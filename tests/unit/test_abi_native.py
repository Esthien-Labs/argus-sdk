"""Round-trip tests for the native C ABI safety-envelope library.

The test builds the native library when a C compiler is available, then checks
that a decision sequence matches the pure-Python envelope exactly. If the
library is absent and cannot be built, the test is skipped.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

import pytest

from argus.safety import (
    ConfidenceCoupledSafetyEnvelope,
    EnvelopeState,
    Prediction,
    SafetyConfig,
    SignalQuality,
)

ROOT = Path(__file__).resolve().parents[2]
ABI_DIR = ROOT / "src" / "argus" / "abi"


def _library_path() -> Path:
    if sys.platform == "win32":
        name = "argus.dll"
    elif sys.platform == "darwin":
        name = "libargus.dylib"
    else:
        name = "libargus.so"
    return ABI_DIR / name


def _ensure_library() -> Path:
    path = _library_path()
    if path.is_file():
        return path
    script = ROOT / "scripts" / "build_native_library.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not path.is_file():
        pytest.skip(f"native library unavailable: {result.stderr.strip()}")
    return path


class _SafetyConfigC(ctypes.Structure):
    _fields_ = [
        ("t_high", ctypes.c_double),
        ("t_low", ctypes.c_double),
        ("degraded_velocity_scale", ctypes.c_double),
        ("degraded_force_scale", ctypes.c_double),
        ("hard_max_torque_nm", ctypes.c_double),
        ("hard_max_velocity_rad_s", ctypes.c_double),
        ("persistence_windows", ctypes.c_uint32),
    ]


class _PredictionC(ctypes.Structure):
    _fields_ = [("intent", ctypes.c_char_p), ("confidence", ctypes.c_double)]


class _SignalQualityC(ctypes.Structure):
    _fields_ = [
        ("reliability", ctypes.c_double),
        ("flatline_channels", ctypes.POINTER(ctypes.c_uint32)),
        ("flatline_count", ctypes.c_size_t),
        ("artifact_detected", ctypes.c_int32),
    ]


class _ActuatorCommandC(ctypes.Structure):
    _fields_ = [
        ("intent", ctypes.c_char_p),
        ("torque_nm", ctypes.c_double),
        ("velocity_rad_s", ctypes.c_double),
        ("envelope_state", ctypes.c_int32),
        ("effective_confidence", ctypes.c_double),
        ("vetoed_by_supervisor", ctypes.c_int32),
    ]


def _load():
    path = _ensure_library()
    lib = ctypes.CDLL(str(path))
    lib.argus_abi_version.restype = ctypes.c_int32
    lib.argus_envelope_create.restype = ctypes.c_void_p
    lib.argus_envelope_create.argtypes = [ctypes.POINTER(_SafetyConfigC)]
    lib.argus_envelope_destroy.argtypes = [ctypes.c_void_p]
    lib.argus_envelope_evaluate.restype = ctypes.c_int32
    lib.argus_envelope_evaluate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PredictionC),
        ctypes.POINTER(_SignalQualityC),
        ctypes.POINTER(_ActuatorCommandC),
    ]
    lib.argus_envelope_get_low_streak.restype = ctypes.c_int32
    lib.argus_envelope_get_low_streak.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    return lib


def _state_from_int(value: int) -> EnvelopeState:
    return {
        0: EnvelopeState.NOMINAL,
        1: EnvelopeState.DEGRADED,
        2: EnvelopeState.SAFE_HALT,
    }[value]


def test_abi_version_is_one() -> None:
    lib = _load()
    assert lib.argus_abi_version() == 1


def test_create_rejects_invalid_config() -> None:
    lib = _load()
    invalid = _SafetyConfigC(0.4, 0.6, 0.5, 0.4, 40.0, 6.0, 3)  # t_low > t_high
    assert lib.argus_envelope_create(ctypes.byref(invalid)) is None


@pytest.mark.parametrize(
    "cfg",
    [
        SafetyConfig(),
        SafetyConfig(t_high=0.8, t_low=0.5, persistence_windows=2),
        SafetyConfig(hard_max_torque_nm=10.0),  # forces a supervisor veto on knee_flexion
    ],
)
def test_native_matches_python(cfg: SafetyConfig) -> None:
    lib = _load()

    config_c = _SafetyConfigC(
        cfg.t_high,
        cfg.t_low,
        cfg.degraded_velocity_scale,
        cfg.degraded_force_scale,
        cfg.hard_max_torque_nm,
        cfg.hard_max_velocity_rad_s,
        cfg.persistence_windows,
    )
    handle = lib.argus_envelope_create(ctypes.byref(config_c))
    assert handle

    reference = ConfidenceCoupledSafetyEnvelope(cfg)
    sequence = [
        ("knee_flexion", 0.92, 0.95),
        ("knee_flexion", 0.60, 0.90),
        ("unknown_intent", 0.99, 1.00),
        ("rest", 0.80, 0.80),
        ("knee_extension", 0.30, 0.20),
        ("knee_extension", 0.30, 0.20),
        ("knee_extension", 0.30, 0.20),
        ("knee_extension", 0.30, 0.20),
    ]

    try:
        for intent, confidence, reliability in sequence:
            prediction = _PredictionC(intent.encode("utf-8"), confidence)
            quality = _SignalQualityC(reliability, None, 0, 0)
            command = _ActuatorCommandC()
            rc = lib.argus_envelope_evaluate(
                handle, ctypes.byref(prediction), ctypes.byref(quality), ctypes.byref(command)
            )
            assert rc == 0

            expected = reference.evaluate(
                Prediction(intent=intent, confidence=confidence),
                SignalQuality(reliability=reliability, flatline_channels=(), artifact_detected=False),
            )

            assert command.torque_nm == pytest.approx(expected.torque_nm, abs=1e-9)
            assert command.velocity_rad_s == pytest.approx(expected.velocity_rad_s, abs=1e-9)
            assert _state_from_int(command.envelope_state) is expected.envelope_state
            assert command.effective_confidence == pytest.approx(expected.effective_confidence, abs=1e-9)
            assert bool(command.vetoed_by_supervisor) == expected.vetoed_by_supervisor

        streak = ctypes.c_uint32(0)
        assert lib.argus_envelope_get_low_streak(handle, ctypes.byref(streak)) == 0
        assert streak.value == reference.low_streak
    finally:
        lib.argus_envelope_destroy(handle)
