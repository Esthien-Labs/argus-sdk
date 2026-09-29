package com.esthien.argus;

/**
 * Actuator command emitted by the safety envelope.
 */
public class ActuatorCommand {
    private final String intent;
    private final double torqueNm;
    private final double velocityRadS;
    private final EnvelopeState envelopeState;
    private final double effectiveConfidence;
    private final boolean vetoedBySupervisor;

    public ActuatorCommand(String intent, double torqueNm, double velocityRadS,
                          int envelopeState, double effectiveConfidence, boolean vetoedBySupervisor) {
        this.intent = intent;
        this.torqueNm = torqueNm;
        this.velocityRadS = velocityRadS;
        this.envelopeState = EnvelopeState.fromInt(envelopeState);
        this.effectiveConfidence = effectiveConfidence;
        this.vetoedBySupervisor = vetoedBySupervisor;
    }

    public String getIntent() { return intent; }
    public double getTorqueNm() { return torqueNm; }
    public double getVelocityRadS() { return velocityRadS; }
    public EnvelopeState getEnvelopeState() { return envelopeState; }
    public double getEffectiveConfidence() { return effectiveConfidence; }
    public boolean isVetoedBySupervisor() { return vetoedBySupervisor; }
}
