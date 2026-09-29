using System;
using System.Runtime.InteropServices;

namespace Esthien.Argus
{
    /// <summary>
    /// Safety envelope operating state.
    /// </summary>
    public enum EnvelopeState
    {
        Nominal = 0,
        Degraded = 1,
        SafeHalt = 2
    }

    /// <summary>
    /// Safety configuration for the envelope.
    /// </summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct SafetyConfig
    {
        public double THigh;
        public double TLow;
        public double DegradedVelocityScale;
        public double DegradedForceScale;
        public double HardMaxTorqueNm;
        public double HardMaxVelocityRadS;
        public uint PersistenceWindows;

        public static SafetyConfig Default => new SafetyConfig
        {
            THigh = 0.75,
            TLow = 0.45,
            DegradedVelocityScale = 0.5,
            DegradedForceScale = 0.4,
            HardMaxTorqueNm = 40.0,
            HardMaxVelocityRadS = 6.0,
            PersistenceWindows = 3
        };
    }

    /// <summary>
    /// Prediction from an inference engine.
    /// </summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct Prediction
    {
        [MarshalAs(UnmanagedType.LPStr)]
        public string Intent;
        public double Confidence;
    }

    /// <summary>
    /// Signal quality assessment.
    /// </summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct SignalQuality
    {
        public double Reliability;
        public IntPtr FlatlineChannels;
        public UIntPtr FlatlineCount;
        public int ArtifactDetected;
    }

    /// <summary>
    /// Actuator command emitted by the envelope.
    /// </summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct ActuatorCommand
    {
        [MarshalAs(UnmanagedType.LPStr)]
        public string Intent;
        public double TorqueNm;
        public double VelocityRadS;
        public int EnvelopeState;
        public double EffectiveConfidence;
        public int VetoedBySupervisor;
    }

    /// <summary>
    /// Safety-supervised inference envelope for physical systems.
    /// </summary>
    public class SafetyEnvelope : IDisposable
    {
        private IntPtr _handle;
        private bool _disposed;

        // P/Invoke declarations
        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern IntPtr argus_envelope_create(ref SafetyConfig config);

        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern void argus_envelope_destroy(IntPtr handle);

        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern int argus_envelope_reset(IntPtr handle);

        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern int argus_envelope_evaluate(
            IntPtr handle,
            IntPtr prediction,
            IntPtr quality,
            IntPtr command);

