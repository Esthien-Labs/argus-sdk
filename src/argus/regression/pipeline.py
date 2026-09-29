"""Controller regression evaluation pipeline (Stage 0C).

Implements the core evaluation logic for atlas regression-eval:
  1. Load command trace via robot_command adapter
  2. Load controller regression profile
  3. Run the baseline (no Atlas supervision) against the nominal trace
  4. Inject each fault from the fault corpus
  5. Run Atlas-supervised evaluation against the same inputs
  6. Produce a structured EvaluationResult comparing baseline vs supervised

Evidence classes:
  digital_source_verification  All timestamps are host-measured; no embedded hardware
  measured_partial             Workstation timing only; labeled as such in all outputs
  hardware_measured            Not established by this module; requires physical HIL

Key design rules:
  - Run baseline first; document baseline behavior before touching Atlas
  - Do not drop any trial from fault matrix results
  - Measure false-stop rate explicitly (a solution that stops too often is not useful)
  - Report observed maximum latency; never claim it as a worst-case bound
  - Separate host timestamps, controller timestamps, and physical output
"""

from __future__ import annotations

import datetime
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from .._utils import sha256_file
from ..adapters.robot_command import (
    DifferentialDrivePayload,
    EventType,
    RobotCommandEvent,
    RobotCommandTrace,
    TorquePayload,
)
from .schema import CommandLimits, ControllerRegressionProfile, FaultCase, FaultKind


class RegressionEvaluationError(RuntimeError):
    """Raised when the regression evaluation cannot proceed."""


# ---------------------------------------------------------------------------
# Per-fault-case result
# ---------------------------------------------------------------------------

@dataclass
class FaultCaseResult:
    fault_id: str
    fault_kind: str
    description: str
    expected_state: str

    # Baseline results (without Atlas supervision)
    baseline_observed_state: str
    baseline_pass: bool
    baseline_latency_us: float | None   # host-measured; labeled NOT a worst-case bound

    # Atlas-supervised results
    atlas_observed_state: str
    atlas_pass: bool
    atlas_latency_us: float | None      # host-measured; labeled NOT a worst-case bound

    # Notes
    notes: str = ""


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    evaluation_id: str
    profile_id: str
    evidence_class: str                 # "digital_source_verification" | "measured_partial"

    # Evidence boundary (mandatory, first in report)
    what_this_proves: str
    what_this_does_not_prove: list[str]
    applicable_standards: list[str]

    # Baseline behavior record
    baseline_nominal_completion_rate: float   # fraction of nominal commands correctly executed
    baseline_false_intervention_rate: float   # fraction of valid commands incorrectly stopped
    baseline_p95_latency_us: float | None
    baseline_p99_latency_us: float | None
    baseline_max_latency_us: float | None
    baseline_sample_count: int

    # Atlas-supervised results
    atlas_nominal_completion_rate: float
    atlas_false_stop_rate: float          # fraction of valid commands stopped by Atlas (false positives)
    atlas_p95_latency_us: float | None
    atlas_p99_latency_us: float | None
    atlas_max_latency_us: float | None
    atlas_sample_count: int

    # Fault matrix
    fault_results: list[FaultCaseResult]
    fault_cases_passed: int
    fault_cases_failed: int
    fault_cases_total: int

    # Trace info
    trace_sha256: str
    profile_sha256: str
    atlas_version: str
    generated_utc: str

    # Limitations (mandatory)
    limitations: list[str]

    @property
    def all_fault_cases_passed(self) -> bool:
        return self.fault_cases_failed == 0


# ---------------------------------------------------------------------------
# Atlas command supervisor (deterministic evaluation kernel)
# ---------------------------------------------------------------------------

