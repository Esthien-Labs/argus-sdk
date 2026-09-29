package com.esthien.argus;

/**
 * Safety envelope operating state.
 */
public enum EnvelopeState {
    NOMINAL(0),
    DEGRADED(1),
    SAFE_HALT(2);

    private final int value;

    EnvelopeState(int value) {
        this.value = value;
    }

    public int getValue() {
        return value;
    }

    public static EnvelopeState fromInt(int value) {
        switch (value) {
            case 0: return NOMINAL;
            case 1: return DEGRADED;
            case 2: return SAFE_HALT;
            default: return SAFE_HALT;
        }
    }
}
