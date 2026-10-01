"""Public tests for the software Authority Capability system (AC1)."""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey, VerifyKey

from argus.safety import (
    ActuatorBounds,
    ActionProvenance,
    AuthorityCapability,
    CapabilityError,
    CapabilityStore,
    CapabilityValidity,
    ConfidenceCoupledSafetyEnvelope,
    EnforcementBoundary,
    EnvelopeState,
    ProposedAction,
    SafetyConfig,
    SignalQuality,
    delegate_capability,
)

NOW = 1_000_000.0


def _keys() -> tuple[SigningKey, SigningKey]:
    return SigningKey.generate(), SigningKey.generate()


def _bounds(torque: float = 40.0, velocity: float = 6.0) -> tuple[ActuatorBounds, ...]:
    return (ActuatorBounds("knee_joint", torque, velocity),)


def _validity(**overrides) -> CapabilityValidity:
    values = {"issued_at": NOW - 10.0, "expires_at": NOW + 3600.0}
    values.update(overrides)
    return CapabilityValidity(**values)


def _capability(
    *,
    issuer: str = "esthien-root",
    audience: str = "robot-001",
    intent_classes: tuple[str, ...] = ("knee_flexion", "knee_extension"),
    bounds: tuple[ActuatorBounds, ...] | None = None,
    validity: CapabilityValidity | None = None,
    model_id: str | None = None,
    parent_cap_id: str | None = None,
) -> AuthorityCapability:
    return AuthorityCapability(
        cap_id="cap-001",
        issuer=issuer,
        audience=audience,
        intent_classes=intent_classes,
        bounds=bounds if bounds is not None else _bounds(),
        profile_id="robot_diff_drive_ros2_v0",
        model_id=model_id,
        validity=validity if validity is not None else _validity(),
        parent_cap_id=parent_cap_id,
    )


def _store(
    trusted: dict[str, VerifyKey] | None = None,
    audience: str = "robot-001",
) -> tuple[CapabilityStore, SigningKey]:
    signing = SigningKey.generate()
    keys = trusted if trusted is not None else {"esthien-root": signing.verify_key}
    return CapabilityStore(audience, keys), signing


def _proposal(
    intent: str = "knee_flexion",
    confidence: float = 0.92,
    model_id: str = "planner-v3",
    profile_id: str = "robot_diff_drive_ros2_v0",
) -> ProposedAction:
    return ProposedAction(
        intent=intent,
        confidence=confidence,
        provenance=ActionProvenance(
            model_id=model_id,
            model_version="1.4.2",
            profile_id=profile_id,
            source="hosted_agent",
            issued_at=NOW,
        ),
    )


def _quality(reliability: float = 0.95) -> SignalQuality:
    return SignalQuality(reliability=reliability, flatline_channels=(), artifact_detected=False)


# ---------------------------------------------------------------- capability token


def test_capability_signs_and_verifies() -> None:
    signing = SigningKey.generate()
    signed = _capability().sign(signing)
    assert signed.verify(signing.verify_key) is True
    assert signed.verify(SigningKey.generate().verify_key) is False


def test_unsigned_capability_is_refused_on_load() -> None:
    store, _ = _store()
    assert store.load(_capability(), now=NOW) == "unsigned_capability"


def test_tampered_capability_is_refused_on_load() -> None:
    from dataclasses import replace

    store, signing = _store()
    signed = _capability().sign(signing)
    tampered = replace(signed, intent_classes=("knee_flexion", "unknown_intent"))
    assert store.load(tampered, now=NOW) == "bad_signature"


def test_unknown_issuer_is_refused() -> None:
    signing = SigningKey.generate()
    store, _ = _store(trusted={"other-root": signing.verify_key})
    signed = _capability(issuer="esthien-root").sign(signing)
    assert store.load(signed, now=NOW) == "unknown_issuer"


def test_audience_mismatch_is_refused() -> None:
    store, signing = _store()
    signed = _capability(audience="other-device").sign(signing)
    assert store.load(signed, now=NOW) == "audience_mismatch"


def test_expired_capability_is_refused() -> None:
    store, signing = _store()
    signed = _capability(validity=_validity(expires_at=NOW - 1.0)).sign(signing)
    assert store.load(signed, now=NOW) == "expired"


def test_offline_grace_extends_validity() -> None:
    store, signing = _store()
    validity = CapabilityValidity(issued_at=NOW - 100.0, expires_at=NOW - 30.0, offline_grace_s=60.0)
    signed = _capability(validity=validity).sign(signing)
    assert store.load(signed, now=NOW) is None


def test_not_yet_valid_is_refused() -> None:
    store, signing = _store()
    signed = _capability(validity=_validity(issued_at=NOW + 10.0, expires_at=NOW + 100.0)).sign(signing)
    assert store.load(signed, now=NOW) == "not_yet_valid"


def test_capability_rejects_malformed_fields() -> None:
    with pytest.raises(CapabilityError):
        _capability(intent_classes=())
    with pytest.raises(CapabilityError):
        _capability(bounds=())
    with pytest.raises(CapabilityError):
        _capability(bounds=_bounds(torque=-1.0))
    with pytest.raises(CapabilityError):
        _capability(issuer="")


# ---------------------------------------------------------------- revocation


def test_revocation_is_local_and_immediate() -> None:
    store, signing = _store()
    assert store.load(_capability().sign(signing), now=NOW) is None
    store.revoke("cap-001")
    assert store.is_revoked("cap-001")
    assert store.load(_capability().sign(signing), now=NOW) == "revoked"
    assert store.check_proposal(_proposal(), now=NOW) == "revoked"


