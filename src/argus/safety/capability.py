"""Software Authority Capabilities: the L0 authority layer of the enforcement boundary.

An Authority Capability is a signed, immutable token that bounds what an AI system
may do. The software form specified in EST-SPEC-009 section 8 ships in the SDK
before any silicon exists; the hardware form ships with EARG-001 and successors.

A capability is not a policy document. It is a token: it can be checked locally,
refused locally, revoked locally without the network, and delegated to another
device as a strictly narrower derived token. A compromised model cannot forge
one, because it does not hold the signing key. A compromised server cannot
extend one, because the boundary clamps every command to the loaded bounds.

The signature scheme is Ed25519 through PyNaCl, a reviewed standard primitive.
This module does not implement key custody, release signing, or hardware
binding; those remain separately gated per EST-SPEC-009.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Mapping

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from .envelope import ActuatorCommand, EnvelopeState, ProposedAction

__all__ = [
    "ActuatorBounds",
    "AuthorityCapability",
    "CapabilityError",
    "CapabilityStore",
    "CapabilityValidity",
    "EnforcementBoundary",
    "delegate_capability",
]


class CapabilityError(ValueError):
    """Raised for malformed capabilities and invalid delegations."""


@dataclass(frozen=True)
class ActuatorBounds:
    """Authority bounds for one named actuator.

    Attributes:
        actuator: Actuator name the bounds apply to.
        max_torque_nm: Maximum commanded torque magnitude.
        max_velocity_rad_s: Maximum commanded velocity magnitude.
        max_duration_s: Maximum continuous command duration, or None for
            unbounded duration.
    """

    actuator: str
    max_torque_nm: float
    max_velocity_rad_s: float
    max_duration_s: float | None = None

    def __post_init__(self) -> None:
        if not self.actuator:
            raise CapabilityError("actuator name must not be empty")
        if self.max_torque_nm < 0 or self.max_velocity_rad_s < 0:
            raise CapabilityError("actuator bounds must be non-negative")
        if self.max_duration_s is not None and self.max_duration_s < 0:
            raise CapabilityError("max_duration_s must be non-negative")

    def is_at_least_as_tight_as(self, other: "ActuatorBounds") -> bool:
        """True when these bounds are within the other capability's bounds."""
        if self.max_torque_nm > other.max_torque_nm:
            return False
        if self.max_velocity_rad_s > other.max_velocity_rad_s:
            return False
        if other.max_duration_s is None:
            return self.max_duration_s is None or self.max_duration_s >= 0
        return self.max_duration_s is not None and self.max_duration_s <= other.max_duration_s


@dataclass(frozen=True)
class CapabilityValidity:
    """Temporal validity of a capability.

    Attributes:
        issued_at: Unix time the capability becomes valid.
        expires_at: Unix time the capability expires, or None for no expiry.
        offline_grace_s: Seconds past expiry the capability stays valid while
            the device is offline.
    """

    issued_at: float
    expires_at: float | None = None
    offline_grace_s: float = 0.0

    def __post_init__(self) -> None:
        if self.offline_grace_s < 0:
            raise CapabilityError("offline_grace_s must be non-negative")
        if self.expires_at is not None and self.expires_at < self.issued_at:
            raise CapabilityError("expires_at must not precede issued_at")

    def status_at(self, now: float) -> str:
        """Return ``valid``, ``not_yet_valid``, or ``expired`` at a given time."""
        if now < self.issued_at:
            return "not_yet_valid"
        if self.expires_at is None:
            return "valid"
        return "valid" if now <= self.expires_at + self.offline_grace_s else "expired"


