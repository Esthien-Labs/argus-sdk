package com.esthien.argus;

/**
 * Prediction from an inference engine.
 */
public class Prediction {
    private final String intent;
    private final double confidence;

    public Prediction(String intent, double confidence) {
        this.intent = intent;
        this.confidence = confidence;
    }

    public String getIntent() { return intent; }
    public double getConfidence() { return confidence; }
}
