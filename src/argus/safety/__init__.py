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
from .sensor_health import SensorHealth, SensorHealthGate

__all__ = [
    "ActionProvenance",
    "ActuatorCommand",
    "AuthorityScope",
    "ConfidenceCoupledSafetyEnvelope",
    "DemoFrameRecord",
    "EnvelopeState",
    "IndependentHardwareSupervisor",
    "Prediction",
    "ProposedAction",
    "SafetyConfig",
    "SensorHealth",
    "SensorHealthGate",
    "SignalQuality",
    "SignalQualityGate",
    "run_pat001_showcase",
]
