"""The Argus proposal protocol: the wire form of an AI action proposal.

Every output from an AI system that intends to affect the physical world enters
the enforcement boundary as a proposal in this encoding. A model proposes. The
boundary disposes. There is no bypass and no free-text interface.

The canonical binary encoding is fixed-layout, little-endian, no padding:

    offset  size  field
    0       2     protocol_version (uint16)
    2       1     action_class
    3       1     flags (reserved, zero)
    4       2     target_length (uint16)
    6       4     parameters_length (uint32)
    10      4     confidence (IEEE-754 float32)
    14      32    context_hash
    46      8     timestamp (uint64, monotonic, not wall clock)
    54      32    model_identity_hash
    86      32    model_weight_hash
    118     32    previous_attestation
    150     64    host_attestation (Ed25519 signature)
    214     ...   target (target_length bytes UTF-8)
    ...     ...   parameters (parameters_length bytes, typed map)

Parameters are a typed map; each entry is name_length (uint8), name (UTF-8),
type_tag (uint8), value. Values: u64 and f64 are 8 bytes little-endian, bool is
one byte, string is a uint16 length prefix plus UTF-8 bytes.

Two provisional assignments are used pending specification ratification, both
recorded in the specification's technical review: action-class codes follow the
class-table order (ACTUATE is 0x01, fixed by the normative example), and the
type-tag set is u64 0x01, f64 0x02, bool 0x03, string 0x04.

Confidence is float32 on the wire; round-trip equality holds for
float32-representable values.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Union

__all__ = [
    "ActionClass",
    "Parameter",
    "ParameterType",
    "ProposalProtocolError",
    "RejectionCode",
    "WireProposal",
    "decode_proposal",
    "encode_proposal",
    "f32",
    "MAX_PROPOSAL_SIZE",
    "PROTOCOL_VERSION",
]

PROTOCOL_VERSION = 0x0001
MAX_PROPOSAL_SIZE = 65_536

_FIXED_SECTION_SIZE = 214
_HASH_SIZE = 32
_ATTESTATION_SIZE = 64


class ActionClass(IntEnum):
    """The class of action a proposal proposes."""

    ACTUATE = 0x01
    COMMUNICATE = 0x02
    MODIFY_STATE = 0x03
    QUERY = 0x04
    DELEGATE = 0x05
    HALT = 0x06


class RejectionCode(IntEnum):
    """Typed rejection reasons. Closed enumeration; codes are never reused."""

    MALFORMED_PROPOSAL = 0x0001
    UNSUPPORTED_VERSION = 0x0002
    INVALID_PROVENANCE = 0x0003
    EXPIRED_PROPOSAL = 0x0004
    PROPOSAL_TOO_LARGE = 0x0005
    UNKNOWN_ACTION_CLASS = 0x0006
    UNKNOWN_TARGET = 0x0007
    MISSING_REQUIRED_FIELD = 0x0008
    PARAMETER_OUT_OF_RANGE = 0x0009
    POLICY_DENIED = 0x000A


class ParameterType(IntEnum):
    """Parameter value types in the typed map."""

    UINT64 = 0x01
    FLOAT64 = 0x02
    BOOL = 0x03
    STRING = 0x04


ParameterValue = Union[int, float, bool, str]


class ProposalProtocolError(ValueError):
    """A typed rejection. Carries the rejection code and a detail string."""

    def __init__(self, code: RejectionCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.name}: {detail}" if detail else code.name)


@dataclass(frozen=True)
class Parameter:
    """One typed-map entry."""

    name: str
    type_tag: ParameterType
    value: ParameterValue

    def __post_init__(self) -> None:
        if not self.name or len(self.name.encode("utf-8")) > 255:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL,
                f"parameter name length must be 1..255, got {len(self.name.encode('utf-8'))}",
            )
        expected = {
            ParameterType.UINT64: int,
            ParameterType.FLOAT64: float,
            ParameterType.BOOL: bool,
            ParameterType.STRING: str,
        }
        if type(self.value) is not expected[self.type_tag]:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL,
                f"parameter {self.name!r} value does not match type {self.type_tag.name}",
            )
        if self.type_tag is ParameterType.UINT64 and not 0 <= self.value <= 0xFFFFFFFFFFFFFFFF:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL, f"parameter {self.name!r} exceeds uint64"
            )


@dataclass(frozen=True)
class WireProposal:
    """A proposal in its canonical wire form.

    Attributes:
        action_class: The class of action proposed.
        confidence: Model-reported confidence in [0, 1]. Not trusted by the
            boundary; an input to confidence-coupled evaluation.
        context_hash: SHA-256 of the inference context.
        timestamp: Monotonic counter value from the inference host.
        model_identity_hash: SHA-256 of the model identifier string.
        model_weight_hash: SHA-256 of the model weights, or the provider
            attestation hash for hosted models.
        previous_attestation: Hash of the previous evidence record in the chain.
        host_attestation: Ed25519 signature over the fixed section by the
            inference host's attestation key.
        target: The actuator, API, or output channel the action targets.
        parameters: Typed action parameters.
        flags: Reserved; must be zero.
        protocol_version: Wire protocol version.
    """

    action_class: ActionClass
    confidence: float
    context_hash: bytes
    timestamp: int
    model_identity_hash: bytes
    model_weight_hash: bytes
    previous_attestation: bytes
    host_attestation: bytes
    target: str
    parameters: tuple[Parameter, ...] = ()
    flags: int = 0
    protocol_version: int = PROTOCOL_VERSION


def f32(value: float) -> float:
    """Round a float to its IEEE-754 float32 representation."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def encode_proposal(proposal: WireProposal) -> bytes:
    """Encode a proposal into its canonical binary form.

    Raises:
        ProposalProtocolError: With a typed rejection code when the proposal
            violates the schema.
    """
    if proposal.protocol_version != PROTOCOL_VERSION:
        raise ProposalProtocolError(
            RejectionCode.UNSUPPORTED_VERSION,
            f"version {proposal.protocol_version:#06x} is not {PROTOCOL_VERSION:#06x}",
        )
    if proposal.flags != 0:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, "reserved flags must be zero"
        )
    if not 0.0 <= proposal.confidence <= 1.0:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, f"confidence {proposal.confidence} outside [0, 1]"
        )
    if not 0 <= proposal.timestamp <= 0xFFFFFFFFFFFFFFFF:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, "timestamp exceeds uint64"
        )
    for name, size in (
        ("context_hash", _HASH_SIZE),
        ("model_identity_hash", _HASH_SIZE),
        ("model_weight_hash", _HASH_SIZE),
        ("previous_attestation", _HASH_SIZE),
        ("host_attestation", _ATTESTATION_SIZE),
    ):
        value = getattr(proposal, name)
        if len(value) != size:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL,
                f"{name} must be {size} bytes, got {len(value)}",
            )
    if not proposal.target:
        raise ProposalProtocolError(
            RejectionCode.MISSING_REQUIRED_FIELD, "target must not be empty"
        )
    target_bytes = proposal.target.encode("utf-8")
    if len(target_bytes) > 0xFFFF:
        raise ProposalProtocolError(
            RejectionCode.PROPOSAL_TOO_LARGE, "target exceeds uint16 length"
        )

    parameters = bytearray()
    for parameter in proposal.parameters:
        name_bytes = parameter.name.encode("utf-8")
        parameters += struct.pack("<B", len(name_bytes)) + name_bytes
        parameters += struct.pack("<B", int(parameter.type_tag))
        if parameter.type_tag is ParameterType.UINT64:
            parameters += struct.pack("<Q", parameter.value)
        elif parameter.type_tag is ParameterType.FLOAT64:
            parameters += struct.pack("<d", parameter.value)
        elif parameter.type_tag is ParameterType.BOOL:
            parameters += b"\x01" if parameter.value else b"\x00"
        else:
            value_bytes = parameter.value.encode("utf-8")
            if len(value_bytes) > 0xFFFF:
                raise ProposalProtocolError(
                    RejectionCode.PROPOSAL_TOO_LARGE,
                    f"parameter {parameter.name!r} value exceeds uint16 length",
                )
            parameters += struct.pack("<H", len(value_bytes)) + value_bytes

    buffer = bytearray()
    buffer += struct.pack(
        "<HBBHIf",
        PROTOCOL_VERSION,
        int(proposal.action_class),
        proposal.flags,
        len(target_bytes),
        len(parameters),
        proposal.confidence,
    )
    buffer += proposal.context_hash
    buffer += struct.pack("<Q", proposal.timestamp)
    buffer += proposal.model_identity_hash
    buffer += proposal.model_weight_hash
    buffer += proposal.previous_attestation
    buffer += proposal.host_attestation
    buffer += target_bytes
    buffer += parameters

    if len(buffer) > MAX_PROPOSAL_SIZE:
        raise ProposalProtocolError(
            RejectionCode.PROPOSAL_TOO_LARGE,
            f"proposal is {len(buffer)} bytes, limit is {MAX_PROPOSAL_SIZE}",
        )
    return bytes(buffer)


