"""Python wrapper for the Argus C ABI safety envelope.

This provides a clean Python API that internally uses the compiled C extension.
It maintains API compatibility with the pure-Python implementation.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional

from . import (
    ArgusActuatorCommandC,
    ArgusEnvelopeState,
    ArgusErrorCode,
    ArgusPredictionC,
    ArgusSafetyConfigC,
    ArgusSignalQualityC,
    load_library,
)


class EnvelopeState(IntEnum):
    """Safety-envelope operating state."""

    NOMINAL = 0
    DEGRADED = 1
    SAFE_HALT = 2


@dataclass(frozen=True)
class SafetyConfig:
    """Safety-envelope threshold and scaling parameters."""

    t_high: float = 0.75
    t_low: float = 0.45
    degraded_velocity_scale: float = 0.5
    degraded_force_scale: float = 0.4
    hard_max_torque_nm: float = 40.0
    hard_max_velocity_rad_s: float = 6.0
    persistence_windows: int = 3


@dataclass(frozen=True)
class ActuatorCommand:
    """Bounded actuator command emitted for one decision window."""

    intent: str
    torque_nm: float
    velocity_rad_s: float
    envelope_state: EnvelopeState
    effective_confidence: float
    vetoed_by_supervisor: bool


class ConfidenceCoupledSafetyEnvelope:
    """Maps (intent, confidence, signal quality) to a bounded actuator command.

    Native-backed: every call goes through the compiled Argus C ABI library.
    The decision logic is identical to the pure-Python implementation in
    ``argus.safety.envelope``; the two agree bit for bit (see
    ``tests/unit/test_abi_native.py``).

    The C ABI carries no explicit actuator-request channel, so
    ``evaluate`` uses the built-in nominal request table. Use the pure-Python
    ``argus.safety`` envelope when caller-supplied request values are required.
    """

    def __init__(self, cfg: SafetyConfig) -> None:
        self._cfg = cfg
        self._lib = load_library()
        self._bind_signatures()
        native_cfg = ArgusSafetyConfigC(
            cfg.t_high,
            cfg.t_low,
            cfg.degraded_velocity_scale,
            cfg.degraded_force_scale,
            cfg.hard_max_torque_nm,
            cfg.hard_max_velocity_rad_s,
            cfg.persistence_windows,
        )
        handle = self._lib.argus_envelope_create(ctypes.byref(native_cfg))
        if not handle:
            raise ValueError("native envelope rejected the configuration")
        self._handle = handle

    def _bind_signatures(self) -> None:
        lib = self._lib
        lib.argus_envelope_create.restype = ctypes.c_void_p
        lib.argus_envelope_create.argtypes = [ctypes.POINTER(ArgusSafetyConfigC)]
        lib.argus_envelope_destroy.restype = None
        lib.argus_envelope_destroy.argtypes = [ctypes.c_void_p]
        lib.argus_envelope_reset.restype = ctypes.c_int32
        lib.argus_envelope_reset.argtypes = [ctypes.c_void_p]
        lib.argus_envelope_evaluate.restype = ctypes.c_int32
        lib.argus_envelope_evaluate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ArgusPredictionC),
            ctypes.POINTER(ArgusSignalQualityC),
            ctypes.POINTER(ArgusActuatorCommandC),
        ]
        lib.argus_envelope_get_state.restype = ctypes.c_int32
        lib.argus_envelope_get_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
        lib.argus_envelope_get_low_streak.restype = ctypes.c_int32
        lib.argus_envelope_get_low_streak.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]

    @property
    def state(self) -> EnvelopeState:
        """Current envelope state, read from the native instance."""
        value = ctypes.c_int32(0)
        rc = self._lib.argus_envelope_get_state(self._handle, ctypes.byref(value))
        if rc != ArgusErrorCode.OK:
            raise OSError(f"argus_envelope_get_state returned {rc}")
        return EnvelopeState(value.value)

    @property
    def low_streak(self) -> int:
        """Number of consecutive below-T_low windows since last reset."""
        value = ctypes.c_uint32(0)
        rc = self._lib.argus_envelope_get_low_streak(self._handle, ctypes.byref(value))
        if rc != ArgusErrorCode.OK:
            raise OSError(f"argus_envelope_get_low_streak returned {rc}")
        return int(value.value)

    def reset(self) -> None:
        """Reset to SAFE_HALT state."""
        rc = self._lib.argus_envelope_reset(self._handle)
        if rc != ArgusErrorCode.OK:
            raise OSError(f"argus_envelope_reset returned {rc}")

    def evaluate(self, prediction: "Prediction", quality: "SignalQuality") -> ActuatorCommand:
        """Evaluate one window using the built-in nominal request table."""
        native_prediction = ArgusPredictionC(
            prediction.intent.encode("utf-8"),
            prediction.confidence,
        )
        native_quality = ArgusSignalQualityC(quality.reliability, None, 0, 0)
        command = ArgusActuatorCommandC()
        rc = self._lib.argus_envelope_evaluate(
            self._handle,
            ctypes.byref(native_prediction),
            ctypes.byref(native_quality),
            ctypes.byref(command),
        )
        if rc != ArgusErrorCode.OK:
            raise OSError(f"argus_envelope_evaluate returned {rc}")
        return ActuatorCommand(
            intent=prediction.intent,
            torque_nm=command.torque_nm,
            velocity_rad_s=command.velocity_rad_s,
            envelope_state=EnvelopeState(command.envelope_state),
            effective_confidence=command.effective_confidence,
            vetoed_by_supervisor=bool(command.vetoed_by_supervisor),
        )

    def close(self) -> None:
        """Release the native envelope instance."""
        if getattr(self, "_handle", None):
            self._lib.argus_envelope_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> "ConfidenceCoupledSafetyEnvelope":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


@dataclass(frozen=True)
class Prediction:
    """One inference result consumed by the safety envelope."""

    intent: str
    confidence: float


@dataclass(frozen=True)
class SignalQuality:
    """Output of the Signal Quality Gate for one window."""

    reliability: float
    flatline_channels: tuple[int, ...]
    artifact_detected: bool


class SignalQualityGate:
    """Estimates signal reliability R from a raw EMG sensor window."""

    def __init__(self, flatline_std_uv: float = 5.0, clip_ratio: float = 0.98) -> None:
        self._flatline_std_uv = flatline_std_uv
        self._clip_ratio = clip_ratio

    def assess(self, emg_block) -> SignalQuality:
        """Assess one EMG window and return a SignalQuality record."""
        import numpy as np

        if emg_block.ndim != 2 or emg_block.shape[0] < 2:
            raise ValueError(f"emg_block shape {emg_block.shape} not assessable")

        n_channels = emg_block.shape[1]
        flat: list[int] = []
        reliability = 1.0

        for ch in range(n_channels):
            std = float(np.std(emg_block[:, ch]))
            if std < self._flatline_std_uv:
                flat.append(ch)
        if flat:
            reliability *= max(0.0, 1.0 - 0.25 * len(flat))

        full_scale = float(np.max(np.abs(emg_block))) + 1e-12
        clipped = float(np.mean(np.abs(emg_block) > self._clip_ratio * full_scale))
        if clipped > 0.01:
            reliability *= 0.6

        demeaned = emg_block - emg_block.mean(axis=0)
        total_power = float(np.mean(demeaned**2)) + 1e-12
        common_mode = demeaned.mean(axis=1)
        common_mode_ratio = float(np.mean(common_mode**2) / (total_power / n_channels))
        artifact = common_mode_ratio > 2.5
        if artifact:
            reliability *= 0.3

        return SignalQuality(
            reliability=round(reliability, 6),
            flatline_channels=tuple(flat),
            artifact_detected=artifact,
        )
