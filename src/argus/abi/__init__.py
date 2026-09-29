"""C ABI definitions for Argus SDK safety-critical components.

This module defines the C-compatible function signatures and data structures
that can be called from any language via FFI. The actual implementation is
compiled from Cython to native code.

Design principles:
- All functions are pure C - no C++ exceptions, no RTTI
- All memory is caller-allocated - no hidden allocations
- All state is opaque - implementation details never cross the ABI boundary
- Error codes are integers - no exceptions across the boundary
"""

from __future__ import annotations

import ctypes
from ctypes import c_char_p, c_double, c_int32, c_size_t, c_uint32, c_void_p, Structure, POINTER
from enum import IntEnum
from pathlib import Path


class ArgusEnvelopeState(IntEnum):
    """Safety envelope operating state - mirrors EnvelopeState in envelope.py."""

    NOMINAL = 0
    DEGRADED = 1
    SAFE_HALT = 2


class ArgusErrorCode(IntEnum):
    """Error codes returned by C ABI functions."""

    OK = 0
    INVALID_ARGUMENT = 1
    INVALID_STATE = 2
    BUFFER_TOO_SMALL = 3
    NOT_INITIALIZED = 4
    INTERNAL_ERROR = 5


class ArgusSafetyConfigC(Structure):
    """C-compatible SafetyConfig structure."""

    _fields_ = [
        ("t_high", c_double),
        ("t_low", c_double),
        ("degraded_velocity_scale", c_double),
        ("degraded_force_scale", c_double),
        ("hard_max_torque_nm", c_double),
        ("hard_max_velocity_rad_s", c_double),
        ("persistence_windows", c_uint32),
    ]


class ArgusPredictionC(Structure):
    """C-compatible Prediction structure."""

    _fields_ = [
        ("intent", c_char_p),
        ("confidence", c_double),
    ]


class ArgusSignalQualityC(Structure):
    """C-compatible SignalQuality structure."""

    _fields_ = [
        ("reliability", c_double),
        ("flatline_channels", POINTER(c_uint32)),
        ("flatline_count", c_size_t),
        ("artifact_detected", c_int32),  # boolean as int32
    ]


class ArgusActuatorCommandC(Structure):
    """C-compatible ActuatorCommand structure."""

    _fields_ = [
        ("intent", c_char_p),
        ("torque_nm", c_double),
        ("velocity_rad_s", c_double),
        ("envelope_state", c_int32),
        ("effective_confidence", c_double),
        ("vetoed_by_supervisor", c_int32),  # boolean as int32
    ]


# Opaque handle for the safety envelope instance
ArgusEnvelopeHandle = c_void_p


# Function signatures for the C ABI
# These are implemented in the Cython-compiled native library

# argus_envelope_create(config: ArgusSafetyConfigC*) -> ArgusEnvelopeHandle
# argus_envelope_destroy(handle: ArgusEnvelopeHandle) -> void
# argus_envelope_reset(handle: ArgusEnvelopeHandle) -> ArgusErrorCode
# argus_envelope_evaluate(handle: ArgusEnvelopeHandle, prediction: ArgusPredictionC*, quality: ArgusSignalQualityC*, command_out: ArgusActuatorCommandC*) -> ArgusErrorCode
# argus_envelope_get_state(handle: ArgusEnvelopeHandle, state_out: c_int32*) -> ArgusErrorCode
# argus_envelope_get_low_streak(handle: ArgusEnvelopeHandle, streak_out: c_uint32*) -> ArgusErrorCode


def load_library() -> ctypes.CDLL:
    """Load the compiled Argus native library.

    Returns:
        Loaded CDLL object.

    Raises:
        OSError: If the library cannot be found or loaded.
    """
    import platform
    import sys

    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        lib_name = "argus.dll"
    elif system == "Darwin":
        lib_name = "libargus.dylib"
    else:
        lib_name = "libargus.so"

    # Look in the package directory first
    package_dir = Path(__file__).parent
    lib_path = package_dir / lib_name

    if lib_path.exists():
        return ctypes.CDLL(str(lib_path))

    # Fall back to system library path
    try:
        return ctypes.CDLL(lib_name)
    except OSError as e:
        raise OSError(
            f"Argus native library not found. Expected at {lib_path} or in system library path. "
            f"Error: {e}"
        ) from e


# Type definitions for the C functions
ArgusEnvelopeCreateFunc = ctypes.CFUNCTYPE(ArgusEnvelopeHandle, POINTER(ArgusSafetyConfigC))
ArgusEnvelopeDestroyFunc = ctypes.CFUNCTYPE(None, ArgusEnvelopeHandle)
ArgusEnvelopeResetFunc = ctypes.CFUNCTYPE(c_int32, ArgusEnvelopeHandle)
ArgusEnvelopeEvaluateFunc = ctypes.CFUNCTYPE(
    c_int32,
    ArgusEnvelopeHandle,
    POINTER(ArgusPredictionC),
    POINTER(ArgusSignalQualityC),
    POINTER(ArgusActuatorCommandC),
)
ArgusEnvelopeGetStateFunc = ctypes.CFUNCTYPE(c_int32, ArgusEnvelopeHandle, POINTER(c_int32))
ArgusEnvelopeGetLowStreakFunc = ctypes.CFUNCTYPE(c_int32, ArgusEnvelopeHandle, POINTER(c_uint32))
