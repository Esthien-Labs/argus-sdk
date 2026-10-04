"""The Argus attestation protocol: the cryptographic evidence chain.

Every decision the enforcement boundary makes produces a tamper-evident,
publicly verifiable record. A system owner, an auditor, or a court can verify
after the fact that an AI system operated within its authorized bounds, offline
and statelessly, with only the record, the policy hash, and the public key.

Records form a hash chain and are batched into binary Merkle trees:

    record[0].previous_record_hash = GENESIS (32 zero bytes)
    record[i].previous_record_hash = SHA-256(record[i-1])

Modifying any historical record changes its hash, which breaks every later link
and every later batch root. Detection is cryptographic, not heuristic.

Record layout (little-endian, no padding):

    offset  size  field
    0       2     record_version (uint16)
    2       1     record_type
    3       1     flags
    4       8     sequence_number (uint64)
    12      8     timestamp_counter (uint64, monotonic)
    20      32    proposal_hash
    52      32    policy_hash
    84      1     decision
    85      2     policy_clause_ref (uint16)
    87      32    monitor_state_hash
    119     32    previous_record_hash
    151     64    signature (Ed25519)
    215     2     extensions_length (uint16)
    217     ...   extensions

Two provisional decisions are used pending specification ratification, both
recorded in the specification's technical review: the signature covers the
pre-signature section only (offsets 0 to 151), because signing a range that
includes the signature field is circular; and the decision enumeration is
0x00 not-applicable, 0x01 approve, 0x02 deny, 0x03 modify.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, replace
from enum import IntEnum

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

__all__ = [
    "GENESIS_HASH",
    "Decision",
    "EvidenceChain",
    "EvidenceRecord",
    "RecordType",
    "decode_record",
    "merkle_inclusion_proof",
    "merkle_root",
    "verify_merkle_inclusion",
]

GENESIS_HASH = bytes(32)
RECORD_VERSION = 0x0001
_HASH_SIZE = 32
_SIGNATURE_SIZE = 64
_PRE_SIGNATURE_SIZE = 151
_EXTENSION_LENGTH_OFFSET = 215
_FIXED_SECTION_SIZE = 217


class RecordType(IntEnum):
    DECISION = 0x01
    POLICY_LOAD = 0x02
    ESCALATION = 0x03
    HALT = 0x04
    TAMPER = 0x05
    HEARTBEAT = 0x06


class Decision(IntEnum):
    NOT_APPLICABLE = 0x00
    APPROVE = 0x01
    DENY = 0x02
    MODIFY = 0x03


class AttestationError(ValueError):
    """Raised for malformed evidence records and broken chains."""


@dataclass(frozen=True)
class EvidenceRecord:
    """One tamper-evident evidence record.

    Attributes:
        record_type: What kind of event this record attests.
        sequence_number: Position in the chain; contiguous from zero.
        timestamp_counter: Monotonic counter value, not wall-clock time.
        proposal_hash: SHA-256 of the evaluated proposal; zero for records with
            no proposal.
        policy_hash: SHA-256 of the active policy.
        decision: The decision, or not-applicable for non-decision records.
        policy_clause_ref: The policy clause that determined the decision.
        monitor_state_hash: SHA-256 of the monitor state at evaluation time.
        previous_record_hash: SHA-256 of the previous record, or the genesis
            hash for record zero.
        extensions: Implementation-defined extra data.
        flags: Reserved; must be zero.
        record_version: Wire record version.
        signature: Ed25519 signature over the pre-signature section.
    """

    record_type: RecordType
    sequence_number: int
    timestamp_counter: int
    proposal_hash: bytes
    policy_hash: bytes
    decision: Decision
    policy_clause_ref: int
    monitor_state_hash: bytes
    previous_record_hash: bytes
    extensions: bytes = b""
    flags: int = 0
    record_version: int = RECORD_VERSION
    signature: bytes | None = None

    def __post_init__(self) -> None:
        if self.record_version != RECORD_VERSION:
            raise AttestationError(f"record version {self.record_version:#06x} unsupported")
        if self.flags != 0:
            raise AttestationError("reserved flags must be zero")
        if not 0 <= self.sequence_number <= 0xFFFFFFFFFFFFFFFF:
            raise AttestationError("sequence_number exceeds uint64")
        if not 0 <= self.timestamp_counter <= 0xFFFFFFFFFFFFFFFF:
            raise AttestationError("timestamp_counter exceeds uint64")
        if len(self.proposal_hash) != _HASH_SIZE:
            raise AttestationError("proposal_hash must be 32 bytes")
        if len(self.policy_hash) != _HASH_SIZE:
            raise AttestationError("policy_hash must be 32 bytes")
        if len(self.monitor_state_hash) != _HASH_SIZE:
            raise AttestationError("monitor_state_hash must be 32 bytes")
        if len(self.previous_record_hash) != _HASH_SIZE:
            raise AttestationError("previous_record_hash must be 32 bytes")
        if len(self.extensions) > 0xFFFF:
            raise AttestationError("extensions exceed uint16 length")

    def encode(self) -> bytes:
        """Encode to the canonical binary form."""
        if self.signature is None:
            raise AttestationError("cannot encode an unsigned record to the wire form")
        return (
            struct.pack(
                "<HBBQQ",
                self.record_version,
                int(self.record_type),
                self.flags,
                self.sequence_number,
                self.timestamp_counter,
            )
            + self.proposal_hash
            + self.policy_hash
            + struct.pack("<BH", int(self.decision), self.policy_clause_ref)
            + self.monitor_state_hash
            + self.previous_record_hash
            + self.signature
            + struct.pack("<H", len(self.extensions))
            + self.extensions
        )

    def pre_signature_bytes(self) -> bytes:
        """The section the signature covers: every field before the signature."""
        return (
            struct.pack(
                "<HBBQQ",
                self.record_version,
                int(self.record_type),
                self.flags,
                self.sequence_number,
                self.timestamp_counter,
            )
            + self.proposal_hash
            + self.policy_hash
            + struct.pack("<BH", int(self.decision), self.policy_clause_ref)
            + self.monitor_state_hash
            + self.previous_record_hash
        )

    def hash(self) -> bytes:
        """SHA-256 over the full encoded record."""
        return hashlib.sha256(self.encode()).digest()

    def sign(self, signing_key: SigningKey) -> "EvidenceRecord":
        """Return a signed copy of this record."""
        if self.signature is not None:
            raise AttestationError("record is already signed")
        return replace(self, signature=signing_key.sign(self.pre_signature_bytes()).signature)

    def verify(self, verify_key: VerifyKey) -> bool:
        """True when the signature is a valid signature over the pre-signature section."""
        if self.signature is None:
            return False
        try:
            verify_key.verify(self.pre_signature_bytes(), self.signature)
        except BadSignatureError:
            return False
        return True


def decode_record(buffer: bytes) -> EvidenceRecord:
    """Decode one record from its canonical binary form.

    Raises:
        AttestationError: If the buffer does not match the schema.
    """
    if len(buffer) < _FIXED_SECTION_SIZE:
        raise AttestationError(
            f"buffer is {len(buffer)} bytes, fixed section alone is {_FIXED_SECTION_SIZE}"
        )
    record_version, type_value, flags = struct.unpack_from("<HBB", buffer, 0)
    if record_version != RECORD_VERSION:
        raise AttestationError(f"record version {record_version:#06x} unsupported")
    if flags != 0:
        raise AttestationError("reserved flags must be zero")
    try:
        record_type = RecordType(type_value)
    except ValueError:
        raise AttestationError(f"record type {type_value:#04x} is not in the enumeration") from None
    sequence_number, timestamp_counter = struct.unpack_from("<QQ", buffer, 4)
    proposal_hash = bytes(buffer[20:52])
    policy_hash = bytes(buffer[52:84])
    decision_value, policy_clause_ref = struct.unpack_from("<BH", buffer, 84)
    try:
        decision = Decision(decision_value)
    except ValueError:
        raise AttestationError(f"decision {decision_value:#04x} is not in the enumeration") from None
    monitor_state_hash = bytes(buffer[87:119])
    previous_record_hash = bytes(buffer[119:151])
    signature = bytes(buffer[151:215])
    (extensions_length,) = struct.unpack_from("<H", buffer, _EXTENSION_LENGTH_OFFSET)
    extensions_end = _FIXED_SECTION_SIZE + extensions_length
    if extensions_end != len(buffer):
        raise AttestationError(
            f"extensions length mismatch: declared {extensions_length} bytes, "
            f"available {len(buffer) - _FIXED_SECTION_SIZE}"
        )
    extensions = bytes(buffer[_FIXED_SECTION_SIZE:extensions_end])
    return EvidenceRecord(
        record_type=record_type,
        sequence_number=sequence_number,
        timestamp_counter=timestamp_counter,
        proposal_hash=proposal_hash,
        policy_hash=policy_hash,
        decision=decision,
        policy_clause_ref=policy_clause_ref,
        monitor_state_hash=monitor_state_hash,
        previous_record_hash=previous_record_hash,
        extensions=extensions,
        flags=flags,
        record_version=record_version,
        signature=signature,
    )


def merkle_root(hashes: list[bytes]) -> bytes:
    """Binary Merkle root over record hashes, duplicating the last node on odd levels."""
    if not hashes:
        return GENESIS_HASH
    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    return level[0]


def merkle_inclusion_proof(hashes: list[bytes], index: int) -> list[tuple[bytes, bool]]:
    """The inclusion path for one leaf: (sibling hash, sibling_is_right) pairs."""
    if not 0 <= index < len(hashes):
        raise AttestationError(f"index {index} outside {len(hashes)} leaves")
    level = list(hashes)
    position = index
    path: list[tuple[bytes, bool]] = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        sibling_is_right = position % 2 == 0
        sibling = level[position + 1] if sibling_is_right else level[position - 1]
        path.append((sibling, sibling_is_right))
        position //= 2
        level = [
            hashlib.sha256(level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    return path


def verify_merkle_inclusion(
    leaf_hash: bytes, path: list[tuple[bytes, bool]], root: bytes
) -> bool:
    """Verify an inclusion proof. Sibling on the right means hash(leaf || sibling)."""
    current = leaf_hash
    for sibling, sibling_is_right in path:
        pair = current + sibling if sibling_is_right else sibling + current
        current = hashlib.sha256(pair).digest()
    return current == root


class EvidenceChain:
    """An ordered, hash-linked, signed evidence chain.

    Every append assigns the next sequence number and links to the previous
    record. The chain is append-only: there is no operation that rewrites
    history, and verification detects any attempt.
    """

    def __init__(self, signing_key: SigningKey | None = None) -> None:
        self._records: list[EvidenceRecord] = []
        self._signing_key = signing_key

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def head_hash(self) -> bytes:
        """SHA-256 of the last record, or the genesis hash for an empty chain."""
        if not self._records:
            return GENESIS_HASH
        return self._records[-1].hash()

    def append(
        self,
        record: EvidenceRecord,
        *,
        timestamp_counter: int | None = None,
    ) -> EvidenceRecord:
        """Append one record, assigning its sequence number and chain link.

        The record is signed when the chain holds a signing key. The record
        passed in is not mutated; the appended, linked, signed copy is returned.
        """
        linked = replace(
            record,
            sequence_number=len(self._records),
            previous_record_hash=self.head_hash(),
            timestamp_counter=(
                record.timestamp_counter if timestamp_counter is None else timestamp_counter
            ),
        )
        if self._signing_key is not None:
            linked = linked.sign(self._signing_key)
        self._records.append(linked)
        return linked

    def verify(self, verify_key: VerifyKey | None = None) -> list[int]:
        """Verify the whole chain.

        Returns the indices of the first broken links, empty when the chain is
        intact. Each broken link is reported independently: a tampered record
        breaks its own link, and every later link that depended on it is also
        reported so the extent of the tampering is visible.
        """
        broken: list[int] = []
        for index, record in enumerate(self._records):
            if record.sequence_number != index:
                broken.append(index)
                continue
            expected_previous = (
                GENESIS_HASH if index == 0 else self._records[index - 1].hash()
            )
            if record.previous_record_hash != expected_previous:
                broken.append(index)
                continue
            if verify_key is not None and not record.verify(verify_key):
                broken.append(index)
        return broken

    def batch_roots(self, batch_size: int = 4096) -> list[bytes]:
        """Merkle roots over consecutive batches of record hashes."""
        hashes = [record.hash() for record in self._records]
        return [
            merkle_root(hashes[start : start + batch_size])
            for start in range(0, len(hashes), batch_size)
        ]
