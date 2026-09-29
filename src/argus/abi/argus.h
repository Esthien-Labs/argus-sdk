// Argus SDK C ABI header.
// Canonical contract for the native safety-envelope library (argus.dll / libargus.so / libargus.dylib).
// All language wrappers bind to the symbols declared here.

#ifndef ARGUS_H
#define ARGUS_H

// ABI version. Increment on any change to a struct layout or function signature.
#define ARGUS_ABI_VERSION 1

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>
#include <stdint.h>

// Error codes
typedef enum {
    ARGUS_OK = 0,
    ARGUS_INVALID_ARGUMENT = 1,
    ARGUS_INVALID_STATE = 2,
    ARGUS_BUFFER_TOO_SMALL = 3,
    ARGUS_NOT_INITIALIZED = 4,
    ARGUS_INTERNAL_ERROR = 5
} ArgusErrorCode;

// Envelope states
typedef enum {
    ARGUS_ENVELOPE_NOMINAL = 0,
    ARGUS_ENVELOPE_DEGRADED = 1,
    ARGUS_ENVELOPE_SAFE_HALT = 2
} ArgusEnvelopeState;

// Safety configuration
typedef struct {
    double t_high;
    double t_low;
    double degraded_velocity_scale;
    double degraded_force_scale;
    double hard_max_torque_nm;
    double hard_max_velocity_rad_s;
    uint32_t persistence_windows;
} ArgusSafetyConfigC;

// Prediction
typedef struct {
    const char* intent;
    double confidence;
} ArgusPredictionC;

// Signal quality
typedef struct {
    double reliability;
    uint32_t* flatline_channels;
    size_t flatline_count;
    int32_t artifact_detected;
} ArgusSignalQualityC;

// Actuator command
typedef struct {
    const char* intent;
    double torque_nm;
    double velocity_rad_s;
    int32_t envelope_state;
    double effective_confidence;
    int32_t vetoed_by_supervisor;
} ArgusActuatorCommandC;

// Opaque handle
typedef void* ArgusEnvelopeHandle;

// ABI version query. Returns ARGUS_ABI_VERSION.
int32_t argus_abi_version(void);

// C ABI functions
ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config);
void argus_envelope_destroy(ArgusEnvelopeHandle handle);
int32_t argus_envelope_reset(ArgusEnvelopeHandle handle);
int32_t argus_envelope_evaluate(
    ArgusEnvelopeHandle handle,
    const ArgusPredictionC* prediction,
    const ArgusSignalQualityC* quality,
    ArgusActuatorCommandC* command_out
);
int32_t argus_envelope_get_state(ArgusEnvelopeHandle handle, int32_t* state_out);
int32_t argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, uint32_t* streak_out);

#ifdef __cplusplus
}
#endif

#endif // ARGUS_H
