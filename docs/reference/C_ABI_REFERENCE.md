# Argus SDK C ABI Reference

Version: 0.7.4
Status: Public release.
Header: `src/argus/abi/argus.h` (mirrored at `wrappers/rust/include/argus.h`)
Note: The C ABI is the cross-language boundary for the safety envelope.

## ABI version

The current ABI version is `ARGUS_ABI_VERSION` = 1. The `argus_abi_version()`
function returns it. The struct layouts and function signatures are frozen at
this version; any change to them increments the version.

The native library is built from `src/argus/abi/argus_native.c` by
`scripts/build_native_library.py`. The C ABI decision logic is identical to the
pure-Python safety envelope and is checked for bit-for-bit agreement in
`tests/unit/test_abi_native.py`.

---

## 1. Design rules

- All functions use plain C, with no C++ exceptions and no RTTI.
- All memory is caller-allocated; there are no hidden allocations.
- All envelope state is opaque; implementation details never cross the boundary.
- All functions return an integer error code; no exceptions cross the boundary.

## 2. Library names

| Platform | File |
|---|---|
| Windows | `argus.dll` |
| macOS | `libargus.dylib` |
| Linux | `libargus.so` |

`argus.abi.load_library()` loads the library from the package directory first, then from
the system library path. It raises `OSError` if the library is not found.

## 3. Enums

### `ArgusErrorCode` (int32)

| Name | Value |
|---|---|
| `ARGUS_OK` | 0 |
| `ARGUS_INVALID_ARGUMENT` | 1 |
| `ARGUS_INVALID_STATE` | 2 |
| `ARGUS_BUFFER_TOO_SMALL` | 3 |
| `ARGUS_NOT_INITIALIZED` | 4 |
| `ARGUS_INTERNAL_ERROR` | 5 |

### `ArgusEnvelopeState` (int32)

| Name | Value |
|---|---|
| `ARGUS_ENVELOPE_NOMINAL` | 0 |
| `ARGUS_ENVELOPE_DEGRADED` | 1 |
| `ARGUS_ENVELOPE_SAFE_HALT` | 2 |

## 4. Structures

### `ArgusSafetyConfigC`

| Field | Type |
|---|---|
| `t_high` | double |
| `t_low` | double |
| `degraded_velocity_scale` | double |
| `degraded_force_scale` | double |
| `hard_max_torque_nm` | double |
| `hard_max_velocity_rad_s` | double |
| `persistence_windows` | uint32 |

### `ArgusPredictionC`

| Field | Type |
|---|---|
| `intent` | const char* |
| `confidence` | double |

### `ArgusSignalQualityC`

| Field | Type |
|---|---|
| `reliability` | double |
| `flatline_channels` | uint32* |
| `flatline_count` | size_t |
| `artifact_detected` | int32 (boolean) |

### `ArgusActuatorCommandC`

| Field | Type |
|---|---|
| `intent` | const char* |
| `torque_nm` | double |
| `velocity_rad_s` | double |
| `envelope_state` | int32 |
| `effective_confidence` | double |
| `vetoed_by_supervisor` | int32 (boolean) |

### `ArgusEnvelopeHandle`

Opaque handle to an envelope instance.

## 5. Functions

### `argus_envelope_create`

```c
ArgusEnvelopeHandle argus_envelope_create(const ArgusSafetyConfigC* config);
```

Creates an envelope. Returns an opaque handle, or a null pointer on invalid input.

### `argus_envelope_destroy`

```c
void argus_envelope_destroy(ArgusEnvelopeHandle handle);
```

Releases the envelope. Passing a null handle is safe.

### `argus_envelope_reset`

```c
int32_t argus_envelope_reset(ArgusEnvelopeHandle handle);
```

Returns the envelope to `ARGUS_ENVELOPE_SAFE_HALT`. Returns an `ArgusErrorCode`.

### `argus_envelope_evaluate`

```c
int32_t argus_envelope_evaluate(
    ArgusEnvelopeHandle handle,
    const ArgusPredictionC* prediction,
    const ArgusSignalQualityC* quality,
    ArgusActuatorCommandC* command_out
);
```

Evaluates one window and writes the bounded command to `command_out`. Returns an
`ArgusErrorCode`.

### `argus_envelope_get_state`

```c
int32_t argus_envelope_get_state(ArgusEnvelopeHandle handle, int32_t* state_out);
```

Writes the current `ArgusEnvelopeState`. Returns an `ArgusErrorCode`.

### `argus_envelope_get_low_streak`

```c
int32_t argus_envelope_get_low_streak(ArgusEnvelopeHandle handle, uint32_t* streak_out);
```

Writes the consecutive below-`t_low` window count. Returns an `ArgusErrorCode`.

## 6. Python `argus.abi` mirrors

The `argus.abi` module mirrors the header as ctypes structures (`ArgusSafetyConfigC`,
`ArgusPredictionC`, `ArgusSignalQualityC`, `ArgusActuatorCommandC`), enums
(`ArgusErrorCode`, `ArgusEnvelopeState`), the opaque handle alias `ArgusEnvelopeHandle`,
`CFUNCTYPE` signatures for each function, and `load_library()`.

## 7. Evidence boundary

The C ABI exposes the same safety-envelope logic as the Python API. It does not establish
physical timing, power, or certification. Native library builds are a v0.8.0 deliverable;
the current release ships the Python wheel and the sources for the wrappers.
