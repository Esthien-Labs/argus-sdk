// JavaScript wrapper for Argus SDK
const { SafetyEnvelope: NativeSafetyEnvelope } = require('./build/Release/argus.node');

class SafetyEnvelope {
    constructor(config) {
        this._native = new NativeSafetyEnvelope(config);
    }

    reset() {
        return this._native.reset();
    }

    evaluate(prediction, quality) {
        return this._native.evaluate(prediction, quality);
    }

    getState() {
        return this._native.getState();
    }

    getLowStreak() {
        return this._native.getLowStreak();
    }
}

module.exports = {
    SafetyEnvelope,
    EnvelopeState: {
        NOMINAL: 0,
        DEGRADED: 1,
        SAFE_HALT: 2
    }
};
