# Argus SDK Python API Reference

Version: 0.7.4
Status: Public release.
Note: Every public name below is exported from the top-level `argus` package and loaded on first use.

---

## 1. Overview

The Argus SDK Python API evaluates profile-bound controller decisions. The default
evaluation path writes `digital_source_verification` evidence. The API does not assert
physical hardware, silicon, power, thermal, or safety-certification results.

The public surface has four groups:

| Group | Module | Purpose |
|---|---|---|
| Safety envelope | `argus.safety` | Confidence-coupled safety envelope and quality gate |
| Profile compiler | `argus.compiler` | Partner profile schema and compilation |
| Capability protocol | `argus.protocol` | Signed capability manifest negotiation |
| C ABI types | `argus.abi` | C-compatible structures and enums |

Every name is imported from the package root:

```python
from argus import ConfidenceCoupledSafetyEnvelope, SafetyConfig, Prediction, SignalQuality
```

## 2. Safety envelope

### `SafetyConfig`

Frozen dataclass. Envelope threshold and scaling parameters.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `t_high` | float | 0.75 | Effective-confidence threshold for NOMINAL |
| `t_low` | float | 0.45 | Threshold below which confidence is degraded |
| `degraded_velocity_scale` | float | 0.5 | Velocity scale in DEGRADED |
| `degraded_force_scale` | float | 0.4 | Torque scale in DEGRADED |
| `hard_max_torque_nm` | float | 40.0 | Absolute torque bound |
| `hard_max_velocity_rad_s` | float | 6.0 | Absolute velocity bound |
| `persistence_windows` | int | 3 | Consecutive low windows for SAFE_HALT |

Raises `ValueError` unless `0 < t_low < t_high < 1`, both scale factors are in `(0, 1]`,
both hard limits are positive, and `persistence_windows >= 1`.

### `Prediction`

Frozen dataclass. One inference result consumed by the envelope.

| Field | Type | Meaning |
|---|---|---|
| `intent` | str | Declared intent class label |
| `confidence` | float | Classifier posterior in `[0, 1]` |

Raises `ValueError` if `confidence` is outside `[0, 1]`.

### `EnvelopeState`

Enum of the operating state: `NOMINAL`, `DEGRADED`, `SAFE_HALT`.

### `SignalQuality`

Frozen dataclass. Output of the quality gate for one window.

| Field | Type | Meaning |
|---|---|---|
| `reliability` | float | Signal reliability R in `[0, 1]` |
| `flatline_channels` | tuple[int, ...] | Indices of flatlined channels |
| `artifact_detected` | bool | True if motion artifact dominates |

Raises `ValueError` if `reliability` is outside `[0, 1]`.

### `SignalQualityGate`

Estimates reliability R from a raw EMG window using three multiplicative penalties:
flatline or contact loss (each dead channel removes 25% of remaining reliability),
clipping (reliability multiplied by 0.6), and motion artifact (multiplied by 0.3).

```python
SignalQualityGate(flatline_std_uv: float = 5.0, clip_ratio: float = 0.98)
```

- `assess(emg_block)` takes a 2-D array of shape `(n_samples, n_channels)` with at least
  two samples and returns a `SignalQuality`. Raises `ValueError` on unexpected shape.

### `ActuatorCommand`

Frozen dataclass. Bounded command emitted for one decision window.

| Field | Type | Meaning |
|---|---|---|
| `intent` | str | Intent that produced the command |
| `torque_nm` | float | Commanded torque |
| `velocity_rad_s` | float | Commanded velocity |
| `envelope_state` | EnvelopeState | State that produced the command |
| `effective_confidence` | float | `C_eff = confidence * reliability` |
| `vetoed_by_supervisor` | bool | True if the hard-limit supervisor clipped it |

### `ConfidenceCoupledSafetyEnvelope`

Maps `(intent, confidence, signal quality)` to a bounded actuator command. The envelope
starts in `SAFE_HALT` (fail-safe) and requires one window at or above `t_high` to reach
`NOMINAL`. It enters `SAFE_HALT` only after `persistence_windows` consecutive windows
below `t_low`. An unknown intent always fails safe.

```python
ConfidenceCoupledSafetyEnvelope(cfg: SafetyConfig)
```

| Member | Description |
|---|---|
| `state` | Current `EnvelopeState` (property) |
| `low_streak` | Consecutive below-`t_low` windows (property) |
| `reset()` | Return to `SAFE_HALT`; required between replayed segments |
| `evaluate(prediction, quality)` | Evaluate with the built-in nominal request table |
| `evaluate_with_request(prediction, quality, requested_torque_nm, requested_velocity_rad_s)` | Evaluate with caller-supplied nominal values |