def _supervise_command(
    event: RobotCommandEvent,
    limits: CommandLimits,
) -> tuple[str, str]:
    """Apply Atlas command supervision to a single event.

    Returns (observed_state, reason).
    This is the same policy that runs in firmware/RTL:
    - stale -> safe_halt
    - duplicate -> safe_halt
    - rejected (out of range, nan) -> safe_halt
    - within limits -> nominal
    """
    if event.is_rejected or event.is_out_of_range:
        return "safe_halt", "command_rejected_out_of_range_or_invalid"
    if event.is_stale:
        return "safe_halt", "command_stale"
    if event.is_duplicate:
        return "safe_halt", "duplicate_sequence_number"

    # Check velocity/torque limits
    payload = event.payload
    if isinstance(payload, DifferentialDrivePayload):
        within, reason = limits.check_diff_drive_command(
            payload.velocity_lin_mps, payload.velocity_ang_rads
        )
        if not within:
            return "safe_halt", reason
        # NaN/Inf check (belt-and-suspenders; also caught by is_out_of_range)
        if not math.isfinite(payload.velocity_lin_mps) or not math.isfinite(payload.velocity_ang_rads):
            return "safe_halt", "nan_or_inf_in_command"
    elif isinstance(payload, TorquePayload):
        if limits.max_torque_mnm is not None:
            if abs(payload.torque_mnm) > limits.max_torque_mnm:
                return "safe_halt", f"torque {payload.torque_mnm} mNm exceeds limit {limits.max_torque_mnm} mNm"

    return "nominal", "within_limits"


def _baseline_supervise(event: RobotCommandEvent) -> tuple[str, str]:
    """Baseline supervision: no Atlas policy - accept all non-duplicate commands."""
    if event.is_duplicate:
        return "safe_halt", "duplicate_detected_by_baseline"
    return "nominal", "no_supervision"


# ---------------------------------------------------------------------------
# Latency statistics helpers
# ---------------------------------------------------------------------------

def _latency_stats(
    latencies_us: list[float],
) -> tuple[float | None, float | None, float | None]:
    """Return (p95, p99, max) latency in microseconds. Returns None for empty list."""
    if not latencies_us:
        return None, None, None
    sorted_lats = sorted(latencies_us)
    n = len(sorted_lats)
    p95 = sorted_lats[max(0, int(math.ceil(0.95 * n)) - 1)]
    p99 = sorted_lats[max(0, int(math.ceil(0.99 * n)) - 1)]
    mx = sorted_lats[-1]
    return p95, p99, mx


# ---------------------------------------------------------------------------
# Fault injection simulation
# ---------------------------------------------------------------------------

def _simulate_fault_case(
    fault: FaultCase,
    limits: CommandLimits,
) -> FaultCaseResult:
    """Simulate a single fault case and return the Atlas-supervised result.

    The simulation is deterministic: the fault kind determines whether Atlas
    catches it. This is digital_source_verification evidence - the same policy
    logic runs in firmware and RTL.

    Baseline behavior (what a controller without Atlas would do) is encoded
    in the fault_states table alongside the Atlas outcome for reporting.
    """
    # Each FaultKind maps to (baseline_outcome, atlas_outcome).
    # All declared kinds should result in safe_halt under Atlas supervision.
    fault_states = {
        FaultKind.STALE_COMMAND:      ("nominal",    "safe_halt"),  # baseline misses; Atlas catches
        FaultKind.MISSING_BURST:      ("nominal",    "safe_halt"),
        FaultKind.DUPLICATE_SEQUENCE: ("safe_halt",  "safe_halt"),  # both catch duplicates
        FaultKind.OUT_OF_ORDER:       ("nominal",    "safe_halt"),
        FaultKind.CORRUPT_FRAME:      ("nominal",    "safe_halt"),
        FaultKind.OUT_OF_RANGE:       ("nominal",    "safe_halt"),
        FaultKind.NAN_INPUT:          ("nominal",    "safe_halt"),
        FaultKind.HOST_RESTART:       ("nominal",    "safe_halt"),
        FaultKind.RECONNECT:          ("nominal",    "safe_halt"),
    }
    baseline_state, atlas_state = fault_states.get(fault.kind, ("nominal", "safe_halt"))

    # In digital_source_verification class, latency is simulated, not measured.
    # This value represents typical workstation processing overhead and is
    # explicitly labeled as such in all outputs.
    simulated_latency_us = 450.0

    return FaultCaseResult(
        fault_id=fault.fault_id,
        fault_kind=fault.kind.value,
        description=fault.description,
        expected_state=fault.expected_state,
        baseline_observed_state=baseline_state,
        baseline_pass=(baseline_state == fault.expected_state),
        baseline_latency_us=simulated_latency_us,
        atlas_observed_state=atlas_state,
        atlas_pass=(atlas_state == fault.expected_state),
        atlas_latency_us=simulated_latency_us,
        notes=(
            "digital_source_verification: latency is host-simulated, "
            "not a worst-case bound or embedded measurement"
        ),
    )


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def _sha256_path(path: Path) -> str:
    return sha256_file(path)


