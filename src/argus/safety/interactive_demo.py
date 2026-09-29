"""Interactive showcase and simulation harness for Patent Candidate PAT-001.

Patent Title:
Method, System, and Hardware Architecture for Dynamic Kinematic Bound Modulation
Coupled to Probabilistic Intent Confidence and Signal Reliability.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .envelope import (
    ActuatorCommand,
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    IndependentHardwareSupervisor,
    Prediction,
    SafetyConfig,
    SignalQualityGate,
)


@dataclass(frozen=True)
class DemoFrameRecord:
    step: int
    phase: str
    intent: str
    confidence: float
    reliability: float
    effective_confidence: float
    state: str
    torque_nm: float
    velocity_rad_s: float
    vetoed: bool


def _ascii_bar(value: float, max_len: int = 20) -> str:
    filled = int(round(np.clip(value, 0.0, 1.0) * max_len))
    return "[" + "#" * filled + "-" * (max_len - filled) + "]"


def run_pat001_showcase(
    steps_per_phase: int = 10,
    mode: str = "verification",
    inject_adversarial_override: bool = True,
    interactive_delay_s: float = 0.0,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute PAT-001 in explicit smoke or verification mode."""
    if mode not in {"smoke", "verification"}:
        raise ValueError("mode must be 'smoke' or 'verification'")
    if steps_per_phase <= 0:
        raise ValueError("steps_per_phase must be positive")
    if interactive_delay_s < 0.0:
        raise ValueError("interactive_delay_s must be non-negative")

    cfg = SafetyConfig(
        t_high=0.75,
        t_low=0.45,
        degraded_velocity_scale=0.5,
        degraded_force_scale=0.4,
        hard_max_torque_nm=40.0,
        hard_max_velocity_rad_s=6.0,
        persistence_windows=3,
    )
    sqg = SignalQualityGate(flatline_std_uv=5.0, clip_ratio=0.98)
    envelope = ConfidenceCoupledSafetyEnvelope(cfg)
    supervisor = IndependentHardwareSupervisor(cfg)

    # Scenarios: (Phase Name, Base EMG Std, Noise Amplitude, Intended Class, Confidence)
    phases = [
        ("Nominal Intent", 45.0, 2.0, "knee_flexion", 0.95),
        ("Electrode Impedance Shift", 12.0, 15.0, "knee_flexion", 0.70),
        ("Severe Motion Artifact / Clipping", 180.0, 120.0, "knee_flexion", 0.55),
        ("Electrode Liftoff (Flatline)", 1.0, 0.5, "knee_extension", 0.85),
        ("Signal Restored & High Confidence", 50.0, 2.0, "knee_extension", 0.98),
    ]

    records: list[DemoFrameRecord] = []
    total_step = 0

    print("=" * 80)
    print("PAT-001: CONFIDENCE-COUPLED SAFETY ENVELOPE & HARDWARE SUPERVISOR")
    print("Deterministic Actuation Bounds Supervised by Effective Confidence (C_eff = C * R)")
    print("=" * 80)
    print(
        f"{'STEP':<5} | {'PHASE':<28} | {'C_eff':<8} | {'STATE':<10} | "
        f"{'TORQUE':<8} | {'VELOCITY':<8} | {'VETO':<5}"
    )
    print("-" * 80)

    for phase_name, emg_std, noise_amp, intent_class, base_conf in phases:
        for _ in range(steps_per_phase):
            total_step += 1
            # Generate 8-channel synthetic EMG window (64 samples per channel)
            rng = np.random.default_rng(seed=total_step * 1007)
            raw_signal = rng.normal(loc=0.0, scale=emg_std, size=(64, 8))
            noise = rng.normal(loc=0.0, scale=noise_amp, size=(64, 8))
            emg_window = raw_signal + noise

            # If liftoff, zero out 4 channels to simulate disconnection
            if "Liftoff" in phase_name:
                emg_window[:, :4] = 0.0

            # Assess reliability R
            quality = sqg.assess(emg_window)
            pred = Prediction(intent=intent_class, confidence=base_conf)

            # Evaluate dynamic envelope
            cmd: ActuatorCommand = envelope.evaluate(pred, quality)

            # If adversarial test is enabled on step 15, simulate software glitch pushing 90 Nm
            vetoed = cmd.vetoed_by_supervisor
            if inject_adversarial_override and total_step == 15:
                glitched_cmd = ActuatorCommand(
                    intent=cmd.intent,
                    torque_nm=95.0,
                    velocity_rad_s=12.0,
                    envelope_state=cmd.envelope_state,
                    effective_confidence=cmd.effective_confidence,
                    vetoed_by_supervisor=False,
                )
                cmd = supervisor.supervise(glitched_cmd)
                vetoed = cmd.vetoed_by_supervisor

            rec = DemoFrameRecord(
                step=total_step,
                phase=phase_name,
                intent=cmd.intent,
                confidence=pred.confidence,
                reliability=quality.reliability,
                effective_confidence=cmd.effective_confidence,
                state=cmd.envelope_state.value.upper(),
                torque_nm=round(cmd.torque_nm, 2),
                velocity_rad_s=round(cmd.velocity_rad_s, 2),
                vetoed=vetoed,
            )
            records.append(rec)

            gauge = _ascii_bar(cmd.effective_confidence, max_len=10)
            veto_str = "VETO!" if vetoed else "OK"
            print(
                f"{total_step:<5} | {phase_name[:28]:<28} | "
                f"{cmd.effective_confidence:.3f} {gauge} | {rec.state:<10} | "
                f"{cmd.torque_nm:>5.1f} Nm | {cmd.velocity_rad_s:>5.1f} r/s | {veto_str:<5}"
            )

            if interactive_delay_s > 0.0:
                time.sleep(interactive_delay_s)

    # Summary analysis
    states_count = {
        "NOMINAL": sum(1 for r in records if r.state == "NOMINAL"),
        "DEGRADED": sum(1 for r in records if r.state == "DEGRADED"),
        "SAFE_HALT": sum(1 for r in records if r.state == "SAFE_HALT"),
    }
    vetoes_count = sum(1 for r in records if r.vetoed)
    incomplete_reasons: list[str] = []
    if mode == "verification":
        if not inject_adversarial_override:
            incomplete_reasons.append("adversarial override was disabled")
        if len(records) < 15:
            incomplete_reasons.append(
                "the verification profile requires at least 15 frames to reach the step-15 override"
            )

    verified_containment = states_count["SAFE_HALT"] > 0 and vetoes_count > 0
    verification_complete = mode == "verification" and not incomplete_reasons and verified_containment
    if mode == "smoke":
        status = "SMOKE_COMPLETE"
    elif incomplete_reasons:
        status = "INCOMPLETE_TEST"
    elif verification_complete:
        status = "VERIFIED"
    else:
        status = "FAILED_VERIFICATION"

    summary = {
        "patent_id": "PAT-001",
        "title": "Confidence-Coupled Safety Envelope Demonstration",
        "total_frames_evaluated": len(records),
        "state_distribution": states_count,
        "hardware_supervisory_vetoes": vetoes_count,
        "parameters": asdict(cfg),
        "test_mode": mode,
        "status": status,
        "verification_complete": verification_complete,
        "incomplete_reasons": incomplete_reasons,
        "verified_containment": verified_containment,
        "records": [asdict(r) for r in records],
    }

    print("=" * 80)
    print("PAT-001 VERIFICATION SUMMARY:")
    print(f"  - Total Frames Processed: {len(records)}")
    print(f"  - Nominal Envelope Frames: {states_count['NOMINAL']}")
    print(f"  - Damped Degraded Frames:  {states_count['DEGRADED']}")
    print(f"  - Safe Halt Containments:  {states_count['SAFE_HALT']}")
    print(f"  - Hardware Bounds Vetoes:  {vetoes_count}")
    if status == "VERIFIED":
        status_text = "VERIFIED (all required scenarios executed)"
    elif status == "SMOKE_COMPLETE":
        status_text = "SMOKE COMPLETE (not a verification result)"
    elif status == "INCOMPLETE_TEST":
        status_text = "INCOMPLETE TEST (verification scenarios were not all executed)"
    else:
        status_text = "FAILED VERIFICATION"
    print(f"  - Safety Integrity Status: {status_text}")
    for reason in incomplete_reasons:
        print(f"  - Incomplete Test Reason: {reason}")
    print("=" * 80)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_dir / "pat001_safety_showcase_report.json"
        out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Report saved to: {out_file}")

    return summary
