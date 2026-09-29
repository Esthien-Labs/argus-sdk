package com.esthien.argus;

/**
 * Safety envelope configuration.
 */
public class SafetyConfig {
    private final double tHigh;
    private final double tLow;
    private final double degradedVelocityScale;
    private final double degradedForceScale;
    private final double hardMaxTorqueNm;
    private final double hardMaxVelocityRadS;
    private final int persistenceWindows;

    public SafetyConfig(double tHigh, double tLow, double degradedVelocityScale,
                        double degradedForceScale, double hardMaxTorqueNm,
                        double hardMaxVelocityRadS, int persistenceWindows) {
        this.tHigh = tHigh;
        this.tLow = tLow;
        this.degradedVelocityScale = degradedVelocityScale;
        this.degradedForceScale = degradedForceScale;
        this.hardMaxTorqueNm = hardMaxTorqueNm;
        this.hardMaxVelocityRadS = hardMaxVelocityRadS;
        this.persistenceWindows = persistenceWindows;
    }

    public static SafetyConfig defaults() {
        return new SafetyConfig(0.75, 0.45, 0.5, 0.4, 40.0, 6.0, 3);
    }

    public double getTHigh() { return tHigh; }
    public double getTLow() { return tLow; }
    public double getDegradedVelocityScale() { return degradedVelocityScale; }
    public double getDegradedForceScale() { return degradedForceScale; }
    public double getHardMaxTorqueNm() { return hardMaxTorqueNm; }
    public double getHardMaxVelocityRadS() { return hardMaxVelocityRadS; }
    public int getPersistenceWindows() { return persistenceWindows; }
}
