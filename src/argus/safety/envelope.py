"""Confidence-Coupled Safety Envelope and Signal Quality Gate.

Core research component of Atlas. The envelope sits between an intent
inference engine and a physical actuator and enforces confidence-coupled
kinematic bounds in real time.

Decision pipeline per window:
    raw EMG window -> SignalQualityGate -> reliability R in [0, 1]
    inference engine -> intent I, confidence C in [0, 1]
    C_eff = C * R
    C_eff >= T_high            -> NOMINAL:    full actuator authority
    T_low <= C_eff < T_high    -> DEGRADED:   scaled torque and velocity
    C_eff < T_low (persistent) -> SAFE_HALT:  zero velocity, hold position
    always                     -> IndependentHardwareSupervisor clips to
                                  absolute hard limits and sets veto flag

The SAFE_HALT state is latched after ``persistence_windows`` consecutive
below-threshold windows and requires a full return to T_high to exit.
The initial state after construction or reset is SAFE_HALT (fail-safe).
No randomness is used; identical inputs always produce identical outputs.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class SafetyConfig:
    """Safety-envelope threshold and scaling parameters.

    Attributes:
        t_high: Effective-confidence threshold above which NOMINAL is entered.
        t_low: Threshold below which confidence is considered degraded.
        degraded_velocity_scale: Velocity scaling factor in DEGRADED state.
        degraded_force_scale: Torque/force scaling factor in DEGRADED state.
        hard_max_torque_nm: Absolute torque bound enforced by the supervisor.
        hard_max_velocity_rad_s: Absolute velocity bound enforced by the supervisor.
        persistence_windows: Consecutive below-T_low windows needed for SAFE_HALT.
    """

    t_high: float = 0.75
    t_low: float = 0.45
    degraded_velocity_scale: float = 0.5
    degraded_force_scale: float = 0.4
    hard_max_torque_nm: float = 40.0
    hard_max_velocity_rad_s: float = 6.0
    persistence_windows: int = 3

    def __post_init__(self) -> None:
        if not 0.0 < self.t_low < self.t_high < 1.0:
            raise ValueError(
                f"need 0 < t_low < t_high < 1, got t_low={self.t_low}, t_high={self.t_high}"
            )
        if not 0.0 < self.degraded_force_scale <= 1.0:
            raise ValueError("degraded_force_scale must be in (0, 1]")
        if not 0.0 < self.degraded_velocity_scale <= 1.0:
            raise ValueError("degraded_velocity_scale must be in (0, 1]")
        if self.hard_max_torque_nm <= 0 or self.hard_max_velocity_rad_s <= 0:
            raise ValueError("hard limits must be positive")
        if self.persistence_windows < 1:
            raise ValueError("persistence_windows must be >= 1")


@dataclass(frozen=True)
class Prediction:
    """One inference result consumed by the safety envelope.

    Attributes:
        intent: Declared intent class label (must match the active profile).
        confidence: Classifier posterior probability in [0, 1].
    """

    intent: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} outside [0, 1]")


class EnvelopeState(enum.Enum):
    """Safety-envelope operating state."""

    NOMINAL = "nominal"
    DEGRADED = "degraded"
    SAFE_HALT = "safe_halt"


@dataclass(frozen=True)
class SignalQuality:
    """Output of the Signal Quality Gate for one window.

    Attributes:
        reliability: Signal reliability R in [0, 1]. Multiplied with
            classifier confidence to produce C_eff.
        flatline_channels: Indices of channels below the flatline threshold.
        artifact_detected: True if motion artifact common-mode power is
            dominant across channels.
    """

    reliability: float
    flatline_channels: tuple[int, ...]
    artifact_detected: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.reliability <= 1.0:
            raise ValueError(f"reliability {self.reliability} outside [0, 1]")


class SignalQualityGate:
    """Estimates signal reliability R from a raw EMG sensor window.

    Three multiplicative penalty checks:
    1. Flatline / contact loss: channel std below ``flatline_std_uv``.
       Each dead channel reduces reliability by 25%.
    2. Clipping / saturation: > 1% of samples within 2% of full scale.
       Reliability multiplied by 0.6.
    3. Motion artifact: dominant common-mode power across channels
       (common-mode ratio > 2.5x). Reliability multiplied by 0.3.

    Args:
        flatline_std_uv: Minimum channel standard deviation (microvolts).
        clip_ratio: Fraction of full-scale range used for clip detection.
    """

    def __init__(self, flatline_std_uv: float = 5.0, clip_ratio: float = 0.98) -> None:
        if flatline_std_uv <= 0:
            raise ValueError("flatline_std_uv must be positive")
        if not 0.0 < clip_ratio < 1.0:
            raise ValueError("clip_ratio must be in (0, 1)")
        self._flatline_std_uv = flatline_std_uv
        self._clip_ratio = clip_ratio

    def assess(self, emg_block: NDArray[np.float64]) -> SignalQuality:
        """Assess one EMG window and return a SignalQuality record.

        Args:
            emg_block: 2-D array of shape (n_samples, n_channels). Minimum
                2 samples required.

        Returns:
            SignalQuality with reliability in [0, 1] and diagnostic flags.

        Raises:
            ValueError: If emg_block has unexpected dimensions.
        """
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
            # Each dead channel removes 25% of remaining reliability.
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


@dataclass(frozen=True)
class ActuatorCommand:
    """Bounded actuator command emitted for one decision window.

    Attributes:
        intent: Intent class that produced this command.
        torque_nm: Commanded torque in Newton-metres (scaled or zeroed by state).
        velocity_rad_s: Commanded velocity in rad/s (scaled or zeroed by state).
        envelope_state: Envelope state that produced this command.
        effective_confidence: C_eff = confidence * reliability, rounded to 6dp.
        vetoed_by_supervisor: True if the hard-limit supervisor clipped this command.
    """

    intent: str
    torque_nm: float
    velocity_rad_s: float
    envelope_state: EnvelopeState
    effective_confidence: float
    vetoed_by_supervisor: bool


# Default nominal torque/velocity requests for the built-in intent classes.
# External callers should use evaluate_with_request() to supply their own limits.
_NOMINAL_REQUEST: dict[str, tuple[float, float]] = {
    "rest": (0.0, 0.0),
    "knee_flexion": (25.0, 3.0),
    "knee_extension": (25.0, 3.0),
}


class ConfidenceCoupledSafetyEnvelope:
    """Maps (intent, confidence, signal quality) to a bounded actuator command.

    State machine with SAFE_HALT persistence: the envelope enters SAFE_HALT
    only after ``persistence_windows`` consecutive windows below T_low,
    preventing single-window noise from freezing the actuator. Recovery to
    NOMINAL requires one window at or above T_high.

    The envelope starts in SAFE_HALT (fail-safe) and must receive a
    high-confidence window to transition to NOMINAL or DEGRADED. This is
    intentional: a controller that has just been powered on or reset should
    not immediately issue motion commands.

    Args:
        cfg: Safety-envelope configuration.
    """

    def __init__(self, cfg: SafetyConfig) -> None:
        self._cfg = cfg
        self._low_streak = 0
        self._state = EnvelopeState.SAFE_HALT

    @property
    def state(self) -> EnvelopeState:
        """Current envelope state."""
        return self._state

    @property
    def low_streak(self) -> int:
        """Number of consecutive below-T_low windows since last reset."""
        return self._low_streak

    def reset(self) -> None:
        """Reset to SAFE_HALT state. Required between replayed segments."""
        self._low_streak = 0
        self._state = EnvelopeState.SAFE_HALT

    def evaluate(self, prediction: Prediction, quality: SignalQuality) -> ActuatorCommand:
        """Evaluate one window using built-in nominal request values.

        Use this when the intent class maps to a known nominal torque/velocity.
        For custom actuator limits use ``evaluate_with_request``.

        Args:
            prediction: Inference result with intent label and confidence.
            quality: Signal quality assessment for the same window.

        Returns:
            ActuatorCommand bounded by the current envelope state and hard limits.
        """
        base_torque, base_velocity = _NOMINAL_REQUEST.get(prediction.intent, (0.0, 0.0))
        return self._step(
            prediction,
            quality,
            base_torque,
            base_velocity,
            known_intent=prediction.intent in _NOMINAL_REQUEST,
        )

    def evaluate_with_request(
        self,
        prediction: Prediction,
        quality: SignalQuality,
        requested_torque_nm: float,
        requested_velocity_rad_s: float,
    ) -> ActuatorCommand:
        """Evaluate one window with caller-supplied nominal request values.

        Use this when working with profiles that define their own actuator
        limits rather than the built-in ``_NOMINAL_REQUEST`` table.

        Args:
            prediction: Inference result.
            quality: Signal quality for this window.
            requested_torque_nm: Nominal torque to apply in NOMINAL state.
            requested_velocity_rad_s: Nominal velocity to apply in NOMINAL state.

        Returns:
            ActuatorCommand bounded by the current state and hard limits.

        Raises:
            ValueError: If requested values are not finite.
        """
        if not math.isfinite(requested_torque_nm) or not math.isfinite(requested_velocity_rad_s):
            raise ValueError("requested torque and velocity must be finite")
        return self._step(
            prediction,
            quality,
            requested_torque_nm,
            requested_velocity_rad_s,
            known_intent=True,
        )

    def _step(
        self,
        prediction: Prediction,
        quality: SignalQuality,
        requested_torque_nm: float,
        requested_velocity_rad_s: float,
        known_intent: bool,
    ) -> ActuatorCommand:
        """Core state-machine step. Single code path for both public methods."""
        c_eff = round(prediction.confidence * quality.reliability, 6)

        # Update streak counter before computing new state.
        if c_eff < self._cfg.t_low:
            self._low_streak += 1
        else:
            self._low_streak = 0

        # State transitions.
        # SAFE_HALT is entered after persistence_windows consecutive low-C_eff
        # windows. Recovery requires c_eff >= T_high. Mid-band c_eff (T_low to
        # T_high) results in DEGRADED from any prior state including SAFE_HALT.
        if self._low_streak >= self._cfg.persistence_windows:
            self._state = EnvelopeState.SAFE_HALT
        elif c_eff >= self._cfg.t_high:
            self._state = EnvelopeState.NOMINAL
        else:
            # c_eff < T_high and streak < persistence: degrade.
            # Covers both early-streak (c_eff < T_low) and mid-band (T_low <= c_eff < T_high).
            # A single mid-band window can exit SAFE_HALT to DEGRADED but not to NOMINAL.
            self._state = EnvelopeState.DEGRADED

        # Unknown intent always fails safe regardless of confidence.
        if not known_intent:
            self._state = EnvelopeState.SAFE_HALT

        # Compute output torque and velocity based on current state.
        if self._state is EnvelopeState.NOMINAL:
            torque, velocity = requested_torque_nm, requested_velocity_rad_s
        elif self._state is EnvelopeState.DEGRADED:
            torque = requested_torque_nm * self._cfg.degraded_force_scale
            velocity = requested_velocity_rad_s * self._cfg.degraded_velocity_scale
        else:  # SAFE_HALT
            torque, velocity = 0.0, 0.0

        command = ActuatorCommand(
            intent=prediction.intent,
            torque_nm=torque,
            velocity_rad_s=velocity,
            envelope_state=self._state,
            effective_confidence=c_eff,
            vetoed_by_supervisor=False,
        )
        return IndependentHardwareSupervisor(self._cfg).supervise(command)


class IndependentHardwareSupervisor:
    """Final veto layer: absolute kinematic bounds, never relaxable.

    Models the MCU/FPGA-resident supervisor that clips any command -
    including a NOMINAL one - that exceeds the declared hard limits.
    The veto flag is set whenever clipping occurs.

    Args:
        cfg: Safety configuration supplying the hard-limit values.
    """

    def __init__(self, cfg: SafetyConfig) -> None:
        self._cfg = cfg

    def supervise(self, cmd: ActuatorCommand) -> ActuatorCommand:
        """Clip cmd to hard limits and return a new command.

        If no clipping is needed the original command object is returned
        unchanged (no allocation).

        Args:
            cmd: Command to supervise.

        Returns:
            Command with torque and velocity clipped to hard limits.
            vetoed_by_supervisor is True if any clipping occurred.
        """
        bounded_torque = float(
            np.clip(cmd.torque_nm, -self._cfg.hard_max_torque_nm, self._cfg.hard_max_torque_nm)
        )
        bounded_velocity = float(
            np.clip(
                cmd.velocity_rad_s,
                -self._cfg.hard_max_velocity_rad_s,
                self._cfg.hard_max_velocity_rad_s,
            )
        )
        vetoed = (bounded_torque != cmd.torque_nm) or (bounded_velocity != cmd.velocity_rad_s)
        if not vetoed:
            return cmd
        return ActuatorCommand(
            intent=cmd.intent,
            torque_nm=bounded_torque,
            velocity_rad_s=bounded_velocity,
            envelope_state=cmd.envelope_state,
            effective_confidence=cmd.effective_confidence,
            vetoed_by_supervisor=True,
        )
