"""Evaluate one safety-envelope decision window with the Argus SDK Python API."""

from argus import (
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    Prediction,
    SafetyConfig,
    SignalQuality,
)


def main() -> None:
    envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())

    # The envelope starts fail-safe. A high-confidence window reaches NOMINAL.
    command = envelope.evaluate_with_request(
        prediction=Prediction(intent="knee_flexion", confidence=0.92),
        quality=SignalQuality(reliability=0.95, flatline_channels=(), artifact_detected=False),
        requested_torque_nm=20.0,
        requested_velocity_rad_s=2.0,
    )

    assert command.envelope_state is EnvelopeState.NOMINAL
    print(f"state={command.envelope_state.name}")
    print(f"torque_nm={command.torque_nm} velocity_rad_s={command.velocity_rad_s}")
    print(f"effective_confidence={command.effective_confidence}")


if __name__ == "__main__":
    main()