def decode_proposal(buffer: bytes) -> WireProposal:
    """Decode a proposal from its canonical binary form.

    Zero-copy for the fixed section is a property of the reference
    implementation; this software form allocates freely and enforces the same
    schema.

    Raises:
        ProposalProtocolError: With a typed rejection code. Never another
            exception type, and never for a reason outside the enumeration.
    """
    if len(buffer) < _FIXED_SECTION_SIZE:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL,
            f"buffer is {len(buffer)} bytes, fixed section alone is {_FIXED_SECTION_SIZE}",
        )

    protocol_version = struct.unpack_from("<H", buffer, 0)[0]
    if protocol_version != PROTOCOL_VERSION:
        raise ProposalProtocolError(
            RejectionCode.UNSUPPORTED_VERSION,
            f"version {protocol_version:#06x} is not {PROTOCOL_VERSION:#06x}",
        )
    if len(buffer) > MAX_PROPOSAL_SIZE:
        raise ProposalProtocolError(
            RejectionCode.PROPOSAL_TOO_LARGE,
            f"proposal is {len(buffer)} bytes, limit is {MAX_PROPOSAL_SIZE}",
        )

    action_class_value = buffer[2]
    try:
        action_class = ActionClass(action_class_value)
    except ValueError:
        raise ProposalProtocolError(
            RejectionCode.UNKNOWN_ACTION_CLASS,
            f"action class {action_class_value:#04x} is not in the enumeration",
        ) from None

    flags = buffer[3]
    if flags != 0:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, "reserved flags must be zero"
        )

    target_length, parameters_length = struct.unpack_from("<HI", buffer, 4)
    confidence = struct.unpack_from("<f", buffer, 10)[0]
    if not 0.0 <= confidence <= 1.0:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, f"confidence {confidence} outside [0, 1]"
        )

    context_hash = bytes(buffer[14:46])
    timestamp = struct.unpack_from("<Q", buffer, 46)[0]
    model_identity_hash = bytes(buffer[54:86])
    model_weight_hash = bytes(buffer[86:118])
    previous_attestation = bytes(buffer[118:150])
    host_attestation = bytes(buffer[150:214])

    target_start = _FIXED_SECTION_SIZE
    target_end = target_start + target_length
    if target_end > len(buffer):
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL,
            f"target section truncated: declared {target_length} bytes, "
            f"available {len(buffer) - target_start}",
        )
    if target_length == 0:
        raise ProposalProtocolError(
            RejectionCode.MISSING_REQUIRED_FIELD, "target must not be empty"
        )
    try:
        target = buffer[target_start:target_end].decode("utf-8")
    except UnicodeDecodeError:
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL, "target is not valid UTF-8"
        ) from None

    parameters_start = target_end
    parameters_end = parameters_start + parameters_length
    if parameters_end != len(buffer):
        raise ProposalProtocolError(
            RejectionCode.MALFORMED_PROPOSAL,
            f"parameters section length mismatch: declared {parameters_length} bytes, "
            f"available {len(buffer) - parameters_start}",
        )

    parameters = _decode_parameters(buffer, parameters_start, parameters_end)

    return WireProposal(
        action_class=action_class,
        confidence=confidence,
        context_hash=context_hash,
        timestamp=timestamp,
        model_identity_hash=model_identity_hash,
        model_weight_hash=model_weight_hash,
        previous_attestation=previous_attestation,
        host_attestation=host_attestation,
        target=target,
        parameters=parameters,
        flags=flags,
        protocol_version=protocol_version,
    )