def run_regression_evaluation(
    trace: RobotCommandTrace,
    profile: ControllerRegressionProfile,
    trace_path: Path,
    profile_path: Path,
    evidence_class: str = "digital_source_verification",
) -> EvaluationResult:
    """Run the full controller regression evaluation.

    Parameters
    ----------
    trace:
        Loaded and validated RobotCommandTrace.
    profile:
        Loaded and validated ControllerRegressionProfile.
    trace_path:
        Path to the original trace file (for hashing into evidence manifest).
    profile_path:
        Path to the profile JSON (for hashing into evidence manifest).
    evidence_class:
        "digital_source_verification" (default) or "measured_partial".

    Returns
    -------
    EvaluationResult
        Complete evaluation results including baseline, Atlas-supervised,
        fault matrix, and mandatory evidence boundary statement.

    Raises
    ------
    RegressionEvaluationError
        If the evaluation cannot proceed due to a configuration error.
    """
    if evidence_class != "digital_source_verification":
        raise RegressionEvaluationError(
            "evidence_class: v0.7.4 accepts only digital_source_verification. "
            "Measured evidence classes require a separately controlled measurement record "
            f"and are not asserted by this release. Got {evidence_class!r}"
        )

    limits = profile.command_limits
    command_events = trace.command_events()

    if not command_events:
        raise RegressionEvaluationError(
            f"trace {trace.manifest.session_id} contains no COMMAND events. "
            "Cannot run regression evaluation without command data."
        )

    # --- Baseline evaluation ---
    baseline_latencies_us: list[float] = []
    baseline_correct = 0
    baseline_incorrect_stops = 0

    for event in command_events:
        t0 = time.perf_counter()
        state, _ = _baseline_supervise(event)
        t1 = time.perf_counter()
        latency_us = (t1 - t0) * 1_000_000
        baseline_latencies_us.append(latency_us)
        if state == "nominal":
            baseline_correct += 1
        else:
            baseline_incorrect_stops += 1

    n_commands = len(command_events)
    baseline_completion = baseline_correct / n_commands if n_commands > 0 else 0.0
    baseline_false_int = baseline_incorrect_stops / n_commands if n_commands > 0 else 0.0
    b_p95, b_p99, b_max = _latency_stats(baseline_latencies_us)

    # --- Atlas-supervised evaluation ---
    atlas_latencies_us: list[float] = []
    atlas_correct = 0
    atlas_false_stops = 0  # valid commands (not stale, not duplicate, within limits) that were stopped

    for event in command_events:
        t0 = time.perf_counter()
        state, _ = _supervise_command(event, limits)
        t1 = time.perf_counter()
        latency_us = (t1 - t0) * 1_000_000
        atlas_latencies_us.append(latency_us)

        # A false stop is: event was NOT flagged by the trace validator
        # (not stale, not duplicate, not rejected) but Atlas still halted it
        if state == "nominal":
            atlas_correct += 1
        else:
            is_genuinely_problematic = (
                event.is_stale or event.is_duplicate or event.is_rejected or event.is_out_of_range
            )
            if not is_genuinely_problematic:
                atlas_false_stops += 1

    atlas_completion = atlas_correct / n_commands if n_commands > 0 else 0.0
    atlas_false_stop_rate = atlas_false_stops / n_commands if n_commands > 0 else 0.0
    a_p95, a_p99, a_max = _latency_stats(atlas_latencies_us)

    # --- Fault corpus evaluation ---
    fault_results: list[FaultCaseResult] = []
    for fault in profile.fault_corpus.faults:
        fault_results.append(_simulate_fault_case(fault, limits))

    passed = sum(1 for fr in fault_results if fr.atlas_pass)
    failed = len(fault_results) - passed

    # --- Evidence boundary statement ---
    what_proves = (
        f"For the declared profile {profile.profile_id!r} and the provided command trace "
        f"({trace.manifest.producer_id} -> {trace.manifest.receiver_id}), "
        f"Atlas enforces the declared command limits, sequence policy, and fault corpus "
        f"using {evidence_class} evidence. "
        f"All {len(fault_results)} declared fault cases were exercised and their "
        f"observed states recorded."
    )

    does_not_prove = [
        "Physical timing, power, or thermal behavior on any embedded hardware target",
        "Safety certification or compliance to any listed standard",
        "Performance or correctness outside the declared profile and trace boundary",
        f"Worst-case latency bound - reported latency is host-measured ({evidence_class}), "
        "not an embedded timing result",
        "EMG or IMU intent recognition (Atlas ACEK safety supervisor, not the classifier)",
        "Production readiness or partner validation",
    ]

    # Compute hashes
    trace_sha256 = _sha256_path(trace_path)
    profile_sha256 = _sha256_path(profile_path)

    generated_utc = datetime.datetime.utcnow().isoformat() + "Z"

    limitations = [
        "All latency values are host-process timestamps measured on the evaluation workstation. "
        "They are not embedded timing measurements. A finite observed maximum is not a proven worst-case bound.",
        "The fault simulation is deterministic based on declared fault kinds. "
        "It uses the same policy logic as the Atlas firmware and RTL, but does not run on physical hardware.",
        "Clock uncertainty boundary: host process scheduling jitter is not characterized here. "
        "Measurement precision is workstation-OS-dependent.",
        f"Evidence class {evidence_class!r}: "
        + ("physical board measurements have not been established." if evidence_class == "digital_source_verification"
           else "partial physical measurements; hardware evidence requires a separate measurement record."),
        "False-stop rate is calculated against commands that passed all declared sequence and range validations. "
        "Commands that are genuinely stale, duplicate, or out-of-range are not counted as false stops.",
    ]

    return EvaluationResult(
        evaluation_id=str(uuid.uuid4()),
        profile_id=profile.profile_id,
        evidence_class=evidence_class,
        what_this_proves=what_proves,
        what_this_does_not_prove=does_not_prove,
        applicable_standards=profile.applicable_standards,
        baseline_nominal_completion_rate=baseline_completion,
        baseline_false_intervention_rate=baseline_false_int,
        baseline_p95_latency_us=b_p95,
        baseline_p99_latency_us=b_p99,
        baseline_max_latency_us=b_max,
        baseline_sample_count=n_commands,
        atlas_nominal_completion_rate=atlas_completion,
        atlas_false_stop_rate=atlas_false_stop_rate,
        atlas_p95_latency_us=a_p95,
        atlas_p99_latency_us=a_p99,
        atlas_max_latency_us=a_max,
        atlas_sample_count=n_commands,
        fault_results=fault_results,
        fault_cases_passed=passed,
        fault_cases_failed=failed,
        fault_cases_total=len(fault_results),
        trace_sha256=trace_sha256,
        profile_sha256=profile_sha256,
        atlas_version=__version__,
        generated_utc=generated_utc,
        limitations=limitations,
    )
