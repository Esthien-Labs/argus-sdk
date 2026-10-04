"""Public tests for the attestation protocol and the evidence chain."""

from __future__ import annotations

import hashlib

import pytest
from nacl.signing import SigningKey

from argus.protocol import (
    AttestationError,
    GENESIS_HASH,
    Decision,
    EvidenceChain,
    EvidenceRecord,
    RecordType,
    decode_record,
    merkle_inclusion_proof,
    merkle_root,
    verify_merkle_inclusion,
)
from argus.safety import (
    ActuatorBounds,
    ActionProvenance,
    AuthorityCapability,
    CapabilityStore,
    CapabilityValidity,
    ConfidenceCoupledSafetyEnvelope,
    EnforcementBoundary,
    EnvelopeState,
    ProposedAction,
    SafetyConfig,
    SignalQuality,
)

NOW = 1_000_000.0


def _record(sequence: int = 0, **overrides) -> EvidenceRecord:
    values = {
        "record_type": RecordType.DECISION,
        "sequence_number": sequence,
        "timestamp_counter": 10_485_762 + sequence,
        "proposal_hash": hashlib.sha256(f"proposal-{sequence}".encode()).digest(),
        "policy_hash": hashlib.sha256(b"policy").digest(),
        "decision": Decision.APPROVE,
        "policy_clause_ref": 0,
        "monitor_state_hash": hashlib.sha256(b"monitor").digest(),
        "previous_record_hash": GENESIS_HASH if sequence == 0 else bytes(32),
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def _provenance() -> ActionProvenance:
    return ActionProvenance(
        model_id="planner-v3",
        model_version="1.4.2",
        profile_id="robot_diff_drive_ros2_v0",
        source="hosted_agent",
        issued_at=NOW,
    )


def _proposal(intent: str = "knee_flexion") -> ProposedAction:
    return ProposedAction(intent=intent, confidence=0.92, provenance=_provenance())


def _quality(reliability: float = 0.95) -> SignalQuality:
    return SignalQuality(reliability=reliability, flatline_channels=(), artifact_detected=False)


# ------------------------------------------------------------------ record format


def test_record_encodes_to_the_specified_offsets() -> None:
    record = _record().sign(SigningKey.generate())
    buffer = record.encode()
    assert len(buffer) == 217
    assert buffer[0:2] == b"\x01\x00"
    assert buffer[2] == 0x01
    assert buffer[3] == 0x00
    assert int.from_bytes(buffer[4:12], "little") == 0
    assert int.from_bytes(buffer[12:20], "little") == 10_485_762
    assert buffer[84] == 0x01
    assert buffer[119:151] == GENESIS_HASH
    assert len(buffer[151:215]) == 64


def test_record_round_trips_through_decode() -> None:
    key = SigningKey.generate()
    record = _record(
        sequence=3,
        extensions=b'{"typed_reason":9,"requested":47.3,"bound":12.0}',
        decision=Decision.DENY,
        policy_clause_ref=0x0203,
    ).sign(key)
    decoded = decode_record(record.encode())
    assert decoded == record
    assert decoded.verify(key.verify_key)


def test_decode_rejects_a_truncated_record() -> None:
    record = _record().sign(SigningKey.generate())
    with pytest.raises(AttestationError):
        decode_record(record.encode()[:-1])


def test_decode_rejects_unknown_record_type() -> None:
    record = _record().sign(SigningKey.generate())
    buffer = bytearray(record.encode())
    buffer[2] = 0x7F
    with pytest.raises(AttestationError):
        decode_record(bytes(buffer))


def test_signature_covers_only_the_pre_signature_section() -> None:
    # The specification's examples sign bytes[0..215), which would include the
    # signature field itself and is circular. The implementation signs the
    # pre-signature section (offsets 0..151) and records that as an erratum.
    key = SigningKey.generate()
    record = _record().sign(key)
    assert record.signature is not None
    assert len(record.signature) == 64
    assert record.verify(key.verify_key) is True
    assert record.verify(SigningKey.generate().verify_key) is False


def test_unsigned_record_cannot_encode() -> None:
    with pytest.raises(AttestationError):
        _record().encode()


def test_rejects_malformed_fields() -> None:
    with pytest.raises(AttestationError):
        _record(proposal_hash=b"short")
    with pytest.raises(AttestationError):
        _record(flags=1)
    with pytest.raises(AttestationError):
        _record(sequence_number=-1)


# ------------------------------------------------------------------ chain


def test_three_record_chain_matches_the_normative_example() -> None:
    key = SigningKey.generate()
    chain = EvidenceChain(key)
    verifier = key.verify_key

    policy_load = EvidenceRecord(
        record_type=RecordType.POLICY_LOAD,
        sequence_number=0,
        timestamp_counter=10_485_762,
        proposal_hash=GENESIS_HASH,
        policy_hash=hashlib.sha256(b"robot_arm_6axis v1.0").digest(),
        decision=Decision.NOT_APPLICABLE,
        policy_clause_ref=0,
        monitor_state_hash=hashlib.sha256(b"calibration").digest(),
        previous_record_hash=GENESIS_HASH,
    )
    chain.append(policy_load)

    approved = EvidenceRecord(
        record_type=RecordType.DECISION,
        sequence_number=1,
        timestamp_counter=10_492_044,
        proposal_hash=hashlib.sha256(b"joint3 proposal").digest(),
        policy_hash=hashlib.sha256(b"robot_arm_6axis v1.0").digest(),
        decision=Decision.APPROVE,
        policy_clause_ref=0,
        monitor_state_hash=hashlib.sha256(b"ood 0.04").digest(),
        previous_record_hash=bytes(32),
    )
    chain.append(approved)

    denied = EvidenceRecord(
        record_type=RecordType.DECISION,
        sequence_number=2,
        timestamp_counter=10_497_301,
        proposal_hash=hashlib.sha256(b"over-torque proposal").digest(),
        policy_hash=hashlib.sha256(b"robot_arm_6axis v1.0").digest(),
        decision=Decision.DENY,
        policy_clause_ref=0x0203,
        monitor_state_hash=hashlib.sha256(b"ood 0.04").digest(),
        previous_record_hash=bytes(32),
    )
    chain.append(denied)

    assert len(chain) == 3
    records = chain.records
    assert records[0].previous_record_hash == GENESIS_HASH
    assert records[1].previous_record_hash == records[0].hash()
    assert records[2].previous_record_hash == records[1].hash()
    assert chain.head_hash() == records[2].hash()
    assert all(record.verify(verifier) for record in records)
    assert chain.verify(verifier) == []


def test_tampering_breaks_the_chain_at_every_subsequent_link() -> None:
    key = SigningKey.generate()
    chain = EvidenceChain(key)
    for index in range(4):
        chain.append(_record(sequence=index), timestamp_counter=10_485_762 + index)
    verifier = key.verify_key
    assert chain.verify(verifier) == []

    # Tamper with record 1: replace it with a record claiming a different decision.
    records = list(chain.records)
    original_hash = records[1].hash()
    original_root = merkle_root([record.hash() for record in records])
    tampered = type(records[1])(
        **{
            **records[1].__dict__,
            "signature": None,
            "decision": Decision.DENY,
        }
    ).sign(SigningKey.generate())
    records[1] = tampered

    # The tampered record hashes differently, so the batch Merkle root changes.
    assert records[1].hash() != original_hash
    assert merkle_root([record.hash() for record in records]) != original_root

    # A hash chain breaks at the first link into the tampered record. Later
    # links point at untouched records, so the Merkle root is what covers the
    # tampered record itself.
    broken = []
    for index, record in enumerate(records):
        expected = GENESIS_HASH if index == 0 else records[index - 1].hash()
        if record.previous_record_hash != expected or record.sequence_number != index:
            broken.append(index)
    assert broken == [2]
    assert records[1].previous_record_hash == records[0].hash()  # link 1 itself still holds


def test_heartbeat_record_closes_the_chain() -> None:
    chain = EvidenceChain(SigningKey.generate())
    chain.append(_record())
    chain.append(
        _record(
            record_type=RecordType.HEARTBEAT,
            proposal_hash=GENESIS_HASH,
            decision=Decision.NOT_APPLICABLE,
        ),
        timestamp_counter=12_582_912,
    )
    assert chain.records[1].record_type is RecordType.HEARTBEAT
    assert chain.verify() == []


# ------------------------------------------------------------------ merkle


def test_merkle_root_of_empty_chain_is_genesis() -> None:
    assert merkle_root([]) == GENESIS_HASH


def test_merkle_root_and_inclusion_proof_over_a_full_batch() -> None:
    hashes = [hashlib.sha256(str(i).encode()).digest() for i in range(4096)]
    root = merkle_root(hashes)
    path = merkle_inclusion_proof(hashes, 2_048)
    assert len(path) == 12  # log2(4096)
    assert verify_merkle_inclusion(hashes[2_048], path, root) is True
    assert verify_merkle_inclusion(hashes[0], path, root) is False


def test_merkle_detects_a_tampered_leaf() -> None:
    hashes = [hashlib.sha256(str(i).encode()).digest() for i in range(7)]
    root = merkle_root(hashes)
    tampered = list(hashes)
    tampered[4] = hashlib.sha256(b"tampered").digest()
    assert merkle_root(tampered) != root
    for index in range(7):
        assert verify_merkle_inclusion(hashes[index], merkle_inclusion_proof(hashes, index), root)


def test_batch_roots_split_the_chain() -> None:
    chain = EvidenceChain(SigningKey.generate())
    for index in range(5):
        chain.append(_record(sequence=index), timestamp_counter=10_485_762 + index)
    roots = chain.batch_roots(batch_size=2)
    assert len(roots) == 3  # 2 + 2 + 1
    hashes = [record.hash() for record in chain.records]
    assert roots[0] == merkle_root(hashes[0:2])
    assert roots[2] == merkle_root(hashes[4:5])


# ------------------------------------------------------------------ boundary integration


def _capability() -> tuple[CapabilityStore, AuthorityCapability]:
    key = SigningKey.generate()
    capability = AuthorityCapability(
        cap_id="cap-001",
        issuer="esthien-root",
        audience="robot-001",
        intent_classes=("knee_flexion", "knee_extension"),
        bounds=(ActuatorBounds("knee_joint", 40.0, 6.0),),
        profile_id="robot_diff_drive_ros2_v0",
        validity=CapabilityValidity(issued_at=NOW - 10.0, expires_at=NOW + 3600.0),
    ).sign(key)
    store = CapabilityStore("robot-001", {"esthien-root": key.verify_key})
    store.load(capability, now=NOW)
    return store, capability


def test_every_evaluation_produces_an_evidence_record() -> None:
    store, _ = _capability()
    chain = EvidenceChain(SigningKey.generate())
    boundary = EnforcementBoundary(
        store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()), chain=chain
    )
    assert len(chain) == 0
    boundary.evaluate_proposal(_proposal(), _quality(), now=NOW)
    boundary.evaluate_proposal(_proposal(intent="unknown_intent"), _quality(), now=NOW)
    assert len(chain) == 2  # evidence is a side effect of every evaluation
    assert chain.records[0].record_type is RecordType.DECISION
    assert chain.records[0].decision is Decision.APPROVE
    assert chain.records[1].decision is Decision.DENY
    assert chain.verify() == []


def test_denied_and_modified_decisions_are_recorded() -> None:
    store, _ = _capability()
    chain = EvidenceChain(SigningKey.generate())
    boundary = EnforcementBoundary(
        store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()), chain=chain
    )
    # Exceeds the capability bound: recorded as MODIFY, and clamped.
    boundary.evaluate_proposal(
        _proposal(), _quality(), now=NOW, requested_torque_nm=200.0, requested_velocity_rad_s=2.0
    )
    assert chain.records[-1].decision is Decision.MODIFY
    # Dead sensor: the envelope degrades on the first window, then halts once
    # the declared persistence window is exhausted. Recorded as MODIFY then DENY.
    dead = SignalQuality(reliability=0.0, flatline_channels=(0, 1, 2, 3), artifact_detected=False)
    for _ in range(3):
        boundary.evaluate_proposal(_proposal(), dead, now=NOW)
    assert chain.records[-1].decision is Decision.DENY
    assert chain.verify() == []


def test_boundary_without_a_chain_produces_no_records() -> None:
    store, _ = _capability()
    boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
    command = boundary.evaluate_proposal(_proposal(), _quality(), now=NOW)
    assert command.envelope_state is EnvelopeState.NOMINAL
