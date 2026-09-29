// Evaluate one safety-envelope decision window with the Argus SDK Rust wrapper.
use argus::{EnvelopeState, Prediction, SafetyConfig, SafetyEnvelope, SignalQuality};

fn main() -> Result<(), i32> {
    let mut envelope = SafetyEnvelope::new(SafetyConfig::default())?;

    let prediction = Prediction {
        intent: "knee_flexion".to_string(),
        confidence: 0.92,
    };
    let quality = SignalQuality {
        reliability: 0.95,
        flatline_channels: vec![],
        artifact_detected: false,
    };

    let command = envelope.evaluate(&prediction, &quality)?;

    println!("state={:?}", command.envelope_state);
    println!("torque_nm={} velocity_rad_s={}", command.torque_nm, command.velocity_rad_s);
    println!("effective_confidence={}", command.effective_confidence);
    println!("nominal={}", command.envelope_state == EnvelopeState::Nominal);

    Ok(())
}
