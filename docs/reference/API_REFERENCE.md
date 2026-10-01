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
| Safety envelope | `argus.safety` | Confidence-coupled safety envelope, proposal contract, and sensor health gate |
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
| `refusal_reason` | str or None | Set when the envelope refused a proposal outright |

## 2A. The proposal contract

A proposal from an AI system is not a command. The envelope is the only path from
proposal to actuator, and every proposal carries provenance.

### `ActionProvenance`

Frozen dataclass, mandatory on every proposal.

| Field | Type | Meaning |
|---|---|---|
| `model_id` | str | Identifier of the model or agent that produced the proposal |
| `model_version` | str | Version of that model or agent |
| `profile_id` | str | Authority profile the proposal was issued against |
| `source` | str | Where the proposal came from |
| `issued_at` | float | Unix timestamp |
| `attestation` | str or None | Optional integrity or attestation digest |

Raises `ValueError` if any identity field is empty or `issued_at` is not finite.

### `ProposedAction`

Frozen dataclass: `intent`, `confidence` in `[0, 1]`, `provenance`.

### `AuthorityScope`

Frozen dataclass declaring the authority one envelope enforces:

| Field | Type | Meaning |
|---|---|---|
| `profile_id` | str | Authority profile enforced by the envelope |
| `authorized_model_ids` | tuple[str, ...] | Model identities allowed to propose; empty means any |

### Evaluating a proposal

```python
envelope.evaluate_proposal(
    proposal,
    quality,
    requested_torque_nm=None,
    requested_velocity_rad_s=None,
)
```

A proposal whose profile does not match the scope, or whose model is not authorized,
is refused: the envelope enters `SAFE_HALT`, the returned command has zero torque and
velocity, `refusal_reason` is set, and `envelope.refusals` increments. A refusal does
not advance the low-confidence streak. Recovery afterwards requires one window at or
above `t_high`, as with any other exit from `SAFE_HALT`.

```python
from argus import (
    ActionProvenance,
    AuthorityScope,
    ConfidenceCoupledSafetyEnvelope,
    ProposedAction,
    SafetyConfig,
    SignalQuality,
)

authority = AuthorityScope(
    profile_id="robot_diff_drive_ros2_v0",
    authorized_model_ids=("planner-v3",),
)
envelope = ConfidenceCoupledSafetyEnvelope(SafetyConfig(), authority=authority)

proposal = ProposedAction(
    intent="knee_flexion",
    confidence=0.92,
    provenance=ActionProvenance(
        model_id="planner-v3",
        model_version="1.4.2",
        profile_id="robot_diff_drive_ros2_v0",
        source="hosted_agent",
        issued_at=1730000000.0,
    ),
)

command = envelope.evaluate_proposal(
    proposal,
    SignalQuality(reliability=0.95, flatline_channels=(), artifact_detected=False),
    requested_torque_nm=20.0,
    requested_velocity_rad_s=2.0,
)
if command.refusal_reason is not None:
    ...  # the proposal was refused; the actuator receives nothing
```

## 2B. Sensor health and out-of-distribution gating

`SensorHealthGate` declares a sensor's operating envelope and assesses windows
against it. It provides the out-of-distribution mitigation that AI functional-safety
standards call for, as a declared, deterministic, inspectable check rather than a
learned one.

```python
SensorHealthGate(
    flatline_std=5.0,
    clip_ratio=0.98,
    ood_z_threshold=4.0,
    ood_channel_fraction=0.25,
    artifact_common_mode_ratio=2.5,
)
```

| Member | Description |
|---|---|
| `declare_reference(reference)` | Declare the reference distribution from a reference window set; required before `assess` |
| `assess(window)` | Assess one window and return a `SensorHealth` |

`SensorHealth` carries `reliability`, `flatline_channels`, `artifact_detected`,
`out_of_distribution`, `ood_score`, and `flags`. Three penalties compose
multiplicatively: each flatlined channel removes 25% of the remaining reliability,
saturation multiplies by 0.6, a motion artifact multiplies by 0.3, and
out-of-distribution input multiplies by `1 - ood_score`.

`SensorHealth.as_signal_quality()` returns the equivalent `SignalQuality`, so the
result plugs into the existing envelope unchanged.

## 2B-2. Authority Capabilities

An Authority Capability is a signed, immutable token that bounds what an AI
system may do. It is the L0 authority layer of the enforcement boundary.

| Name | Purpose |
|---|---|
| `ActuatorBounds` | Per-actuator torque, velocity, and duration bounds |
| `CapabilityValidity` | Issue time, expiry, and offline grace |
| `AuthorityCapability` | The signed token itself |
| `CapabilityStore` | Load, revoke, and enforce capabilities for one audience |
| `EnforcementBoundary` | The L0 to L2 composition: capability authority plus the safety envelope |
| `delegate_capability` | Issue a strictly narrower derived token |
| `CapabilityError` | Raised for malformed tokens and invalid delegations |

