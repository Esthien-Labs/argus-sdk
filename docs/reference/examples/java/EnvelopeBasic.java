// Evaluate one safety-envelope decision window with the Argus SDK Java wrapper.
import com.esthien.argus.ActuatorCommand;
import com.esthien.argus.EnvelopeState;
import com.esthien.argus.Prediction;
import com.esthien.argus.SafetyConfig;
import com.esthien.argus.SafetyEnvelope;
import com.esthien.argus.SignalQuality;

public final class EnvelopeBasic {
    private EnvelopeBasic() {
    }

    public static void main(String[] args) {
        try (SafetyEnvelope envelope = new SafetyEnvelope(SafetyConfig.defaults())) {
            ActuatorCommand command = envelope.evaluate(
                    new Prediction("knee_flexion", 0.92),
                    new SignalQuality(0.95, new int[] {}, false));

            System.out.println("state=" + command.getEnvelopeState());
            System.out.println("torqueNm=" + command.getTorqueNm()
                    + " velocityRadS=" + command.getVelocityRadS());
            System.out.println("effectiveConfidence=" + command.getEffectiveConfidence());
            System.out.println("nominal=" + (command.getEnvelopeState() == EnvelopeState.NOMINAL));
        }
    }
}