`evaluate_with_request` raises `ValueError` if the requested values are not finite.

Example:

```python
from argus import (
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    Prediction,
    SafetyConfig,
    SignalQuality,
)

envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig())
command = envelope.evaluate_with_request(
    Prediction(intent="knee_flexion", confidence=0.92),
    SignalQuality(reliability=0.95, flatline_channels=(), artifact_detected=False),
    requested_torque_nm=20.0,
    requested_velocity_rad_s=2.0,
)
assert command.envelope_state is EnvelopeState.NOMINAL
print(command.torque_nm, command.effective_confidence)
```

## 3. Profile compiler

### `PartnerProfile`

Frozen dataclass, schema version `"1.0"`. Fields: `schema_version`, `profile_id`,
`sensors` (tuple of `SensorSpec`), `intent_classes`, `actuator` (`ActuatorSpec`),
`fault_paths` (tuple of `FaultPath`).

| Method | Description |
|---|---|
| `from_mapping(value)` | Build from a mapping; raises `ProfileValidationError` |
| `from_json_file(path)` | Build from a JSON file |
| `to_mapping()` | Serialise to a mapping |

Validation requires unique sensor names, unique intent classes (max 64), and exactly one
fault path per sensor.

### `SensorSpec`

Fields: `name`, `sensor_type`, `channels` (1 to 64), `sample_rate_hz` (max 1,000,000),
`noise_threshold`.

### `ActuatorSpec`

Fields: `name`, `max_torque_nm`, `max_velocity_rad_s`, `position_min_rad`,
`position_max_rad`, with `position_min_rad < position_max_rad`.

### `FaultPath`

Fields: `sensor`, `action`. Action must be one of the defined fallback actions.

### `ProfileCompiler`

```python
ProfileCompiler().compile(profile: PartnerProfile) -> CompilationArtifacts
```

Returns the simulation profile, firmware header, RTL parameters, RTL defines, and fault
test vectors.

### `CompilationArtifacts`

Frozen dataclass with `profile_id` and `files` (mapping of file name to content).
`write(output_dir)` writes every file and returns the written paths.

Example:

```python
from pathlib import Path
from argus import PartnerProfile, ProfileCompiler

profile = PartnerProfile.from_json_file(Path("config/profiles/assistive_controller_v0.json"))
artifacts = ProfileCompiler().compile(profile)
artifacts.write(Path("out/profile-build"))
```

## 4. Capability protocol

### `CapabilityManifest`

Frozen dataclass, manifest version `"1.0"`. Fields: `manifest_version`, `device_id`,
`device_type`, `protocol_version`, `commands`, `sensors` (`SensorCapability`), `max_torque_nm`,
`max_velocity_rad_s`, `fault_behaviors`.

| Method | Description |
|---|---|
| `from_mapping(value)` | Parse an unsigned manifest; requires a valid HMAC-SHA256 signature field |
| `unsigned_mapping()` | The payload without a signature |
| `signed_mapping(secret)` | The payload with an HMAC-SHA256 signature |
| `from_signed_mapping(value, secret)` | Verify and parse; raises `ManifestValidationError` on failure |

Signatures use HMAC-SHA256 with a caller-supplied secret. This is a caller-managed
integrity check, not a release signing or key-custody system.

### `NegotiationPolicy`

Frozen dataclass: `protocol_version`, `required_commands`, `minimum_sensor_rates_hz`,
`required_fault_behaviors`, `required_torque_nm`, `required_velocity_rad_s`,
`max_allowed_torque_nm`, `max_allowed_velocity_rad_s`. Required ranges must not exceed the
policy maximums.

### `CapabilityNegotiator`

```python
CapabilityNegotiator(policy, secret).negotiate(raw_manifest) -> NegotiationResult
```

Verifies the signed manifest and returns a `NegotiationResult` with `accepted`,
`device_id`, `reasons`, and optional `agreed_limits`. Refusal reasons are deterministic.

## 5. C ABI types

The `argus.abi` module defines ctypes structures, enums, and function signatures for
cross-language FFI. See `C_ABI_REFERENCE.md`.

## 6. Exceptions

| Exception | Raised by |
|---|---|
| `ProfileValidationError` | Profile schema parsing |
| `ManifestValidationError` | Capability manifest parsing and signature checks |
| `ValueError` | Dataclass field validation |

## 7. Evidence boundary

Results from this API are `digital_source_verification` evidence unless a separate
measurement record says otherwise. The API does not establish physical timing, power,
thermal behaviour, functional-safety certification, production silicon, or customer
qualification. Any public performance figure must carry the measurement boundary in the
evaluation specification.