        // Native interop layouts. The ABI carries the intent as a C string
        // pointer, so structs are marshalled explicitly through unmanaged
        // memory rather than as ref/out managed structs.
        [StructLayout(LayoutKind.Sequential)]
        private struct PredictionC
        {
            public IntPtr Intent;
            public double Confidence;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SignalQualityC
        {
            public double Reliability;
            public IntPtr FlatlineChannels;
            public UIntPtr FlatlineCount;
            public int ArtifactDetected;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct ActuatorCommandC
        {
            public IntPtr Intent;
            public double TorqueNm;
            public double VelocityRadS;
            public int EnvelopeState;
            public double EffectiveConfidence;
            public int VetoedBySupervisor;
        }

        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern int argus_envelope_get_state(IntPtr handle, out int state);

        [DllImport("argus", CallingConvention = CallingConvention.Cdecl)]
        private static extern int argus_envelope_get_low_streak(IntPtr handle, out uint streak);

        /// <summary>
        /// Create a new safety envelope.
        /// </summary>
        public SafetyEnvelope(SafetyConfig config)
        {
            _handle = argus_envelope_create(ref config);
            if (_handle == IntPtr.Zero)
            {
                throw new InvalidOperationException("Failed to create safety envelope");
            }
        }

        /// <summary>
        /// Reset the envelope to SAFE_HALT state.
        /// </summary>
        public void Reset()
        {
            int result = argus_envelope_reset(_handle);
            if (result != 0)
            {
                throw new InvalidOperationException($"Reset failed: {result}");
            }
        }

        /// <summary>
        /// Evaluate one window.
        /// </summary>
        public ActuatorCommandResult Evaluate(Prediction prediction, SignalQualityData quality)
        {
            IntPtr intentPtr = Marshal.StringToHGlobalAnsi(prediction.Intent ?? string.Empty);
            IntPtr predictionPtr = Marshal.AllocHGlobal(Marshal.SizeOf<PredictionC>());
            IntPtr qualityPtr = Marshal.AllocHGlobal(Marshal.SizeOf<SignalQualityC>());
            IntPtr commandPtr = Marshal.AllocHGlobal(Marshal.SizeOf<ActuatorCommandC>());

            uint[] flatline = quality.FlatlineChannels ?? Array.Empty<uint>();
            GCHandle flatlineHandle = GCHandle.Alloc(flatline, GCHandleType.Pinned);
            try
            {
                var nativePrediction = new PredictionC
                {
                    Intent = intentPtr,
                    Confidence = prediction.Confidence,
                };
                var nativeQuality = new SignalQualityC
                {
                    Reliability = quality.Reliability,
                    FlatlineChannels = flatlineHandle.AddrOfPinnedObject(),
                    FlatlineCount = (UIntPtr)flatline.Length,
                    ArtifactDetected = quality.ArtifactDetected ? 1 : 0,
                };
                Marshal.StructureToPtr(nativePrediction, predictionPtr, false);
                Marshal.StructureToPtr(nativeQuality, qualityPtr, false);

                int result = argus_envelope_evaluate(_handle, predictionPtr, qualityPtr, commandPtr);
                if (result != 0)
                {
                    throw new InvalidOperationException($"Evaluation failed: {result}");
                }

                ActuatorCommandC command = Marshal.PtrToStructure<ActuatorCommandC>(commandPtr);
                return new ActuatorCommandResult
                {
                    Intent = Marshal.PtrToStringAnsi(command.Intent) ?? string.Empty,
                    TorqueNm = command.TorqueNm,
                    VelocityRadS = command.VelocityRadS,
                    State = (EnvelopeState)command.EnvelopeState,
                    EffectiveConfidence = command.EffectiveConfidence,
                    VetoedBySupervisor = command.VetoedBySupervisor != 0,
                };
            }
            finally
            {
                if (flatlineHandle.IsAllocated)
                {
                    flatlineHandle.Free();
                }
                Marshal.FreeHGlobal(intentPtr);
                Marshal.FreeHGlobal(predictionPtr);
                Marshal.FreeHGlobal(qualityPtr);
                Marshal.FreeHGlobal(commandPtr);
            }
        }

        /// <summary>
        /// Get current envelope state.
        /// </summary>
        public EnvelopeState State
        {
            get
            {
                int result = argus_envelope_get_state(_handle, out int state);
                if (result != 0)
                {
                    throw new InvalidOperationException($"Get state failed: {result}");
                }
                return (EnvelopeState)state;
            }
        }

        /// <summary>
        /// Get current low streak count.
        /// </summary>
        public uint LowStreak
        {
            get
            {
                int result = argus_envelope_get_low_streak(_handle, out uint streak);
                if (result != 0)
                {
                    throw new InvalidOperationException($"Get low streak failed: {result}");
                }
                return streak;
            }
        }

        public void Dispose()
        {
            if (!_disposed)
            {
                if (_handle != IntPtr.Zero)
                {
                    argus_envelope_destroy(_handle);
                    _handle = IntPtr.Zero;
                }
                _disposed = true;
            }
            GC.SuppressFinalize(this);
        }

        ~SafetyEnvelope()
        {
            Dispose();
        }
    }

    /// <summary>
    /// Signal quality data (managed).
    /// </summary>
    public class SignalQualityData
    {
        public double Reliability { get; set; }
        public uint[] FlatlineChannels { get; set; } = Array.Empty<uint>();
        public bool ArtifactDetected { get; set; }
    }

    /// <summary>
    /// Actuator command result (managed).
    /// </summary>
    public class ActuatorCommandResult
    {
        public string Intent { get; set; } = string.Empty;
        public double TorqueNm { get; set; }
        public double VelocityRadS { get; set; }
        public EnvelopeState State { get; set; }
        public double EffectiveConfidence { get; set; }
        public bool VetoedBySupervisor { get; set; }
    }
}
