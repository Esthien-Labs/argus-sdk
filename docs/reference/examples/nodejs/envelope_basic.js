// Evaluate one safety-envelope decision window with the Argus SDK Node.js wrapper.
const { SafetyEnvelope, EnvelopeState } = require('@esthien/argus');

const envelope = new SafetyEnvelope({
    tHigh: 0.75,
    tLow: 0.45,
    degradedVelocityScale: 0.5,
    degradedForceScale: 0.4,
    hardMaxTorqueNm: 40.0,
    hardMaxVelocityRadS: 6.0,
    persistenceWindows: 3,
});

const command = envelope.evaluate(
    { intent: 'knee_flexion', confidence: 0.92 },
    { reliability: 0.95, flatlineChannels: [], artifactDetected: false },
);

console.log(`state=${command.envelopeState}`);
console.log(`torqueNm=${command.torqueNm} velocityRadS=${command.velocityRadS}`);
console.log(`effectiveConfidence=${command.effectiveConfidence}`);
console.log(`nominal=${command.envelopeState === EnvelopeState.NOMINAL}`);
