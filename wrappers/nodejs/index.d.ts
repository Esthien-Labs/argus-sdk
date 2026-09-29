// TypeScript definitions for Argus SDK

export enum EnvelopeState {
    NOMINAL = 0,
    DEGRADED = 1,
    SAFE_HALT = 2
}

export interface SafetyConfig {
    tHigh: number;
    tLow: number;
    degradedVelocityScale: number;
    degradedForceScale: number;
    hardMaxTorqueNm: number;
    hardMaxVelocityRadS: number;
    persistenceWindows: number;
}

export interface Prediction {
    intent: string;
    confidence: number;
}

export interface SignalQuality {
    reliability: number;
    flatlineChannels: number[];
    artifactDetected: boolean;
}

export interface ActuatorCommand {
    intent: string;
    torqueNm: number;
    velocityRadS: number;
    envelopeState: EnvelopeState;
    effectiveConfidence: number;
    vetoedBySupervisor: boolean;
}

export class SafetyEnvelope {
    constructor(config: SafetyConfig);
    reset(): number;
    evaluate(prediction: Prediction, quality: SignalQuality): ActuatorCommand;
    getState(): EnvelopeState;
    getLowStreak(): number;
}
