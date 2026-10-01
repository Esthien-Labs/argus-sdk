"""Argus SDK package metadata and opt-in developer interfaces."""

from __future__ import annotations

from typing import Any

__version__ = "0.7.4"

_LAZY_EXPORTS = {
    "PartnerProfile": (".compiler", "PartnerProfile"),
    "ProfileCompiler": (".compiler", "ProfileCompiler"),
    "CapabilityManifest": (".protocol", "CapabilityManifest"),
    "CapabilityNegotiator": (".protocol", "CapabilityNegotiator"),
    "NegotiationPolicy": (".protocol", "NegotiationPolicy"),
    "ActionProvenance": (".safety", "ActionProvenance"),
    "ActuatorBounds": (".safety", "ActuatorBounds"),
    "ActuatorCommand": (".safety", "ActuatorCommand"),
    "AuthorityCapability": (".safety", "AuthorityCapability"),
    "AuthorityScope": (".safety", "AuthorityScope"),
    "CapabilityError": (".safety", "CapabilityError"),
    "CapabilityStore": (".safety", "CapabilityStore"),
    "CapabilityValidity": (".safety", "CapabilityValidity"),
    "ConfidenceCoupledSafetyEnvelope": (".safety", "ConfidenceCoupledSafetyEnvelope"),
    "EnforcementBoundary": (".safety", "EnforcementBoundary"),
    "EnvelopeState": (".safety", "EnvelopeState"),
    "Prediction": (".safety", "Prediction"),
    "ProposedAction": (".safety", "ProposedAction"),
    "SafetyConfig": (".safety", "SafetyConfig"),
    "SignalQuality": (".safety", "SignalQuality"),
    "SignalQualityGate": (".safety", "SignalQualityGate"),
    "delegate_capability": (".safety", "delegate_capability"),
    # C ABI exports for cross-language compatibility
    "ArgusEnvelopeState": (".abi", "ArgusEnvelopeState"),
    "ArgusErrorCode": (".abi", "ArgusErrorCode"),
    "ArgusSafetyConfigC": (".abi", "ArgusSafetyConfigC"),
    "ArgusPredictionC": (".abi", "ArgusPredictionC"),
    "ArgusSignalQualityC": (".abi", "ArgusSignalQualityC"),
    "ArgusActuatorCommandC": (".abi", "ArgusActuatorCommandC"),
    "ArgusEnvelopeHandle": (".abi", "ArgusEnvelopeHandle"),
}

__all__ = ["__version__", *_LAZY_EXPORTS]


def __getattr__(name: str) -> Any:
    """Load developer interfaces only when an integration explicitly imports one."""

    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