def test_revoking_a_parent_refuses_the_derived_capability() -> None:
    store, signing = _store()
    parent = _capability().sign(signing)
    assert store.load(parent, now=NOW) is None
    derived = delegate_capability(
        parent,
        signing_key=signing,
        cap_id="cap-002",
        issuer="esthien-root",
        audience="robot-001",
        intent_classes=("knee_flexion",),
        bounds=_bounds(torque=20.0),
        validity=_validity(),
    )
    assert store.load(derived, now=NOW) is None
    store.revoke("cap-001")
    assert store.check_proposal(_proposal(), now=NOW) == "parent_revoked"


# ---------------------------------------------------------------- delegation


def test_delegation_must_be_strictly_narrower() -> None:
    store, signing = _store()
    parent = _capability().sign(signing)
    with pytest.raises(CapabilityError):
        delegate_capability(
            parent,
            signing_key=signing,
            cap_id="cap-wide",
            issuer="esthien-root",
            audience="robot-001",
            intent_classes=("knee_flexion", "brand_new_intent"),
            bounds=_bounds(),
            validity=_validity(),
        )
    with pytest.raises(CapabilityError):
        delegate_capability(
            parent,
            signing_key=signing,
            cap_id="cap-loose",
            issuer="esthien-root",
            audience="robot-001",
            intent_classes=("knee_flexion",),
            bounds=_bounds(torque=80.0),
            validity=_validity(),
        )
    with pytest.raises(CapabilityError):
        delegate_capability(
            parent,
            signing_key=signing,
            cap_id="cap-late",
            issuer="esthien-root",
            audience="robot-001",
            intent_classes=("knee_flexion",),
            bounds=_bounds(),
            validity=_validity(expires_at=NOW + 99999.0),
        )


def test_unsigned_parent_cannot_delegate() -> None:
    _, signing = _store()
    with pytest.raises(CapabilityError):
        delegate_capability(
            _capability(),
            signing_key=signing,
            cap_id="cap-002",
            issuer="esthien-root",
            audience="robot-001",
            intent_classes=("knee_flexion",),
            bounds=_bounds(torque=20.0),
            validity=_validity(),
        )


def test_delegated_capability_lands_in_its_own_store() -> None:
    root_signing = SigningKey.generate()
    parent = _capability().sign(root_signing)
    derived = delegate_capability(
        parent,
        signing_key=root_signing,
        cap_id="cap-002",
        issuer="esthien-root",
        audience="arm-001",
        intent_classes=("knee_flexion",),
        bounds=_bounds(torque=20.0, velocity=3.0),
        validity=_validity(),
    )
    arm_store = CapabilityStore("arm-001", {"esthien-root": root_signing.verify_key})
    assert arm_store.load(derived, now=NOW, parent=parent) is None
    assert derived.parent_cap_id == "cap-001"


# ---------------------------------------------------------------- enforcement


def test_authorized_proposal_reaches_the_actuator() -> None:
    store, signing = _store()
    assert store.load(_capability().sign(signing), now=NOW) is None
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(_proposal(), _quality(), now=NOW, requested_torque_nm=20.0, requested_velocity_rad_s=2.0)
    assert command.envelope_state is EnvelopeState.NOMINAL
    assert command.torque_nm == 20.0
    assert command.refusal_reason is None


def test_unauthorized_intent_is_refused_without_motion() -> None:
    store, signing = _store()
    assert store.load(_capability(intent_classes=("knee_flexion",)).sign(signing), now=NOW) is None
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(
        _proposal(intent="knee_extension"), _quality(), now=NOW, requested_torque_nm=20.0, requested_velocity_rad_s=2.0
    )
    assert command.envelope_state is EnvelopeState.SAFE_HALT
    assert command.torque_nm == 0.0
    assert command.refusal_reason == "intent_not_authorized"
    assert boundary.refusals == ("intent_not_authorized",)


def test_no_capability_loaded_refuses_everything() -> None:
    store, _ = _store()
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(_proposal(), _quality(), now=NOW)
    assert command.refusal_reason == "no_capability_loaded"
    assert command.torque_nm == 0.0


def test_model_bound_capability_refuses_other_models() -> None:
    store, signing = _store()
    assert store.load(_capability(model_id="planner-v3").sign(signing), now=NOW) is None
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(
        _proposal(model_id="untrusted-model"), _quality(), now=NOW, requested_torque_nm=20.0, requested_velocity_rad_s=2.0
    )
    assert command.refusal_reason == "model_not_authorized"
    assert command.torque_nm == 0.0


def test_command_is_clamped_to_the_capability_bounds() -> None:
    store, signing = _store()
    assert store.load(_capability(bounds=_bounds(torque=10.0, velocity=1.0)).sign(signing), now=NOW) is None
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(
        _proposal(), _quality(), now=NOW, requested_torque_nm=40.0, requested_velocity_rad_s=4.0
    )
    assert command.torque_nm == 10.0
    assert command.velocity_rad_s == 1.0
    assert command.vetoed_by_supervisor is True


def test_envelope_still_gates_confidence_inside_the_boundary() -> None:
    store, signing = _store()
    assert store.load(_capability().sign(signing), now=NOW) is None
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    dead_sensor = SignalQuality(reliability=0.1, flatline_channels=(0, 1, 2, 3), artifact_detected=False)
    command = boundary.evaluate_proposal(
        _proposal(), dead_sensor, now=NOW, requested_torque_nm=20.0, requested_velocity_rad_s=2.0
    )
    assert command.envelope_state is not EnvelopeState.NOMINAL
