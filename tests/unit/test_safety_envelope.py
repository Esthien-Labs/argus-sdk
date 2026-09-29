"""Public tests for the confidence-coupled safety envelope.

Exercises the released API surface only: ``argus.safety``.
"""

from __future__ import annotations

import pytest

from argus.safety import (
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    Prediction,
    SafetyConfig,
    SignalQuality,
    SignalQualityGate,
)


def _quality(reliability: float = 1.0) -> SignalQuality:
    return SignalQuality(reliability=reliability, flatline_channels=(), artifact_detected=False)


def test_starts_in_safe_halt() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    assert envelope.state is EnvelopeState.SAFE_HALT


def test_high_confidence_window_reaches_nominal() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    command = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.92),
        _quality(0.95),
        requested_torque_nm=20.0,
        requested_velocity_rad_s=2.0,
    )
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.torque_nm == 20.0
    assert command.effective_confidence == pytest.approx(0.874, abs=1e-9)


def test_low_confidence_after_persistence_halts() -> None:
    config = SafetyConfig(persistence_windows=2)
    envelope = ConfidenceCoupledSafetyEnvelope(config)
    window = (Prediction(intent="knee_flexion", confidence=0.2), _quality(1.0))
    first = envelope.evaluate_with_request(*window, requested_torque_nm=20.0, requested_velocity_rad_s=2.0)
    second = envelope.evaluate_with_request(*window, requested_torque_nm=20.0, requested_velocity_rad_s=2.0)
    assert first.envelope_state is EnvelopeState.DEGRADED
    assert second.envelope_state is EnvelopeState.SAFE_HALT
    assert second.torque_nm == 0.0
    assert second.velocity_rad_s == 0.0


def test_unknown_intent_fails_safe() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    command = envelope.evaluate(Prediction(intent="unknown_intent", confidence=0.99), _quality(1.0))
    assert command.envelope_state is EnvelopeState.SAFE_HALT


def test_hard_limit_supervisor_clips_and_flags() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(hard_max_torque_nm=10.0))
    command = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.95),
        _quality(1.0),
        requested_torque_nm=25.0,
        requested_velocity_rad_s=2.0,
    )
    assert command.torque_nm == 10.0
    assert command.vetoed_by_supervisor is True


def test_reset_returns_to_safe_halt() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.95),
        _quality(1.0),
        requested_torque_nm=20.0,
        requested_velocity_rad_s=2.0,
    )
    envelope.reset()
    assert envelope.state is EnvelopeState.SAFE_HALT
    assert envelope.low_streak == 0


def test_signal_quality_gate_penalizes_flatline() -> None:
    import numpy as np

    gate = SignalQualityGate()
    dead = np.zeros((16, 4))
    quality = gate.assess(dead)
    assert quality.reliability < 1.0
    assert len(quality.flatline_channels) == 4


def test_rejects_malformed_confidence() -> None:
    with pytest.raises(ValueError):
        Prediction(intent="rest", confidence=1.5)