def _decode_parameters(
    buffer: bytes, start: int, end: int
) -> tuple[Parameter, ...]:
    """Decode the typed-map section. Every inconsistency is MALFORMED_PROPOSAL."""
    parameters: list[Parameter] = []
    offset = start
    while offset < end:
        if offset + 1 > end:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL, "parameter name length truncated"
            )
        name_length = buffer[offset]
        offset += 1
        if offset + name_length + 1 > end:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL,
                f"parameter name truncated: declared {name_length} bytes",
            )
        try:
            name = buffer[offset : offset + name_length].decode("utf-8")
        except UnicodeDecodeError:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL, "parameter name is not valid UTF-8"
            ) from None
        offset += name_length
        type_value = buffer[offset]
        offset += 1
        try:
            type_tag = ParameterType(type_value)
        except ValueError:
            raise ProposalProtocolError(
                RejectionCode.MALFORMED_PROPOSAL,
                f"parameter {name!r} has unknown type tag {type_value:#04x}",
            ) from None

        if type_tag is ParameterType.UINT64:
            if offset + 8 > end:
                raise _truncated(name)
            value: ParameterValue = struct.unpack_from("<Q", buffer, offset)[0]
            offset += 8
        elif type_tag is ParameterType.FLOAT64:
            if offset + 8 > end:
                raise _truncated(name)
            value = struct.unpack_from("<d", buffer, offset)[0]
            offset += 8
        elif type_tag is ParameterType.BOOL:
            if offset + 1 > end:
                raise _truncated(name)
            raw = buffer[offset]
            if raw not in (0, 1):
                raise ProposalProtocolError(
                    RejectionCode.MALFORMED_PROPOSAL,
                    f"parameter {name!r} bool value must be 0 or 1, got {raw}",
                )
            value = raw == 1
            offset += 1
        else:
            if offset + 2 > end:
                raise _truncated(name)
            value_length = struct.unpack_from("<H", buffer, offset)[0]
            offset += 2
            if offset + value_length > end:
                raise ProposalProtocolError(
                    RejectionCode.MALFORMED_PROPOSAL,
                    f"parameter {name!r} value truncated: declared {value_length} bytes",
                )
            try:
                value = buffer[offset : offset + value_length].decode("utf-8")
            except UnicodeDecodeError:
                raise ProposalProtocolError(
                    RejectionCode.MALFORMED_PROPOSAL,
                    f"parameter {name!r} value is not valid UTF-8",
                ) from None
            offset += value_length
        parameters.append(Parameter(name=name, type_tag=type_tag, value=value))

    return tuple(parameters)


def _truncated(name: str) -> ProposalProtocolError:
    return ProposalProtocolError(
        RejectionCode.MALFORMED_PROPOSAL, f"parameter {name!r} value truncated"
    )
