package com.esthien.argus;

/**
 * Signal quality assessment.
 */
public class SignalQuality {
    private final double reliability;
    private final int[] flatlineChannels;
    private final boolean artifactDetected;

    public SignalQuality(double reliability, int[] flatlineChannels, boolean artifactDetected) {
        this.reliability = reliability;
        this.flatlineChannels = flatlineChannels;
        this.artifactDetected = artifactDetected;
    }

    public double getReliability() { return reliability; }
    public int[] getFlatlineChannels() { return flatlineChannels; }
    public boolean isArtifactDetected() { return artifactDetected; }
}
