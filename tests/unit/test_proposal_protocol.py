"""Public tests for the Argus proposal protocol wire form.

Covers the conformance properties of the protocol specification: round-trip,
determinism, typed rejection, and the normative example layouts.
"""

from __future__ import annotations

import hashlib
import random
import struct

import pytest

from argus.protocol import (
    MAX_PROPOSAL_SIZE,
    ActionClass,
    Parameter,
    ParameterType,
    ProposalProtocolError,
    RejectionCode,
    WireProposal,
    decode_proposal,
    encode_proposal,
    f32,
)


def _hash(seed: str) -> bytes:
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _proposal(
    *,
    action_class: ActionClass = ActionClass.ACTUATE,
    confidence: float = f32(0.973),
    target: str = "robot/joint3/position",
    parameters: tuple[Parameter, ...] = (),
    timestamp: int = 5_000_000,
    flags: int = 0,
) -> WireProposal:
    return WireProposal(
        action_class=action_class,
        confidence=confidence,
        context_hash=_hash("context"),
        timestamp=timestamp,
        model_identity_hash=_hash("arm-controller v3.2.1"),
        model_weight_hash=_hash("weights"),
        previous_attestation=_hash("previous evidence record"),
        host_attestation=bytes(range(64)),
        target=target,
        parameters=parameters,
        flags=flags,
    )


ARM_PARAMETERS = (
    Parameter("angle_rad", ParameterType.FLOAT64, 1.5708),
    Parameter("max_velocity_rad_s", ParameterType.FLOAT64, 0.5),
    Parameter("max_torque_nm", ParameterType.FLOAT64, 12.0),
)


# ------------------------------------------------------------------ layout


def test_fixed_section_layout_matches_the_specification_offsets() -> None:
    buffer = encode_proposal(_proposal(parameters=ARM_PARAMETERS))
    assert struct.unpack_from("<H", buffer, 0)[0] == 0x0001
    assert buffer[2] == 0x01
    assert buffer[3] == 0x00
    assert struct.unpack_from("<H", buffer, 4)[0] == 21
    assert struct.unpack_from("<f", buffer, 10)[0] == f32(0.973)
    assert buffer[14:46] == _hash("context")
    assert struct.unpack_from("<Q", buffer, 46)[0] == 5_000_000
    assert buffer[54:86] == _hash("arm-controller v3.2.1")
    assert buffer[86:118] == _hash("weights")
    assert buffer[118:150] == _hash("previous evidence record")
    assert buffer[150:214] == bytes(range(64))
    assert buffer[214:235] == b"robot/joint3/position"
    assert len(buffer) == 214 + 21 + 70


def test_parameters_length_of_the_normative_example_is_70_bytes() -> None:
    # The specification's example declares 40; the typed-map encoding of the
    # three stated f64 entries is 70 bytes (3 length bytes + 40 name bytes +
    # 3 tag bytes + 24 value bytes). Recorded as an erratum in the technical
    # review; this implementation follows the encoding rule.
    buffer = encode_proposal(_proposal(parameters=ARM_PARAMETERS))
    assert struct.unpack_from("<I", buffer, 6)[0] == 70


# ------------------------------------------------------------------ round-trip


def _random_parameter(rng: random.Random) -> Parameter:
    kind = rng.choice(list(ParameterType))
    if kind is ParameterType.UINT64:
        value = rng.randrange(0, 2**64)
    elif kind is ParameterType.FLOAT64:
        value = struct.unpack("<d", struct.pack("<d", rng.uniform(-1e6, 1e6)))[0]
    elif kind is ParameterType.BOOL:
        value = rng.choice((True, False))
    else:
        value = "".join(rng.choice("abcdef0123456789") for _ in range(rng.randrange(0, 20)))
    name = "".join(rng.choice("abcdefghij_") for _ in range(rng.randrange(1, 20)))
    return Parameter(name, kind, value)


def _random_proposal(rng: random.Random) -> WireProposal:
    count = rng.randrange(0, 4)
    return WireProposal(
        action_class=rng.choice(list(ActionClass)),
        confidence=f32(rng.random()),
        context_hash=rng.randbytes(32),
        timestamp=rng.randrange(0, 2**64),
        model_identity_hash=rng.randbytes(32),
        model_weight_hash=rng.randbytes(32),
        previous_attestation=rng.randbytes(32),
        host_attestation=rng.randbytes(64),
        target="".join(rng.choice("abc/xyz0123") for _ in range(rng.randrange(1, 30))),
        parameters=tuple(_random_parameter(rng) for _ in range(count)),
    )


def test_round_trip_holds_for_ten_thousand_generated_proposals() -> None:
    rng = random.Random(20261002)
    for _ in range(10_000):
        proposal = _random_proposal(rng)
        decoded = decode_proposal(encode_proposal(proposal))
        assert decoded == proposal


