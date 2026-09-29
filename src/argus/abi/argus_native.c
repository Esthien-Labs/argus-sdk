// Argus SDK native safety-envelope library.
//
// Implements the C ABI declared in argus.h. The state machine mirrors the
// Python ConfidenceCoupledSafetyEnvelope in src/argus/safety/envelope.py.
//
// Build with scripts/build_native_library.py. The output is argus.dll (Windows),
// libargus.so (Linux), or libargus.dylib (macOS).

#include "argus.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    ArgusSafetyConfigC cfg;
    int32_t state;
    uint32_t low_streak;
    int initialized;
} argus_envelope_t;

typedef struct {
    const char* intent;
    double torque;
    double velocity;
} argus_nominal_request_t;

static const argus_nominal_request_t NOMINAL_REQUESTS[] = {
    {"rest", 0.0, 0.0},
    {"knee_flexion", 25.0, 3.0},
    {"knee_extension", 25.0, 3.0},
};

static const size_t NOMINAL_REQUEST_COUNT =
    sizeof(NOMINAL_REQUESTS) / sizeof(NOMINAL_REQUESTS[0]);

static double round6(double value) {
    return round(value * 1e6) / 1e6;
}

static double clamp(double value, double limit) {
    if (value > limit) {
        return limit;
    }
    if (value < -limit) {
        return -limit;
    }
    return value;
}

static int nominal_lookup(const char* intent, double* torque_out, double* velocity_out) {
    size_t i;
    if (intent == NULL) {
        *torque_out = 0.0;
        *velocity_out = 0.0;
        return 0;
    }
    for (i = 0; i < NOMINAL_REQUEST_COUNT; ++i) {
        if (strcmp(intent, NOMINAL_REQUESTS[i].intent) == 0) {
            *torque_out = NOMINAL_REQUESTS[i].torque;
            *velocity_out = NOMINAL_REQUESTS[i].velocity;
            return 1;
        }
    }
    *torque_out = 0.0;
    *velocity_out = 0.0;
    return 0;
}

static int config_is_valid(const ArgusSafetyConfigC* cfg) {
    if (cfg == NULL) {
        return 0;
    }
    if (!(0.0 < cfg->t_low && cfg->t_low < cfg->t_high && cfg->t_high < 1.0)) {
        return 0;
    }
    if (!(cfg->degraded_force_scale > 0.0 && cfg->degraded_force_scale <= 1.0)) {
        return 0;
    }
    if (!(cfg->degraded_velocity_scale > 0.0 && cfg->degraded_velocity_scale <= 1.0)) {
        return 0;
    }
    if (cfg->hard_max_torque_nm <= 0.0 || cfg->hard_max_velocity_rad_s <= 0.0) {
        return 0;
    }
    if (cfg->persistence_windows < 1) {
        return 0;
    }
    return 1;
}

int32_t argus_abi_version(void) {
    return ARGUS_ABI_VERSION;
}

ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config) {
    argus_envelope_t* env;

    if (!config_is_valid(config)) {
        return NULL;
    }

    env = (argus_envelope_t*)calloc(1, sizeof(argus_envelope_t));
    if (env == NULL) {
        return NULL;
    }
    env->cfg = *config;
    env->state = ARGUS_ENVELOPE_SAFE_HALT;  // fail-safe on construction
    env->low_streak = 0;
    env->initialized = 1;
    return (ArgusEnvelopeHandle)env;
}

void argus_envelope_destroy(ArgusEnvelopeHandle handle) {
    free(handle);
}

int32_t argus_envelope_reset(ArgusEnvelopeHandle handle) {
    argus_envelope_t* env = (argus_envelope_t*)handle;
    if (env == NULL || !env->initialized) {
        return ARGUS_NOT_INITIALIZED;
    }
    env->low_streak = 0;
    env->state = ARGUS_ENVELOPE_SAFE_HALT;
    return ARGUS_OK;
}

int32_t argus_envelope_evaluate(
    ArgusEnvelopeHandle handle,
    const ArgusPredictionC* prediction,
    const ArgusSignalQualityC* quality,
    ArgusActuatorCommandC* command_out
) {
    argus_envelope_t* env = (argus_envelope_t*)handle;
    double c_eff;
    double base_torque;
    double base_velocity;
    double torque;
    double velocity;
    int known_intent;
    int vetoed = 0;

    if (env == NULL || !env->initialized) {
        return ARGUS_NOT_INITIALIZED;
    }
    if (prediction == NULL || quality == NULL || command_out == NULL) {
        return ARGUS_INVALID_ARGUMENT;
    }
    if (!(prediction->confidence >= 0.0 && prediction->confidence <= 1.0)) {
        return ARGUS_INVALID_ARGUMENT;
    }
    if (!(quality->reliability >= 0.0 && quality->reliability <= 1.0)) {
        return ARGUS_INVALID_ARGUMENT;
    }

    c_eff = round6(prediction->confidence * quality->reliability);

    if (c_eff < env->cfg.t_low) {
        env->low_streak += 1;
    } else {
        env->low_streak = 0;
    }

    if (env->low_streak >= env->cfg.persistence_windows) {
        env->state = ARGUS_ENVELOPE_SAFE_HALT;
    } else if (c_eff >= env->cfg.t_high) {
        env->state = ARGUS_ENVELOPE_NOMINAL;
    } else {
        env->state = ARGUS_ENVELOPE_DEGRADED;
    }

    known_intent = nominal_lookup(prediction->intent, &base_torque, &base_velocity);
    if (!known_intent) {
        env->state = ARGUS_ENVELOPE_SAFE_HALT;
    }

    if (env->state == ARGUS_ENVELOPE_NOMINAL) {
        torque = base_torque;
        velocity = base_velocity;
    } else if (env->state == ARGUS_ENVELOPE_DEGRADED) {
        torque = base_torque * env->cfg.degraded_force_scale;
        velocity = base_velocity * env->cfg.degraded_velocity_scale;
    } else {
        torque = 0.0;
        velocity = 0.0;
    }

    if (fabs(torque) > env->cfg.hard_max_torque_nm) {
        torque = clamp(torque, env->cfg.hard_max_torque_nm);
        vetoed = 1;
    }
    if (fabs(velocity) > env->cfg.hard_max_velocity_rad_s) {
        velocity = clamp(velocity, env->cfg.hard_max_velocity_rad_s);
        vetoed = 1;
    }

    command_out->intent = prediction->intent;
    command_out->torque_nm = torque;
    command_out->velocity_rad_s = velocity;
    command_out->envelope_state = env->state;
    command_out->effective_confidence = c_eff;
    command_out->vetoed_by_supervisor = vetoed;
    return ARGUS_OK;
}

int32_t argus_envelope_get_state(ArgusEnvelopeHandle handle, int32_t* state_out) {
    argus_envelope_t* env = (argus_envelope_t*)handle;
    if (env == NULL || !env->initialized) {
        return ARGUS_NOT_INITIALIZED;
    }
    if (state_out == NULL) {
        return ARGUS_INVALID_ARGUMENT;
    }
    *state_out = env->state;
    return ARGUS_OK;
}

int32_t argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, uint32_t* streak_out) {
    argus_envelope_t* env = (argus_envelope_t*)handle;
    if (env == NULL || !env->initialized) {
        return ARGUS_NOT_INITIALIZED;
    }
    if (streak_out == NULL) {
        return ARGUS_INVALID_ARGUMENT;
    }
    *streak_out = env->low_streak;
    return ARGUS_OK;
}
