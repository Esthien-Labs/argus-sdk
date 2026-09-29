"""Public tests for the sensor health and out-of-distribution gate."""

from __future__ import annotations

import numpy as np
import pytest

from argus.safety import ConfidenceCoupledSafetyEnvelope, EnvelopeState, Prediction, SafetyConfig, SensorHealthGate


def _reference(n_samples: int = 400, n_channels: int = 4, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(loc=0.0, scale=20.0, size=(n_samples, n_channels))


def _window(n_samples: int = 64, n_channels: int = 4, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(loc=0.0, scale=20.0, size=(n_samples, n_channels))


def test_gate_requires_a_declared_reference() -> None:
    gate = SensorHealthGate()
    with pytest.raises(ValueError):
        gate.assess(_window())


def test_declare_reference_rejects_zero_variance_channel() -> None:
    gate = SensorHealthGate()
    reference = _reference()
    reference[:, 2] = 0.0
    with pytest.raises(ValueError):
        gate.declare_reference(reference)


def test_in_distribution_window_keeps_full_reliability() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    health = gate.assess(_window(seed=3))
    assert not health.out_of_distribution
    assert health.ood_score == 0.0
    assert health.reliability == 1.0
    assert health.flags == ()


def test_shifted_window_is_detected_as_out_of_distribution() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    shifted = _window() + 400.0
    health = gate.assess(shifted)
    assert health.out_of_distribution
    assert health.ood_score == 1.0
    assert "out_of_distribution" in health.flags
    assert health.reliability < 1.0


def test_flatline_is_detected_and_penalised() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    dead = _window()
    dead[:, 1] = 0.0
    health = gate.assess(dead)
    assert health.flatline_channels == (1,)
    assert "flatline" in health.flags
    assert health.reliability == pytest.approx(0.75, abs=1e-6)


def test_ood_penalty_compounds_with_flatline() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    window = _window() + 400.0
    window[:, 1] = 0.0
    health = gate.assess(window)
    assert "flatline" in health.flags
    assert "out_of_distribution" in health.flags
    # Three of four channels are out of distribution, so the out-of-distribution
    # penalty is (1 - 0.75). Saturation may also apply on the shifted channels.
    assert health.reliability <= 0.75 * (1 - 0.75) + 1e-9


def test_health_plugs_into_the_envelope_unchanged() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    health = gate.assess(_window(seed=5))
    command = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.92),
        health.as_signal_quality(),
        requested_torque_nm=20.0,
        requested_velocity_rad_s=2.0,
    )
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.effective_confidence == pytest.approx(0.92 * health.reliability, abs=1e-6)


def test_out_of_distribution_input_holds_the_envelope_back() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    healthy = gate.assess(_window(seed=5))
    shifted = gate.assess(_window(seed=5) + 400.0)
    good = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.92), healthy.as_signal_quality(), 20.0, 2.0
    )
    bad = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.92), shifted.as_signal_quality(), 20.0, 2.0
    )
    assert good.envelope_state is EnvelopeState.NOMINAL
    assert bad.envelope_state is not EnvelopeState.NOMINAL
    assert bad.effective_confidence < good.effective_confidence


def test_channel_count_mismatch_is_rejected() -> None:
    gate = SensorHealthGate()
    gate.declare_reference(_reference())
    with pytest.raises(ValueError):
        gate.assess(_window(n_channels=3))


def test_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        SensorHealthGate(flatline_std=0.0)
    with pytest.raises(ValueError):
        SensorHealthGate(clip_ratio=1.0)
    with pytest.raises(ValueError):
        SensorHealthGate(ood_z_threshold=0.0)
    with pytest.raises(ValueError):
        SensorHealthGate(ood_channel_fraction=0.0)