def test_encoding_is_deterministic() -> None:
    proposal = _proposal(parameters=ARM_PARAMETERS)
    assert encode_proposal(proposal) == encode_proposal(proposal)


# ------------------------------------------------------------------ typed rejection


def test_short_buffer_is_malformed() -> None:
    buffer = encode_proposal(_proposal())
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(buffer[:200])
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_oversized_parameters_length_is_malformed() -> None:
    buffer = bytearray(encode_proposal(_proposal(parameters=ARM_PARAMETERS)))
    struct.pack_into("<I", buffer, 6, 4_096)
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL
    assert "declared 4096" in exc.value.detail


def test_unknown_action_class_is_typed() -> None:
    buffer = bytearray(encode_proposal(_proposal()))
    buffer[2] = 0x7F
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.UNKNOWN_ACTION_CLASS


def test_version_two_is_unsupported() -> None:
    buffer = bytearray(encode_proposal(_proposal()))
    struct.pack_into("<H", buffer, 0, 0x0002)
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.UNSUPPORTED_VERSION


def test_empty_target_is_a_missing_required_field() -> None:
    buffer = bytearray(encode_proposal(_proposal()))
    struct.pack_into("<H", buffer, 4, 0)
    buffer[:] = buffer[:214]
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.MISSING_REQUIRED_FIELD


def test_unknown_parameter_type_tag_is_malformed() -> None:
    buffer = bytearray(
        encode_proposal(
            _proposal(parameters=(Parameter("x", ParameterType.UINT64, 7),))
        )
    )
    # The single entry is 1 + 1 + 1 + 8 bytes at the end of the buffer.
    buffer[-9] = 0x7F
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_nonzero_reserved_flags_are_rejected() -> None:
    with pytest.raises(ProposalProtocolError) as exc:
        encode_proposal(_proposal(flags=1))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL
    buffer = bytearray(encode_proposal(_proposal()))
    buffer[3] = 0x01
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_out_of_range_confidence_is_malformed() -> None:
    with pytest.raises(ProposalProtocolError) as exc:
        encode_proposal(_proposal(confidence=1.5))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL
    buffer = bytearray(encode_proposal(_proposal()))
    struct.pack_into("<f", buffer, 10, 2.0)
    with pytest.raises(ProposalProtocolError) as exc:
        decode_proposal(bytes(buffer))
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_wrong_hash_size_is_malformed_on_encode() -> None:
    proposal = WireProposal(
        action_class=ActionClass.ACTUATE,
        confidence=f32(0.9),
        context_hash=b"short",
        timestamp=1,
        model_identity_hash=_hash("m"),
        model_weight_hash=_hash("w"),
        previous_attestation=_hash("p"),
        host_attestation=bytes(64),
        target="robot/joint3/position",
    )
    with pytest.raises(ProposalProtocolError) as exc:
        encode_proposal(proposal)
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_oversized_proposal_is_too_large() -> None:
    proposal = _proposal(
        parameters=(
            Parameter("big", ParameterType.STRING, "x" * 70_000),
        )
    )
    with pytest.raises(ProposalProtocolError) as exc:
        encode_proposal(proposal)
    assert exc.value.code is RejectionCode.PROPOSAL_TOO_LARGE


def test_parameter_value_type_mismatch_is_malformed() -> None:
    with pytest.raises(ProposalProtocolError) as exc:
        Parameter("angle", ParameterType.FLOAT64, 3)
    assert exc.value.code is RejectionCode.MALFORMED_PROPOSAL


def test_fuzz_never_raises_anything_but_a_typed_rejection() -> None:
    rng = random.Random(20261002)
    valid = encode_proposal(_proposal(parameters=ARM_PARAMETERS))
    for _ in range(100_000):
        length = rng.choice(
            (rng.randrange(0, 60), rng.randrange(60, 214), rng.randrange(214, len(valid) + 40))
        )
        buffer = bytearray(rng.randbytes(length))
        if rng.random() < 0.5 and length >= 220:
            buffer[:220] = valid[:220]
        try:
            decode_proposal(bytes(buffer))
        except ProposalProtocolError as error:
            assert isinstance(error.code, RejectionCode)
        except Exception as error:  # pragma: no cover - the property under test
            raise AssertionError(f"unexpected exception {error!r}") from error


def test_rejection_codes_are_closed_and_stable() -> None:
    assert [code.value for code in RejectionCode] == list(range(0x0001, 0x000B))
    assert RejectionCode.MALFORMED_PROPOSAL.value == 0x0001
    assert RejectionCode.POLICY_DENIED.value == 0x000A


def test_max_proposal_size_matches_the_specification() -> None:
    assert MAX_PROPOSAL_SIZE == 65_536