A capability carries: `cap_id`, `issuer`, `audience` (the device it is bound
to), `intent_classes`, per-actuator `bounds`, `profile_id`, optional
`model_id`/`model_version` provenance binding, `validity`, an optional
`parent_cap_id` for delegated tokens, and an Ed25519 `signature` over the
canonical serialization.

Lifecycle:

1. **Issue.** The issuing authority signs the token with an Ed25519 signing key.
2. **Load.** `CapabilityStore.load(capability, now=..., parent=...)` verifies the
   signature against the trusted issuer key, the audience, expiry with offline
   grace, revocation, and the parent chain. A failed check refuses the load with
   a named reason.
3. **Enforce.** `EnforcementBoundary.evaluate_proposal(...)` checks every
   proposal against the loaded capabilities, evaluates it through the safety
   envelope, and clamps the command to the tightest loaded bounds. A refusal
   produces a `SAFE_HALT` command with a `refusal_reason`.
4. **Revoke.** `store.revoke(cap_id)` is local and needs no network and no key.
   Revoking a parent invalidates its derived tokens.
5. **Delegate.** `delegate_capability(parent, ...)` issues a derived token that
   is strictly narrower: fewer intent classes, tighter bounds, no longer
   validity. A wider delegation raises `CapabilityError`.

```python
from nacl.signing import SigningKey
from argus import (
    ActuatorBounds, ActionProvenance, AuthorityCapability, CapabilityStore,
    CapabilityValidity, ConfidenceCoupledSafetyEnvelope, EnforcementBoundary,
    ProposedAction, SafetyConfig, SignalQuality,
)

signing_key = SigningKey.generate()
capability = AuthorityCapability(
    cap_id="cap-001",
    issuer="esthien-root",
    audience="robot-001",
    intent_classes=("knee_flexion", "knee_extension"),
    bounds=(ActuatorBounds("knee_joint", max_torque_nm=25.0, max_velocity_rad_s=3.0),),
    profile_id="robot_diff_drive_ros2_v0",
    validity=CapabilityValidity(issued_at=1_000_000.0, expires_at=1_003_600.0),
).sign(signing_key)

store = CapabilityStore("robot-001", {"esthien-root": signing_key.verify_key})
store.load(capability, now=1_000_000.0)

boundary = EnforcementBoundary(store, ConfidenceCoupledSafetyEnvelope(SafetyConfig()))
command = boundary.evaluate_proposal(
    ProposedAction(
        intent="knee_flexion",
        confidence=0.92,
        provenance=ActionProvenance(
            model_id="planner-v3", model_version="1.4.2",
            profile_id="robot_diff_drive_ros2_v0", source="hosted_agent",
            issued_at=1_000_000.0,
        ),
    ),
    SignalQuality(reliability=0.95, flatline_channels=(), artifact_detected=False),
    now=1_000_000.0,
)
```

A compromised model cannot forge a capability, because it does not hold the
signing key. A compromised server cannot widen one, because the boundary clamps
every command to the loaded bounds. Revocation works with the cable pulled.

The signature scheme is Ed25519 through PyNaCl. This layer does not implement
key custody, release signing, or hardware binding; those remain separately
gated.

## 2C. The wedge containment benchmark

`argus.regression.wedge` runs the containment demonstration that separates the
enforcement boundary from a library. It runs two arms over the same declared
scenario and fault corpus:

- **baseline**: the controller's output goes to the actuator.
- **argus**: the controller's output enters the envelope as a proposal and only
  the envelope's output reaches the actuator.

The controller is a declared nearest-centroid linear policy whose features are
per-channel signal means. That choice creates the documented failure mode of
learned controllers: a motion pattern is a zero-mean alternating signal, so its
per-channel mean is zero, and a dead sensor's per-channel mean is also zero. The
controller cannot distinguish "no signal" from "zero-mean motion", so on a dead
sensor it keeps proposing motion with high confidence.

```python
from argus.regression.wedge import run_wedge_benchmark, write_wedge_report

result = run_wedge_benchmark()
paths = write_wedge_report(result, out_dir)
```

The report records, per declared fault: unsafe motion commands issued while the
sensor was faulted, for both arms; the first window at which the envelope reached
`SAFE_HALT`; and false stops, meaning clean windows where the boundary suppressed
a motion command the baseline would have issued.

This is `digital_source_verification` evidence on generated data. It establishes no
hardware, silicon, power, thermal, field, or comparative product claim.

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
