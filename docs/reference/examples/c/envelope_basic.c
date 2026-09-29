/* Evaluate one safety-envelope decision window with the Argus SDK C ABI. */
#include "argus.h"

#include <stdio.h>

int main(void) {
    ArgusSafetyConfigC config = {
        .t_high = 0.75,
        .t_low = 0.45,
        .degraded_velocity_scale = 0.5,
        .degraded_force_scale = 0.4,
        .hard_max_torque_nm = 40.0,
        .hard_max_velocity_rad_s = 6.0,
        .persistence_windows = 3,
    };

    ArgusEnvelopeHandle handle = argus_envelope_create(&config);
    if (handle == NULL) {
        fprintf(stderr, "argus_envelope_create failed\n");
        return 1;
    }

    ArgusPredictionC prediction = { .intent = "knee_flexion", .confidence = 0.92 };
    ArgusSignalQualityC quality = {
        .reliability = 0.95,
        .flatline_channels = NULL,
        .flatline_count = 0,
        .artifact_detected = 0,
    };
    ArgusActuatorCommandC command;

    int32_t rc = argus_envelope_evaluate(handle, &prediction, &quality, &command);
    if (rc != ARGUS_OK) {
        fprintf(stderr, "argus_envelope_evaluate returned %d\n", rc);
        argus_envelope_destroy(handle);
        return 1;
    }

    printf("state=%d\n", command.envelope_state);
    printf("torque_nm=%f velocity_rad_s=%f\n", command.torque_nm, command.velocity_rad_s);
    printf("effective_confidence=%f\n", command.effective_confidence);
    printf("nominal=%d\n", command.envelope_state == ARGUS_ENVELOPE_NOMINAL);

    argus_envelope_destroy(handle);
    return 0;
}
