"""Wedge benchmark: containment of a confidently wrong learned controller.

This is the demonstration that separates the Argus enforcement boundary from a
library. It runs two arms over the same declared scenario and fault corpus:

  baseline  the controller's output goes to the actuator;
  argus     the controller's output enters the safety envelope as a proposal
            and only the envelope's output reaches the actuator.

The controller is a declared nearest-centroid linear policy, not a caricature.
Its features are per-channel signal means, which is the cheapest thing a real
controller can compute. That choice creates the documented failure mode of
learned controllers on this class of sensor:

  a motion pattern is a zero-mean alternating signal, so its per-channel mean is
  zero. A dead sensor's per-channel mean is also zero. The controller cannot
  distinguish "no signal" from "zero-mean motion", and on a dead sensor it keeps
  proposing motion with high confidence.

That failure is not a defect of this particular controller. It is the reason a
runtime enforcement boundary exists: the controller has no representation for
"the sensor is gone", so it cannot be trusted to notice.

Every number is a digital-source result on generated data. This benchmark does
not measure hardware, silicon, power, thermal behaviour, or field performance,
and it does not compare Argus against any other product.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..safety import (
    ActionProvenance,
    AuthorityScope,
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    ProposedAction,
    SafetyConfig,
    SensorHealthGate,
)

__all__ = [
    "WedgeFault",
    "WedgeResult",
    "DeclaredLinearController",
    "build_wedge_fault_corpus",
    "run_wedge_benchmark",
    "write_wedge_report",
]

_EVIDENCE_CLASS = "digital_source_verification"

# Declared class centroids in per-channel mean space. The flexion centroid sits
# at the origin because the motion pattern is zero-mean; that is what makes a
# dead sensor indistinguishable from motion to a mean-based controller.
_CENTROIDS = {
    "rest": np.array([10.0, -10.0, 10.0, -10.0]),
    "knee_flexion": np.array([0.0, 0.0, 0.0, 0.0]),
    "knee_extension": np.array([30.0, 30.0, 30.0, 30.0]),
}


@dataclass(frozen=True)
class WedgeFault:
    """One declared fault in the wedge corpus.

    Attributes:
        name: Fault identifier used in the report.
        kind: One of ``flatline``, ``saturation``, ``shift``, ``drift``.
        onset: Window index the fault starts at.
        duration: Number of windows the fault lasts.
        channels: Channel indices the fault applies to. An empty tuple means all.
        magnitude: Fault strength in declared reference standard deviations.
    """

    name: str
    kind: str
    onset: int
    duration: int
    channels: tuple[int, ...] = ()
    magnitude: float = 12.0

    def __post_init__(self) -> None:
        if self.kind not in {"flatline", "saturation", "shift", "drift"}:
            raise ValueError(f"unknown fault kind {self.kind!r}")
        if self.onset < 0 or self.duration < 1:
            raise ValueError("fault onset must be non-negative and duration at least 1")
        if not math.isfinite(self.magnitude) or self.magnitude < 0:
            raise ValueError("fault magnitude must be a non-negative finite number")


def build_wedge_fault_corpus() -> tuple[WedgeFault, ...]:
    """Return the declared wedge fault corpus."""
    return (
        WedgeFault("flatline_single_channel", "flatline", onset=50, duration=50, channels=(0,)),
        WedgeFault("flatline_all_channels", "flatline", onset=50, duration=50),
        WedgeFault("saturation", "saturation", onset=50, duration=50),
        WedgeFault("mean_shift", "shift", onset=50, duration=50),
        WedgeFault("slow_drift", "drift", onset=50, duration=50, magnitude=6.0),
    )


class DeclaredLinearController:
    """A declared nearest-centroid linear policy.

    Nearest-centroid classification is linear in the features:
    ``argmin_c ||f - centroid_c||^2`` equals ``argmax_c (2 f . centroid_c -
    ||centroid_c||^2)``, so the policy is a weight matrix and a bias, which is
    what makes it inspectable and reproducible.

    Args:
        intents: Intent labels, which must be keys of the declared centroids.
        confidence_gain: Softmax sharpness.
        model_id: Declared model identity carried on every proposal.
        model_version: Declared model version.
    """

    def __init__(
        self,
        intents: tuple[str, ...] = ("rest", "knee_flexion", "knee_extension"),
        *,
        confidence_gain: float = 6.0,
        model_id: str = "wedge-linear-controller",
        model_version: str = "1.0.0",
    ) -> None:
        if confidence_gain <= 0:
            raise ValueError("confidence_gain must be positive")
        unknown = [intent for intent in intents if intent not in _CENTROIDS]
        if unknown:
            raise ValueError(f"no declared centroid for intents {unknown}")
        self._intents = tuple(intents)
        self._weights = np.array([2.0 * _CENTROIDS[i] for i in self._intents])
        self._bias = np.array([-float(_CENTROIDS[i] @ _CENTROIDS[i]) for i in self._intents])
        self._gain = float(confidence_gain)
        self._model_id = model_id
        self._model_version = model_version

    @property
    def intents(self) -> tuple[str, ...]:
        return self._intents

    @property
    def model_id(self) -> str:
        return self._model_id

    def propose(self, window: np.ndarray, provenance: ActionProvenance) -> ProposedAction:
        """Return the proposal for one window of shape (samples, channels)."""
        if window.ndim != 2:
            raise ValueError(f"window shape {window.shape} is not a decision window")
        features = window.mean(axis=0)
        scores = self._weights @ features + self._bias
        scaled = self._gain * (scores - scores.max())
        exp = np.exp(scaled)
        probabilities = exp / exp.sum()
        index = int(np.argmax(probabilities))
        return ProposedAction(
            intent=self._intents[index],
            confidence=round(float(probabilities[index]), 6),
            provenance=provenance,
        )


def _nominal_request(intent: str) -> tuple[float, float]:
    return {"rest": (0.0, 0.0), "knee_flexion": (25.0, 3.0), "knee_extension": (25.0, 3.0)}.get(
        intent, (0.0, 0.0)
    )


def _scenario_windows(
    n_windows: int, samples_per_window: int, n_channels: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Generate the declared scenario: sensor windows and true intent labels.

    Shape is (n_windows, samples_per_window, n_channels). Windows 0-49 and 150
    upward are motion; the declared profile for each motion window matches the
    centroid of its intent. Rest carries the sensor's quiescent DC pattern.
    """
    if n_channels != 4:
        raise ValueError("the declared scenario uses 4 channels")
    rng = np.random.default_rng(seed)
    third = n_windows // 3
    labels = np.array(
        ["knee_flexion"] * third + ["rest"] * third + ["knee_extension"] * (n_windows - 2 * third)
    )
    windows = np.empty((n_windows, samples_per_window, n_channels), dtype=np.float64)
    for intent in set(labels.tolist()):
        centroid = _CENTROIDS[intent]
        rows = np.nonzero(labels == intent)[0]
        windows[rows] = rng.normal(
            loc=centroid, scale=20.0, size=(rows.size, samples_per_window, n_channels)
        )
    return windows, labels