@dataclass(frozen=True)
class AuthorityCapability:
    """A signed, immutable authority token (software form).

    Attributes:
        cap_id: Unique capability identifier.
        issuer: Key identifier of the issuing entity.
        audience: Device identity or deployment scope the token is bound to.
        intent_classes: Intent classes the holder may propose.
        bounds: Per-actuator bounds the holder may command.
        profile_id: Authority profile the capability was issued against.
        model_id: Model identity the capability is bound to, or None for any.
        model_version: Model version binding, or None for any.
        validity: Temporal validity.
        parent_cap_id: Parent capability for a delegated token, or None.
        signature: Ed25519 signature over the canonical serialization, or None
            before signing.
    """

    cap_id: str
    issuer: str
    audience: str
    intent_classes: tuple[str, ...]
    bounds: tuple[ActuatorBounds, ...]
    profile_id: str
    validity: CapabilityValidity
    model_id: str | None = None
    model_version: str | None = None
    parent_cap_id: str | None = None
    signature: bytes | None = None

    def __post_init__(self) -> None:
        if not self.cap_id or not self.issuer or not self.audience:
            raise CapabilityError("cap_id, issuer, and audience must not be empty")
        if not self.intent_classes:
            raise CapabilityError("intent_classes must not be empty")
        if not self.bounds:
            raise CapabilityError("bounds must not be empty")
        if len(set(self.intent_classes)) != len(self.intent_classes):
            raise CapabilityError("intent_classes must be unique")
        if len({b.actuator for b in self.bounds}) != len(self.bounds):
            raise CapabilityError("one bounds entry per actuator")

    def unsigned_mapping(self) -> dict:
        """The capability without its signature, in a canonical mapping."""
        return {
            "cap_id": self.cap_id,
            "issuer": self.issuer,
            "audience": self.audience,
            "intent_classes": list(self.intent_classes),
            "bounds": [
                {
                    "actuator": b.actuator,
                    "max_torque_nm": b.max_torque_nm,
                    "max_velocity_rad_s": b.max_velocity_rad_s,
                    "max_duration_s": b.max_duration_s,
                }
                for b in self.bounds
            ],
            "profile_id": self.profile_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "validity": {
                "issued_at": self.validity.issued_at,
                "expires_at": self.validity.expires_at,
                "offline_grace_s": self.validity.offline_grace_s,
            },
            "parent_cap_id": self.parent_cap_id,
        }

    def canonical_bytes(self) -> bytes:
        """Canonical serialization the signature covers."""
        return json.dumps(
            self.unsigned_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def sign(self, signing_key: SigningKey) -> "AuthorityCapability":
        """Return a signed copy of this capability."""
        if self.signature is not None:
            raise CapabilityError("capability is already signed")
        return replace(self, signature=signing_key.sign(self.canonical_bytes()).signature)

    def verify(self, verify_key: VerifyKey) -> bool:
        """True when the signature is a valid signature over this token."""
        if self.signature is None:
            return False
        try:
            verify_key.verify(self.canonical_bytes(), self.signature)
        except BadSignatureError:
            return False
        return True

    def authorizes_intent(self, intent: str) -> bool:
        return intent in self.intent_classes

    def authorizes_model(self, model_id: str, model_version: str | None) -> bool:
        if self.model_id is not None and self.model_id != model_id:
            return False
        if self.model_version is not None and model_version is not None:
            return self.model_version == model_version
        return True

    def torque_bound_nm(self) -> float:
        return min(b.max_torque_nm for b in self.bounds)

    def velocity_bound_rad_s(self) -> float:
        return min(b.max_velocity_rad_s for b in self.bounds)

    def is_within(self, parent: "AuthorityCapability") -> bool:
        """True when this capability is no wider than its parent."""
        if not set(self.intent_classes) <= set(parent.intent_classes):
            return False
        parent_bounds = {b.actuator: b for b in parent.bounds}
        for b in self.bounds:
            if b.actuator not in parent_bounds:
                return False
            if not b.is_at_least_as_tight_as(parent_bounds[b.actuator]):
                return False
        if parent.validity.expires_at is not None:
            if self.validity.expires_at is None:
                return False
            if self.validity.expires_at > parent.validity.expires_at:
                return False
        return True


def delegate_capability(
    parent: AuthorityCapability,
    *,
    signing_key: SigningKey,
    cap_id: str,
    issuer: str,
    audience: str,
    intent_classes: tuple[str, ...],
    bounds: tuple[ActuatorBounds, ...],
    validity: CapabilityValidity,
) -> AuthorityCapability:
    """Issue a derived capability that is strictly narrower than its parent.

    Raises:
        CapabilityError: If the derived capability would exceed the parent in
            intent classes, actuator bounds, or validity.
    """
    if parent.signature is None:
        raise CapabilityError("parent capability must be signed")
    derived = AuthorityCapability(
        cap_id=cap_id,
        issuer=issuer,
        audience=audience,
        intent_classes=tuple(intent_classes),
        bounds=tuple(bounds),
        profile_id=parent.profile_id,
        model_id=parent.model_id,
        model_version=parent.model_version,
        validity=validity,
        parent_cap_id=parent.cap_id,
    )
    if not derived.is_within(parent):
        raise CapabilityError("derived capability exceeds its parent")
    return derived.sign(signing_key)


class CapabilityStore:
    """Loads, revokes, and enforces Authority Capabilities for one audience.

    Args:
        audience: The device or deployment identity this store enforces for.
        trusted_keys: Issuer key identifiers mapped to their Ed25519 verify keys.
    """

    # Refusal-reason specificity ordering. When no capability authorizes a
    # proposal, the most specific failure is reported first.
    _REASON_ORDER = (
        "parent_revoked",
        "revoked",
        "parent_invalid",
        "delegation_exceeds_parent",
        "parent_not_available",
        "expired",
        "not_yet_valid",
        "unsigned_capability",
        "bad_signature",
        "unknown_issuer",
        "audience_mismatch",
        "model_not_authorized",
        "profile_mismatch",
        "intent_not_authorized",
        "no_capability_loaded",
    )

    def __init__(self, audience: str, trusted_keys: Mapping[str, VerifyKey]) -> None:
        if not audience:
            raise CapabilityError("audience must not be empty")
        self._audience = audience
        self._trusted_keys = dict(trusted_keys)
        self._capabilities: dict[str, AuthorityCapability] = {}
        self._revoked: set[str] = set()
        self._refusals: list[str] = []

    @property
    def refusals(self) -> tuple[str, ...]:
        """Recorded refusal reasons, oldest first."""
        return tuple(self._refusals)

    def load(
        self,
        capability: AuthorityCapability,
        *,
        now: float,
        parent: AuthorityCapability | None = None,
    ) -> str | None:
        """Load a capability after full verification.

        A delegated capability carries its chain, so its parent may be supplied
        at load time instead of already being loaded in this store. Returns
        None on success or a refusal reason. A refused capability is not
        loaded.
        """
        reason = self._verify(capability, now, parent=parent)
        if reason is not None:
            return reason
        self._capabilities[capability.cap_id] = capability
        return None

    def _verify(
        self,
        capability: AuthorityCapability,
        now: float,
        parent: AuthorityCapability | None = None,
        check_audience: bool = True,
    ) -> str | None:
        if capability.signature is None:
            return "unsigned_capability"
        key = self._trusted_keys.get(capability.issuer)
        if key is None:
            return "unknown_issuer"
        if not capability.verify(key):
            return "bad_signature"
        if check_audience and capability.audience != self._audience:
            return "audience_mismatch"
        status = capability.validity.status_at(now)
        if status != "valid":
            return status
        if capability.parent_cap_id is not None:
            resolved = self._capabilities.get(capability.parent_cap_id) or parent
            if resolved is None or resolved.cap_id != capability.parent_cap_id:
                return "parent_not_available"
            # A parent in the chain was issued to its own audience, so the local
            # audience check does not apply to it.
            chain = self._verify(resolved, now, check_audience=False)
            if chain == "revoked":
                return "parent_revoked"
            if chain is not None:
                return "parent_invalid"
            if not capability.is_within(resolved):
                return "delegation_exceeds_parent"
        if capability.cap_id in self._revoked:
            return "revoked"
        return None

    def revoke(self, cap_id: str) -> None:
        """Revoke a capability locally. Revocation needs no network and no key."""
        self._revoked.add(cap_id)

    def is_revoked(self, cap_id: str) -> bool:
        return cap_id in self._revoked

    def _better(self, current: str | None, candidate: str) -> str:
        if current is None:
            return candidate
        if self._REASON_ORDER.index(candidate) < self._REASON_ORDER.index(current):
            return candidate
        return current

    def check_proposal(self, proposal: ProposedAction, *, now: float) -> str | None:
        """Return a refusal reason, or None when a capability authorizes the proposal.

        When nothing authorizes the proposal, the most specific failure is
        reported: a revoked capability before an unauthorized intent, an
        unauthorized model before an unauthorized intent class.
        """
        best: str | None = None
        for capability in self._capabilities.values():
            reason = self._verify(capability, now)
            if reason is not None:
                best = self._better(best, reason)
                continue
            if not capability.authorizes_intent(proposal.intent):
                best = self._better(best, "intent_not_authorized")
                continue
            provenance = proposal.provenance
            if not capability.authorizes_model(provenance.model_id, provenance.model_version):
                best = self._better(best, "model_not_authorized")
                continue
            if capability.profile_id != provenance.profile_id:
                best = self._better(best, "profile_mismatch")
                continue
            return None
        if best is None:
            best = "no_capability_loaded"
        self._refusals.append(best)
        return best

    def clamp(self, command: ActuatorCommand, *, now: float) -> ActuatorCommand:
        """Clamp a command to the tightest valid loaded actuator bounds.

        A clamped command is marked as vetoed by the supervisor, because the
        authority bound is a hard limit exactly like the envelope's own.
        """
        valid = [
            capability for capability in self._capabilities.values()
            if self._verify(capability, now) is None
        ]
        torque_bound = min((c.torque_bound_nm() for c in valid), default=None)
        velocity_bound = min((c.velocity_bound_rad_s() for c in valid), default=None)
        torque = command.torque_nm
        velocity = command.velocity_rad_s
        clamped = False
        if torque_bound is not None and abs(torque) > torque_bound:
            torque = max(-torque_bound, min(torque_bound, torque))
            clamped = True
        if velocity_bound is not None and abs(velocity) > velocity_bound:
            velocity = max(-velocity_bound, min(velocity_bound, velocity))
            clamped = True
        if not clamped:
            return command
        return ActuatorCommand(
            intent=command.intent,
            torque_nm=torque,
            velocity_rad_s=velocity,
            envelope_state=command.envelope_state,
            effective_confidence=command.effective_confidence,
            vetoed_by_supervisor=True,
            refusal_reason=command.refusal_reason,
        )


def refused_command(proposal: ProposedAction, reliability: float, reason: str) -> ActuatorCommand:
    """Build the SAFE_HALT command returned for a refused proposal."""
    return ActuatorCommand(
        intent=proposal.intent,
        torque_nm=0.0,
        velocity_rad_s=0.0,
        envelope_state=EnvelopeState.SAFE_HALT,
        effective_confidence=round(proposal.confidence * reliability, 6),
        vetoed_by_supervisor=False,
        refusal_reason=reason,
    )


class EnforcementBoundary:
    """The L0 to L2 software enforcement boundary.

    Composes the capability authority (L0) with the confidence-coupled safety
    envelope (L2). A proposal enters; a bounded command leaves. There is no
    other path, and no bypass: a capability refusal produces a SAFE_HALT
    command, an envelope refusal produces a SAFE_HALT command, and a command
    that passes both is clamped to the loaded capability bounds.

    Args:
        store: The capability authority for this device.
        envelope: The confidence-coupled safety envelope.
    """

    def __init__(self, store: CapabilityStore, envelope) -> None:
        self._store = store
        self._envelope = envelope

    @property
    def refusals(self) -> tuple[str, ...]:
        """Capability refusal reasons recorded by the authority."""
        return self._store.refusals

    def evaluate_proposal(
        self,
        proposal: ProposedAction,
        quality,
        *,
        now: float,
        requested_torque_nm: float | None = None,
        requested_velocity_rad_s: float | None = None,
    ) -> ActuatorCommand:
        """Evaluate one untrusted proposal through the full boundary.

        Args:
            proposal: Untrusted action proposal with provenance.
            quality: Signal quality for the same window.
            now: Current time for capability validity checks.
            requested_torque_nm: Nominal torque; omitted means the envelope's
                built-in request table.
            requested_velocity_rad_s: Nominal velocity; same rule.

        Returns:
            A bounded ActuatorCommand. Never motion for a refused proposal.
        """
        reason = self._store.check_proposal(proposal, now=now)
        if reason is not None:
            return refused_command(proposal, quality.reliability, reason)
        command = self._envelope.evaluate_proposal(
            proposal,
            quality,
            requested_torque_nm=requested_torque_nm,
            requested_velocity_rad_s=requested_velocity_rad_s,
        )
        return self._store.clamp(command, now=now)
