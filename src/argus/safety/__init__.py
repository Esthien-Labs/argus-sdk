"""Atlas Confidence-Coupled Safety Envelope."""

from .envelope import (
    ActionProvenance,
    ActuatorCommand,
    AuthorityScope,
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    IndependentHardwareSupervisor,
    Prediction,
    ProposedAction,
    SafetyConfig,
    SignalQuality,
    SignalQualityGate,
)
from .interactive_demo import (
    DemoFrameRecord,
    run_pat001_showcase,
)
from .capability import (
    ActuatorBounds,
    AuthorityCapability,
    CapabilityError,
    CapabilityStore,
    CapabilityValidity,
    EnforcementBoundary,
    delegate_capability,
)
from .sensor_health import SensorHealth, SensorHealthGate

__all__ = [
    "ActionProvenance",
    "ActuatorBounds",
    "ActuatorCommand",
    "AuthorityCapability",
    "AuthorityScope",
    "CapabilityError",
    "CapabilityStore",
    "CapabilityValidity",
    "ConfidenceCoupledSafetyEnvelope",
    "DemoFrameRecord",
    "EnforcementBoundary",
    "EnvelopeState",
    "IndependentHardwareSupervisor",
    "Prediction",
    "ProposedAction",
    "SafetyConfig",
    "SensorHealth",
    "SensorHealthGate",
    "SignalQuality",
    "SignalQualityGate",
    "delegate_capability",
    "run_pat001_showcase",
]
