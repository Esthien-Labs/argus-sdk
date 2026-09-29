"""Atlas Confidence-Coupled Safety Envelope."""

from .envelope import (
    ActuatorCommand,
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    IndependentHardwareSupervisor,
    Prediction,
    SafetyConfig,
    SignalQuality,
    SignalQualityGate,
)
from .interactive_demo import (
    DemoFrameRecord,
    run_pat001_showcase,
)

__all__ = [
    "ActuatorCommand",
    "ConfidenceCoupledSafetyEnvelope",
    "DemoFrameRecord",
    "EnvelopeState",
    "IndependentHardwareSupervisor",
    "Prediction",
    "SafetyConfig",
    "SignalQuality",
    "SignalQualityGate",
    "run_pat001_showcase",
]
