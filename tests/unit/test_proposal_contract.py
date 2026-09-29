"""Public tests for the proposal contract.

A proposal from an AI system is not a command. These tests pin the semantics:
provenance is mandatory, authority scope is enforced, and a refused proposal
produces a SAFE_HALT command that never reaches the actuator path.
"""

from __future__ import annotations

import time

import pytest

from argus.safety import (
    ActionProvenance,
    ActuatorCommand,
    AuthorityScope,
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    Prediction,
    ProposedAction,
    SafetyConfig,
    SignalQuality,
)


def _provenance(
    model_id: str = "planner-v3",
    profile_id: str = "robot_diff_drive_ros2_v0",
) -> ActionProvenance:
    return ActionProvenance(
        model_id=model_id,
        model_version="1.4.2",
        profile_id=profile_id,
        source="hosted_agent",
        issued_at=time.time(),
    )


def _proposal(
    intent: str = "knee_flexion",
    confidence: float = 0.92,
    **kwargs,
) -> ProposedAction:
    return ProposedAction(
        intent=intent,
        confidence=confidence,
        provenance=_provenance(**kwargs),
    )


def _quality(reliability: float = 0.95) -> SignalQuality:
    return SignalQuality(reliability=reliability, flatline_channels=(), artifact_detected=False)


def test_provenance_requires_identity_fields() -> None:
    with pytest.raises(ValueError):
        ActionProvenance("", "1.0", "p", "cloud", 1.0)
    with pytest.raises(ValueError):
        ActionProvenance("m", "1.0", "", "cloud", 1.0)


def test_provenance_rejects_nonfinite_timestamp() -> None:
    with pytest.raises(ValueError):
        ActionProvenance("m", "1.0", "p", "cloud", float("nan"))


def test_proposal_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        ProposedAction("rest", 1.4, _provenance())


def test_proposal_without_authority_scope_is_evaluated() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    command = envelope.evaluate_proposal(_proposal(), _quality())
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.refusal_reason is None
    assert envelope.refusals == 0


def test_proposal_with_request_reaches_nominal() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    command = envelope.evaluate_proposal(_proposal(), _quality(), 20.0, 2.0)
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.torque_nm == 20.0
    assert command.effective_confidence == pytest.approx(0.874, abs=1e-9)


def test_unknown_model_is_refused_and_halted() -> None:
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0", authorized_model_ids=("planner-v3",))
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)
    command = envelope.evaluate_proposal(
        _proposal(model_id="untrusted-model"), _quality(), 20.0, 2.0
    )
    assert command.envelope_state is EnvelopeState.SAFE_HALT
    assert command.torque_nm == 0.0
    assert command.velocity_rad_s == 0.0
    assert command.refusal_reason == "model_not_authorized"
    assert envelope.refusals == 1


def test_profile_mismatch_is_refused() -> None:
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0")
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)
    command = envelope.evaluate_proposal(_proposal(profile_id="other_profile"), _quality())
    assert command.envelope_state is EnvelopeState.SAFE_HALT
    assert command.refusal_reason == "profile_mismatch"


def test_authorized_model_is_accepted() -> None:
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0", authorized_model_ids=("planner-v3",))
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)
    command = envelope.evaluate_proposal(_proposal(), _quality(), 20.0, 2.0)
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.refusal_reason is None


def test_refusal_does_not_advance_the_low_streak() -> None:
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0", authorized_model_ids=("planner-v3",))
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)
    for _ in range(5):
        envelope.evaluate_proposal(_proposal(model_id="untrusted"), _quality())
    assert envelope.refusals == 5
    assert envelope.low_streak == 0


def test_refused_proposal_never_yields_motion() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0", authorized_model_ids=("planner-v3",))
    envelope._authority = authority
    command = envelope.evaluate_proposal(
        _proposal(model_id="anything"), _quality(1.0), 999.0, 999.0
    )
    assert isinstance(command, ActuatorCommand)
    assert command.torque_nm == 0.0 and command.velocity_rad_s == 0.0


def test_recovery_after_refusal_requires_high_confidence() -> None:
    authority = AuthorityScope(profile_id="robot_diff_drive_ros2_v0", authorized_model_ids=("planner-v3",))
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)
    envelope.evaluate_proposal(_proposal(model_id="untrusted"), _quality())
    assert envelope.state is EnvelopeState.SAFE_HALT
    command = envelope.evaluate_proposal(_proposal(confidence=0.9), _quality(), 20.0, 2.0)
    assert command.envelope_state is EnvelopeState.NOMINAL


def test_prediction_api_is_unchanged() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
    command = envelope.evaluate_with_request(
        Prediction(intent="knee_flexion", confidence=0.92), _quality(), 20.0, 2.0
    )
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.refusal_reason is None
