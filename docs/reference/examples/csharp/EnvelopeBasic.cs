// Evaluate one safety-envelope decision window with the Argus SDK C# wrapper.
using System;
using Esthien.Argus;

internal static class EnvelopeBasic
{
    private static void Main()
    {
        using var envelope = new SafetyEnvelope(SafetyConfig.Default);

        ActuatorCommandResult command = envelope.Evaluate(
            new Prediction { Intent = "knee_flexion", Confidence = 0.92 },
            new SignalQualityData { Reliability = 0.95, ArtifactDetected = false });

        Console.WriteLine($"state={command.State}");
        Console.WriteLine($"torqueNm={command.TorqueNm} velocityRadS={command.VelocityRadS}");
        Console.WriteLine($"effectiveConfidence={command.EffectiveConfidence}");
        Console.WriteLine($"nominal={command.State == EnvelopeState.Nominal}");
    }
}
