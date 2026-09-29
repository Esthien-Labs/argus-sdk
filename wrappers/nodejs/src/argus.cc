// Node.js N-API wrapper for Argus SDK safety envelope
// This file compiles to a native Node.js module

#include <napi.h>
#include <cstring>

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

// External C ABI functions (from compiled argus.dll/libargus.so/libargus.dylib)
extern "C" {
    ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config);
    void argus_envelope_destroy(ArgusEnvelopeHandle handle);
    int argus_envelope_reset(ArgusEnvelopeHandle handle);
    int argus_envelope_evaluate(ArgusEnvelopeHandle handle, const ArgusPredictionC* prediction,
                                 const ArgusSignalQualityC* quality, ArgusActuatorCommandC* command_out);
    int argus_envelope_get_state(ArgusEnvelopeHandle handle, int* state_out);
    int argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, unsigned int* streak_out);
}

class SafetyEnvelope : public Napi::ObjectWrap<SafetyEnvelope> {
public:
    static Napi::Object Init(Napi::Env env, Napi::Object exports);
    SafetyEnvelope(const Napi::CallbackInfo& info);
    ~SafetyEnvelope();

private:
    static Napi::FunctionReference constructor;
    ArgusEnvelopeHandle handle_;

    Napi::Value Reset(const Napi::CallbackInfo& info);
    Napi::Value Evaluate(const Napi::CallbackInfo& info);
    Napi::Value GetState(const Napi::CallbackInfo& info);
    Napi::Value GetLowStreak(const Napi::CallbackInfo& info);
};

Napi::FunctionReference SafetyEnvelope::constructor;

Napi::Object SafetyEnvelope::Init(Napi::Env env, Napi::Object exports) {
    Napi::Function func = DefineClass(env, "SafetyEnvelope", {
        InstanceMethod("reset", &SafetyEnvelope::Reset),
        InstanceMethod("evaluate", &SafetyEnvelope::Evaluate),
        InstanceMethod("getState", &SafetyEnvelope::GetState),
        InstanceMethod("getLowStreak", &SafetyEnvelope::GetLowStreak),
    });

    constructor = Napi::Persistent(func);
    constructor.SuppressDestruct();

    exports.Set("SafetyEnvelope", func);
    return exports;
}

SafetyEnvelope::SafetyEnvelope(const Napi::CallbackInfo& info)
    : Napi::ObjectWrap<SafetyEnvelope>(info) {
    Napi::Env env = info.Env();

    if (info.Length() < 1 || !info[0].IsObject()) {
        Napi::TypeError::New(env, "Expected config object").ThrowAsJavaScriptException();
        return;
    }

    Napi::Object config = info[0].As<Napi::Object>();

    ArgusSafetyConfigC cfg;
    cfg.t_high = config.Get("tHigh").ToNumber().DoubleValue();
    cfg.t_low = config.Get("tLow").ToNumber().DoubleValue();
    cfg.degraded_velocity_scale = config.Get("degradedVelocityScale").ToNumber().DoubleValue();
    cfg.degraded_force_scale = config.Get("degradedForceScale").ToNumber().DoubleValue();
    cfg.hard_max_torque_nm = config.Get("hardMaxTorqueNm").ToNumber().DoubleValue();
    cfg.hard_max_velocity_rad_s = config.Get("hardMaxVelocityRadS").ToNumber().DoubleValue();
    cfg.persistence_windows = config.Get("persistenceWindows").ToNumber().Uint32Value();

    handle_ = argus_envelope_create(&cfg);
    if (!handle_) {
        Napi::Error::New(env, "Failed to create envelope").ThrowAsJavaScriptException();
    }
}

SafetyEnvelope::~SafetyEnvelope() {
    if (handle_) {
        argus_envelope_destroy(handle_);
    }
}

Napi::Value SafetyEnvelope::Reset(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    int result = argus_envelope_reset(handle_);
    return Napi::Number::New(env, result);
}

Napi::Value SafetyEnvelope::Evaluate(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();

    if (info.Length() < 2) {
        Napi::TypeError::New(env, "Expected prediction and quality").ThrowAsJavaScriptException();
        return env.Null();
    }

    Napi::Object prediction = info[0].As<Napi::Object>();
    Napi::Object quality = info[1].As<Napi::Object>();

    std::string intent = prediction.Get("intent").ToString().Utf8Value();

    ArgusPredictionC pred;
    pred.intent = intent.c_str();
    pred.confidence = prediction.Get("confidence").ToNumber().DoubleValue();

    ArgusSignalQualityC qual;
    qual.reliability = quality.Get("reliability").ToNumber().DoubleValue();
    qual.flatline_channels = nullptr;
    qual.flatline_count = 0;
    qual.artifact_detected = quality.Get("artifactDetected").ToBoolean().Value() ? 1 : 0;

    ArgusActuatorCommandC cmd;
    int result = argus_envelope_evaluate(handle_, &pred, &qual, &cmd);

    if (result != 0) {
        Napi::Error::New(env, "Evaluation failed").ThrowAsJavaScriptException();
        return env.Null();
    }

    Napi::Object resultObj = Napi::Object::New(env);
    resultObj.Set("intent", Napi::String::New(env, cmd.intent));
    resultObj.Set("torqueNm", Napi::Number::New(env, cmd.torque_nm));
    resultObj.Set("velocityRadS", Napi::Number::New(env, cmd.velocity_rad_s));
    resultObj.Set("envelopeState", Napi::Number::New(env, cmd.envelope_state));
    resultObj.Set("effectiveConfidence", Napi::Number::New(env, cmd.effective_confidence));
    resultObj.Set("vetoedBySupervisor", Napi::Boolean::New(env, cmd.vetoed_by_supervisor != 0));

    return resultObj;
}

Napi::Value SafetyEnvelope::GetState(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    int state;
    int result = argus_envelope_get_state(handle_, &state);
    if (result != 0) {
        Napi::Error::New(env, "Failed to get state").ThrowAsJavaScriptException();
        return env.Null();
    }
    return Napi::Number::New(env, state);
}

Napi::Value SafetyEnvelope::GetLowStreak(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    unsigned int streak;
    int result = argus_envelope_get_low_streak(handle_, &streak);
    if (result != 0) {
        Napi::Error::New(env, "Failed to get low streak").ThrowAsJavaScriptException();
        return env.Null();
    }
    return Napi::Number::New(env, streak);
}

Napi::Object InitAll(Napi::Env env, Napi::Object exports) {
    return SafetyEnvelope::Init(env, exports);
}

NODE_API_MODULE(argus, InitAll)
