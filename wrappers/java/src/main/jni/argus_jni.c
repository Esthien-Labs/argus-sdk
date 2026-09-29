// Argus SDK Java JNI wrapper
// This file compiles to a native library that Java can call via JNI

#include <jni.h>
#include <string.h>

// C ABI types (must match argus/abi/__init__.py)
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

// External C ABI functions
extern ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config);
extern void argus_envelope_destroy(ArgusEnvelopeHandle handle);
extern int argus_envelope_reset(ArgusEnvelopeHandle handle);
extern int argus_envelope_evaluate(ArgusEnvelopeHandle handle, const ArgusPredictionC* prediction,
                                    const ArgusSignalQualityC* quality, ArgusActuatorCommandC* command_out);
extern int argus_envelope_get_state(ArgusEnvelopeHandle handle, int* state_out);
extern int argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, unsigned int* streak_out);

// JNI wrappers

JNIEXPORT jlong JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeCreate(
    JNIEnv* env, jobject obj, jdouble tHigh, jdouble tLow,
    jdouble degradedVelocityScale, jdouble degradedForceScale,
    jdouble hardMaxTorqueNm, jdouble hardMaxVelocityRadS, jint persistenceWindows) {

    ArgusSafetyConfigC cfg;
    cfg.t_high = tHigh;
    cfg.t_low = tLow;
    cfg.degraded_velocity_scale = degradedVelocityScale;
    cfg.degraded_force_scale = degradedForceScale;
    cfg.hard_max_torque_nm = hardMaxTorqueNm;
    cfg.hard_max_velocity_rad_s = hardMaxVelocityRadS;
    cfg.persistence_windows = persistenceWindows;

    ArgusEnvelopeHandle handle = argus_envelope_create(&cfg);
    return (jlong)handle;
}

JNIEXPORT void JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeDestroy(
    JNIEnv* env, jobject obj, jlong handle) {
    argus_envelope_destroy((ArgusEnvelopeHandle)handle);
}

JNIEXPORT jint JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeReset(
    JNIEnv* env, jobject obj, jlong handle) {
    return argus_envelope_reset((ArgusEnvelopeHandle)handle);
}

JNIEXPORT jobject JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeEvaluate(
    JNIEnv* env, jobject obj, jlong handle, jstring intent, jdouble confidence,
    jdouble reliability, jintArray flatlineChannels, jboolean artifactDetected) {

    const char* intentStr = (*env)->GetStringUTFChars(env, intent, NULL);

    ArgusPredictionC pred;
    pred.intent = intentStr;
    pred.confidence = confidence;

    jint* flatline = (*env)->GetIntArrayElements(env, flatlineChannels, NULL);
    jsize flatlineLen = (*env)->GetArrayLength(env, flatlineChannels);

    ArgusSignalQualityC qual;
    qual.reliability = reliability;
    qual.flatline_channels = (unsigned int*)flatline;
    qual.flatline_count = flatlineLen;
    qual.artifact_detected = artifactDetected ? 1 : 0;

    ArgusActuatorCommandC cmd;
    int result = argus_envelope_evaluate((ArgusEnvelopeHandle)handle, &pred, &qual, &cmd);

    (*env)->ReleaseStringUTFChars(env, intent, intentStr);
    (*env)->ReleaseIntArrayElements(env, flatlineChannels, flatline, JNI_ABORT);

    if (result != 0) {
        return NULL;
    }

    // Create ActuatorCommand Java object
    jclass cmdClass = (*env)->FindClass(env, "com/esthien/argus/ActuatorCommand");
    jmethodID ctor = (*env)->GetMethodID(env, cmdClass, "<init>",
        "(Ljava/lang/String;DDIDZ)V");

    jstring cmdIntent = (*env)->NewStringUTF(env, cmd.intent);
    jobject cmdObj = (*env)->NewObject(env, cmdClass, ctor,
        cmdIntent, cmd.torque_nm, cmd.velocity_rad_s,
        cmd.envelope_state, cmd.effective_confidence,
        cmd.vetoed_by_supervisor != 0 ? JNI_TRUE : JNI_FALSE);

    return cmdObj;
}

JNIEXPORT jint JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeGetState(
    JNIEnv* env, jobject obj, jlong handle) {
    int state;
    int result = argus_envelope_get_state((ArgusEnvelopeHandle)handle, &state);
    if (result != 0) {
        return -1;
    }
    return state;
}

JNIEXPORT jint JNICALL Java_com_esthien_argus_SafetyEnvelope_nativeGetLowStreak(
    JNIEnv* env, jobject obj, jlong handle) {
    unsigned int streak;
    int result = argus_envelope_get_low_streak((ArgusEnvelopeHandle)handle, &streak);
    if (result != 0) {
        return -1;
    }
    return (jint)streak;
}
