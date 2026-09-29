package com.esthien.argus;

/**
 * Safety-supervised inference envelope for physical systems.
 */
public class SafetyEnvelope implements AutoCloseable {
    static {
        // Loads argus_jni, the JNI bridge. The bridge links the Argus C ABI
        // library (argus.dll / libargus.so / libargus.dylib).
        System.loadLibrary("argus_jni");
    }

    private long handle;

    /**
     * Create a new safety envelope.
     */
    public SafetyEnvelope(SafetyConfig config) {
        this.handle = nativeCreate(
            config.getTHigh(),
            config.getTLow(),
            config.getDegradedVelocityScale(),
            config.getDegradedForceScale(),
            config.getHardMaxTorqueNm(),
            config.getHardMaxVelocityRadS(),
            config.getPersistenceWindows()
        );
        if (this.handle == 0) {
            throw new RuntimeException("Failed to create safety envelope");
        }
    }

    /**
     * Reset the envelope to SAFE_HALT state.
     */
    public void reset() {
        int result = nativeReset(handle);
        if (result != 0) {
            throw new RuntimeException("Reset failed: " + result);
        }
    }

    /**
     * Evaluate one window.
     */
    public ActuatorCommand evaluate(Prediction prediction, SignalQuality quality) {
        return nativeEvaluate(
            handle,
            prediction.getIntent(),
            prediction.getConfidence(),
            quality.getReliability(),
            quality.getFlatlineChannels(),
            quality.isArtifactDetected()
        );
    }

    /**
     * Get current envelope state.
     */
    public EnvelopeState getState() {
        int state = nativeGetState(handle);
        return EnvelopeState.fromInt(state);
    }

    /**
     * Get current low streak count.
     */
    public int getLowStreak() {
        return nativeGetLowStreak(handle);
    }

    @Override
    public void close() {
        if (handle != 0) {
            nativeDestroy(handle);
            handle = 0;
        }
    }

    // Native methods
    private native long nativeCreate(double tHigh, double tLow,
        double degradedVelocityScale, double degradedForceScale,
        double hardMaxTorqueNm, double hardMaxVelocityRadS, int persistenceWindows);
    private native void nativeDestroy(long handle);
    private native int nativeReset(long handle);
    private native ActuatorCommand nativeEvaluate(long handle, String intent,
        double confidence, double reliability, int[] flatlineChannels, boolean artifactDetected);
    private native int nativeGetState(long handle);
    private native int nativeGetLowStreak(long handle);
}