def _apply_fault(
    windows: np.ndarray, fault: WedgeFault, reference_std: np.ndarray
) -> np.ndarray:
    """Return a copy of the windows with one fault applied over its window range."""
    out = windows.copy()
    n_channels = out.shape[2]
    channels = list(fault.channels or range(n_channels))
    end = min(fault.onset + fault.duration, out.shape[0])
    span = slice(fault.onset, end)
    if fault.kind == "flatline":
        out[span, :, channels] = 0.0
    elif fault.kind == "saturation":
        block = out[span, :, channels]
        scale = np.max(np.abs(block)) + 1e-9
        out[span, :, channels] = block / scale * 0.999
    elif fault.kind == "shift":
        out[span, :, channels] += fault.magnitude * reference_std[channels]
    elif fault.kind == "drift":
        length = end - fault.onset
        ramp = np.linspace(0.0, 1.0, length, endpoint=True)[:, None, None]
        out[span, :, channels] += fault.magnitude * ramp * reference_std[channels]
    return out


@dataclass
class WedgeResult:
    """Outcome of the wedge benchmark for one fault.

    An unsafe command is a motion command issued while the sensor window is
    faulted. A false stop is a clean window where the boundary suppressed a
    motion command the baseline would have issued.
    """

    fault: str
    baseline_unsafe_commands: int
    argus_unsafe_commands: int
    argus_safe_halt_windows: int
    argus_false_stops: int
    windows: int
    containment_fraction: float
    first_safe_halt_window: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "fault": self.fault,
            "baseline_unsafe_commands": self.baseline_unsafe_commands,
            "argus_unsafe_commands": self.argus_unsafe_commands,
            "argus_safe_halt_windows": self.argus_safe_halt_windows,
            "argus_false_stops": self.argus_false_stops,
            "windows": self.windows,
            "containment_fraction": self.containment_fraction,
            "first_safe_halt_window": self.first_safe_halt_window,
            "detail": self.detail,
        }


