// Package argus provides Go bindings for the Argus SDK safety envelope.
package argus

/*
#cgo LDFLAGS: -L${SRCDIR}/lib -largus
#cgo windows LDFLAGS: -L${SRCDIR}/lib -largus
#cgo darwin LDFLAGS: -L${SRCDIR}/lib -largus
#cgo linux LDFLAGS: -L${SRCDIR}/lib -largus

#include <stdlib.h>
#include <string.h>

typedef struct {
    double t_high;
    double t_low;
    double degraded_velocity_scale;
    double degraded_force_scale;
    double hard_max_torque_nm;
    double hard_max_velocity_rad_s;
    unsigned int persistence_windows;
} ArgusSafetyConfigC;

typedef struct {
    const char* intent;
    double confidence;
} ArgusPredictionC;

typedef struct {
    double reliability;
    unsigned int* flatline_channels;
    size_t flatline_count;
    int artifact_detected;
} ArgusSignalQualityC;

typedef struct {
    const char* intent;
    double torque_nm;
    double velocity_rad_s;
    int envelope_state;
    double effective_confidence;
    int vetoed_by_supervisor;
} ArgusActuatorCommandC;

typedef void* ArgusEnvelopeHandle;

extern ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config);
extern void argus_envelope_destroy(ArgusEnvelopeHandle handle);
extern int argus_envelope_reset(ArgusEnvelopeHandle handle);
extern int argus_envelope_evaluate(ArgusEnvelopeHandle handle, const ArgusPredictionC* prediction,
                                    const ArgusSignalQualityC* quality, ArgusActuatorCommandC* command_out);
extern int argus_envelope_get_state(ArgusEnvelopeHandle handle, int* state_out);
extern int argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, unsigned int* streak_out);
*/
import "C"

import (
	"errors"
	"unsafe"
)

// EnvelopeState represents the safety envelope operating state.
type EnvelopeState int

const (
	Nominal EnvelopeState = iota
	Degraded
	SafeHalt
)

// SafetyConfig holds the safety envelope configuration.
type SafetyConfig struct {
	THigh                 float64
	TLow                  float64
	DegradedVelocityScale float64
	DegradedForceScale    float64
	HardMaxTorqueNm       float64
	HardMaxVelocityRadS   float64
	PersistenceWindows    uint32
}

// DefaultSafetyConfig returns the default safety configuration.
func DefaultSafetyConfig() SafetyConfig {
	return SafetyConfig{
		THigh:                 0.75,
		TLow:                  0.45,
		DegradedVelocityScale: 0.5,
		DegradedForceScale:    0.4,
		HardMaxTorqueNm:       40.0,
		HardMaxVelocityRadS:   6.0,
		PersistenceWindows:    3,
	}
}

// Prediction represents an inference result.
type Prediction struct {
	Intent     string
	Confidence float64
}

// SignalQuality represents a signal quality assessment.
type SignalQuality struct {
	Reliability       float64
	FlatlineChannels  []uint32
	ArtifactDetected  bool
}

// ActuatorCommand represents a bounded actuator command.
type ActuatorCommand struct {
	Intent               string
	TorqueNm             float64
	VelocityRadS         float64
	EnvelopeState        EnvelopeState
	EffectiveConfidence  float64
	VetoedBySupervisor   bool
}

// SafetyEnvelope wraps the C safety envelope.
type SafetyEnvelope struct {
	handle C.ArgusEnvelopeHandle
}

// NewSafetyEnvelope creates a new safety envelope.
func NewSafetyEnvelope(cfg SafetyConfig) (*SafetyEnvelope, error) {
	cCfg := C.ArgusSafetyConfigC{
		t_high:                 C.double(cfg.THigh),
		t_low:                  C.double(cfg.TLow),
		degraded_velocity_scale: C.double(cfg.DegradedVelocityScale),
		degraded_force_scale:    C.double(cfg.DegradedForceScale),
		hard_max_torque_nm:      C.double(cfg.HardMaxTorqueNm),
		hard_max_velocity_rad_s: C.double(cfg.HardMaxVelocityRadS),
		persistence_windows:     C.uint(cfg.PersistenceWindows),
	}

	handle := C.argus_envelope_create(&cCfg)
	if handle == nil {
		return nil, errors.New("failed to create envelope")
	}

	return &SafetyEnvelope{handle: handle}, nil
}

// Close destroys the envelope.
func (e *SafetyEnvelope) Close() {
	if e.handle != nil {
		C.argus_envelope_destroy(e.handle)
		e.handle = nil
	}
}

// Reset resets the envelope to SAFE_HALT state.
func (e *SafetyEnvelope) Reset() error {
	result := C.argus_envelope_reset(e.handle)
	if result != 0 {
		return errors.New("reset failed")
	}
	return nil
}

// Evaluate evaluates one window.
func (e *SafetyEnvelope) Evaluate(pred Prediction, quality SignalQuality) (*ActuatorCommand, error) {
	intentC := C.CString(pred.Intent)
	defer C.free(unsafe.Pointer(intentC))

	cPred := C.ArgusPredictionC{
		intent:     intentC,
		confidence: C.double(pred.Confidence),
	}

	var flatlinePtr *C.uint
	if len(quality.FlatlineChannels) > 0 {
		flatlinePtr = (*C.uint)(unsafe.Pointer(&quality.FlatlineChannels[0]))
	}

	cQual := C.ArgusSignalQualityC{
		reliability:      C.double(quality.Reliability),
		flatline_channels: flatlinePtr,
		flatline_count:   C.size_t(len(quality.FlatlineChannels)),
		artifact_detected: C.int(boolToInt(quality.ArtifactDetected)),
	}

	var cCmd C.ArgusActuatorCommandC
	result := C.argus_envelope_evaluate(e.handle, &cPred, &cQual, &cCmd)
	if result != 0 {
		return nil, errors.New("evaluation failed")
	}

	return &ActuatorCommand{
		Intent:              C.GoString(cCmd.intent),
		TorqueNm:            float64(cCmd.torque_nm),
		VelocityRadS:        float64(cCmd.velocity_rad_s),
		EnvelopeState:       EnvelopeState(cCmd.envelope_state),
		EffectiveConfidence: float64(cCmd.effective_confidence),
		VetoedBySupervisor:  cCmd.vetoed_by_supervisor != 0,
	}, nil
}

// State returns the current envelope state.
func (e *SafetyEnvelope) State() (EnvelopeState, error) {
	var state C.int
	result := C.argus_envelope_get_state(e.handle, &state)
	if result != 0 {
		return SafeHalt, errors.New("get state failed")
	}
	return EnvelopeState(state), nil
}

// LowStreak returns the current low streak count.
func (e *SafetyEnvelope) LowStreak() (uint32, error) {
	var streak C.uint
	result := C.argus_envelope_get_low_streak(e.handle, &streak)
	if result != 0 {
		return 0, errors.New("get low streak failed")
	}
	return uint32(streak), nil
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