def run_wedge_benchmark(
    *,
    n_windows: int = 200,
    samples_per_window: int = 64,
    n_channels: int = 4,
    seed: int = 20260929,
    safety_config: SafetyConfig | None = None,
) -> dict[str, Any]:
    """Run the wedge benchmark over the declared fault corpus.

    Args:
        n_windows: Number of decision windows in the scenario.
        samples_per_window: Sensor samples per decision window.
        n_channels: Sensor channels; the declared scenario uses 4.
        seed: Deterministic seed for the generated sensor data.
        safety_config: Envelope configuration; defaults to ``SafetyConfig()``.

    Returns:
        A report mapping with the per-fault results and the aggregate containment.
    """
    if n_windows < 30:
        raise ValueError("n_windows must be at least 30")
    if samples_per_window < 2:
        raise ValueError("samples_per_window must be at least 2")
    if n_channels != 4:
        raise ValueError("the declared scenario uses 4 channels")

    config = safety_config or SafetyConfig()
    windows, labels = _scenario_windows(n_windows, samples_per_window, n_channels, seed)
    controller = DeclaredLinearController()
    provenance = ActionProvenance(
        model_id=controller.model_id,
        model_version=controller._model_version,
        profile_id="wedge_benchmark",
        source="local_model",
        issued_at=0.0,
    )
    authority = AuthorityScope(
        profile_id="wedge_benchmark", authorized_model_ids=(controller.model_id,)
    )

    # The reference distribution is declared from clean in-distribution data only.
    gate = SensorHealthGate(flatline_policy="fail_closed")
    gate.declare_reference(windows.reshape(-1, n_channels))
    reference_std = windows.reshape(-1, n_channels).std(axis=0)

    results: list[WedgeResult] = []
    for fault in build_wedge_fault_corpus():
        faulted = _apply_fault(windows, fault, reference_std)
        fault_end = min(fault.onset + fault.duration, n_windows)

        baseline_unsafe = 0
        argus_unsafe = 0
        argus_halt = 0
        argus_false_stops = 0
        first_halt: int | None = None

        envelope = ConfidenceCoupledSafetyEnvelope(config, authority=authority)
        for index in range(n_windows):
            window = faulted[index]
            under_fault = fault.onset <= index < fault_end
            proposal = controller.propose(window, provenance)
            quality = gate.assess(window).as_signal_quality()

            base_torque, _ = _nominal_request(proposal.intent)
            if under_fault and base_torque != 0.0:
                baseline_unsafe += 1

            command = envelope.evaluate_proposal(proposal, quality)
            is_motion = command.torque_nm != 0.0
            if under_fault and is_motion:
                argus_unsafe += 1
            if not under_fault and not is_motion and base_torque != 0.0:
                argus_false_stops += 1
            if command.envelope_state is EnvelopeState.SAFE_HALT:
                argus_halt += 1
                if first_halt is None and under_fault:
                    first_halt = index

        containment = 0.0
        if baseline_unsafe > 0:
            containment = round((baseline_unsafe - argus_unsafe) / baseline_unsafe, 6)

        results.append(
            WedgeResult(
                fault=fault.name,
                baseline_unsafe_commands=baseline_unsafe,
                argus_unsafe_commands=argus_unsafe,
                argus_safe_halt_windows=argus_halt,
                argus_false_stops=argus_false_stops,
                windows=n_windows,
                containment_fraction=containment,
                first_safe_halt_window=first_halt,
                detail={
                    "fault_kind": fault.kind,
                    "fault_onset": fault.onset,
                    "fault_duration": fault.duration,
                    "persistence_windows": config.persistence_windows,
                },
            )
        )

    total_baseline = sum(r.baseline_unsafe_commands for r in results)
    total_argus = sum(r.argus_unsafe_commands for r in results)
    aggregate = round((total_baseline - total_argus) / total_baseline, 6) if total_baseline else 0.0

    return {
        "evidence_class": _EVIDENCE_CLASS,
        "benchmark": "argus_wedge_containment_v0",
        "status": "verification_required",
        "seed": seed,
        "windows": n_windows,
        "samples_per_window": samples_per_window,
        "channels": n_channels,
        "safety_config": {
            "t_high": config.t_high,
            "t_low": config.t_low,
            "persistence_windows": config.persistence_windows,
        },
        "boundary": (
            "Digital source verification on generated data. No hardware, silicon, "
            "power, thermal, field, or comparative product claim is established."
        ),
        "results": [r.to_mapping() for r in results],
        "aggregate": {
            "baseline_unsafe_commands": total_baseline,
            "argus_unsafe_commands": total_argus,
            "containment_fraction": aggregate,
        },
    }


def write_wedge_report(result: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    """Write the wedge report as JSON and markdown. Returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "wedge_containment_benchmark.json"
    md_path = out_dir / "wedge_containment_benchmark.md"

    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    aggregate = result["aggregate"]
    lines = [
        "# Argus wedge containment benchmark",
        "",
        f"Evidence class: `{result['evidence_class']}`. {result['boundary']}",
        "",
        "A learned controller keeps proposing motion when its sensor dies. The",
        "baseline passes that proposal to the actuator. Argus treats it as an",
        "untrusted proposal and bounds it.",
        "",
        "| Fault | Baseline unsafe commands | Argus unsafe commands | Containment | First safe halt |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result["results"]:
        lines.append(
            f"| {row['fault']} | {row['baseline_unsafe_commands']} | "
            f"{row['argus_unsafe_commands']} | {row['containment_fraction']:.4f} | "
            f"{row['first_safe_halt_window'] if row['first_safe_halt_window'] is not None else '-'} |"
        )
    lines += [
        "",
        f"Aggregate containment: **{aggregate['containment_fraction']:.4f}** "
        f"({aggregate['baseline_unsafe_commands']} baseline unsafe commands, "
        f"{aggregate['argus_unsafe_commands']} with the enforcement boundary).",
        "",
        "Unsafe command: a motion command issued while the sensor window is faulted.",
        "False stop: a clean window where the boundary suppressed a motion command.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "md": md_path}
