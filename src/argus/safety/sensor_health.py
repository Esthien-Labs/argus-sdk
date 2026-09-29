"""Sensor health and out-of-distribution gating for the safety envelope.

ISO/PAS 8800 names out-of-distribution detection as an architectural mitigation
for learned functions, alongside model monitors and verified fallbacks. This
module provides that mitigation as a declared, deterministic, explainable gate:

  - signal validity: flatline and saturation checks per channel;
  - distribution check: per-channel deviation from a declared reference window.

The gate is deliberately simple and inspectable rather than learned. A safety
mitigation must be checkable by a third party, so the reference statistics and
thresholds are declared, not fitted silently.

The result plugs into the existing safety envelope through
``SensorHealth.as_signal_quality()``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from .envelope import SignalQuality

__all__ = ["SensorHealth", "SensorHealthGate"]


@dataclass(frozen=True)
class SensorHealth:
    """Outcome of one sensor-health assessment.

    Attributes:
        reliability: Combined reliability in [0, 1]. Multiplied with classifier
            confidence to produce C_eff.
        flatline_channels: Indices of channels below the flatline threshold.
        artifact_detected: True if common-mode power dominates across channels.
        out_of_distribution: True if the out-of-distribution channel fraction
            reached the declared threshold.
        ood_score: Fraction of channels outside the declared reference
            distribution, in [0, 1].
        flags: Named check outcomes, for the evidence record.
    """

    reliability: float
    flatline_channels: tuple[int, ...]
    artifact_detected: bool
    out_of_distribution: bool
    ood_score: float
    flags: tuple[str, ...] = field(default=())

    def as_signal_quality(self) -> SignalQuality:
        """Return the equivalent SignalQuality for the existing envelope API."""
        return SignalQuality(
            reliability=self.reliability,
            flatline_channels=self.flatline_channels,
            artifact_detected=self.artifact_detected,
        )


class SensorHealthGate:
    """Declares a sensor's operating envelope and assesses windows against it.

    Three multiplicative penalties, each independently declared and checkable:

    1. Flatline or contact loss: a channel standard deviation below
       ``flatline_std`` removes 25% of the remaining reliability.
    2. Saturation: more than 1% of samples within ``1 - clip_ratio`` of full
       scale multiplies reliability by 0.6.
    3. Out-of-distribution input: the fraction of channels whose normalised
       deviation from the declared reference exceeds ``ood_z_threshold``
       multiplies reliability by ``1 - ood_score``.

    Args:
        flatline_std: Minimum channel standard deviation in sensor units.
        clip_ratio: Fraction of full-scale range used for clip detection.
        ood_z_threshold: Normalised deviation per channel above which a channel
            is out of distribution.
        ood_channel_fraction: Fraction of out-of-distribution channels at which
            the window is declared out of distribution.
        artifact_common_mode_ratio: Common-mode power ratio above which a motion
            artifact is declared.
        flatline_policy: ``penalise`` removes 25% of the remaining reliability
            per flatlined channel. ``fail_closed`` treats any flatlined channel
            as a loss of the sensor signal and drives reliability to zero. A
            safety-critical profile declares ``fail_closed``.
    """

    def __init__(
        self,
        *,
        flatline_std: float = 5.0,
        clip_ratio: float = 0.98,
        ood_z_threshold: float = 4.0,
        ood_channel_fraction: float = 0.25,
        artifact_common_mode_ratio: float = 2.5,
        flatline_policy: str = "penalise",
    ) -> None:
        if flatline_std <= 0:
            raise ValueError("flatline_std must be positive")
        if not 0.0 < clip_ratio < 1.0:
            raise ValueError("clip_ratio must be in (0, 1)")
        if ood_z_threshold <= 0:
            raise ValueError("ood_z_threshold must be positive")
        if not 0.0 < ood_channel_fraction <= 1.0:
            raise ValueError("ood_channel_fraction must be in (0, 1]")
        if artifact_common_mode_ratio <= 0:
            raise ValueError("artifact_common_mode_ratio must be positive")
        if flatline_policy not in {"penalise", "fail_closed"}:
            raise ValueError("flatline_policy must be 'penalise' or 'fail_closed'")
        self._flatline_std = float(flatline_std)
        self._clip_ratio = float(clip_ratio)
        self._ood_z_threshold = float(ood_z_threshold)
        self._ood_channel_fraction = float(ood_channel_fraction)
        self._artifact_ratio = float(artifact_common_mode_ratio)
        self._flatline_policy = flatline_policy
        self._reference_mean: NDArray[np.float64] | None = None
        self._reference_std: NDArray[np.float64] | None = None

    def declare_reference(self, reference: NDArray[np.float64]) -> None:
        """Declare the reference distribution from a reference window set.

        Args:
            reference: 2-D array of shape (n_samples, n_channels) drawn from the
                sensor's declared operating envelope.

        Raises:
            ValueError: If the reference has unexpected shape or a channel has
                no variance.
        """
        if reference.ndim != 2 or reference.shape[0] < 2 or reference.shape[1] < 1:
            raise ValueError(f"reference shape {reference.shape} not declarable")
        mean = reference.mean(axis=0)
        std = reference.std(axis=0)
        if float(np.min(std)) <= 0.0:
            raise ValueError("reference channels must have non-zero variance")
        self._reference_mean = np.asarray(mean, dtype=np.float64)
        self._reference_std = np.asarray(std, dtype=np.float64)

    def assess(self, window: NDArray[np.float64]) -> SensorHealth:
        """Assess one sensor window.

        Args:
            window: 2-D array of shape (n_samples, n_channels), minimum 2 samples.

        Returns:
            SensorHealth with reliability in [0, 1] and named check outcomes.

        Raises:
            ValueError: If the window has unexpected shape or no reference has
                been declared.
        """
        if window.ndim != 2 or window.shape[0] < 2:
            raise ValueError(f"window shape {window.shape} not assessable")
        if self._reference_mean is None or self._reference_std is None:
            raise ValueError("declare_reference must be called before assess")

        n_channels = window.shape[1]
        if window.shape[1] != self._reference_mean.shape[0]:
            raise ValueError(
                f"window has {n_channels} channels, reference declared "
                f"{self._reference_mean.shape[0]}"
            )

        flags: list[str] = []

        flat = [
            ch for ch in range(n_channels)
            if float(np.std(window[:, ch])) < self._flatline_std
        ]
        if flat:
            flags.append("flatline")
        fail_closed = bool(flat) and self._flatline_policy == "fail_closed"

        full_scale = float(np.max(np.abs(window))) + 1e-12
        clipped = float(np.mean(np.abs(window) > self._clip_ratio * full_scale))
        if clipped > 0.01:
            flags.append("saturation")

        demeaned = window - window.mean(axis=0)
        total_power = float(np.mean(demeaned**2)) + 1e-12
        common_mode = demeaned.mean(axis=1)
        common_mode_ratio = float(np.mean(common_mode**2) / (total_power / n_channels))
        artifact = common_mode_ratio > self._artifact_ratio
        if artifact:
            flags.append("artifact")

        deviation = np.abs(window.mean(axis=0) - self._reference_mean) / self._reference_std
        ood_channels = int(np.count_nonzero(deviation > self._ood_z_threshold))
        ood_score = round(ood_channels / n_channels, 6)
        out_of_distribution = ood_score >= self._ood_channel_fraction
        if out_of_distribution:
            flags.append("out_of_distribution")

        reliability = 1.0
        if fail_closed:
            reliability = 0.0
        else:
            if flat:
                reliability *= max(0.0, 1.0 - 0.25 * len(flat))
            if clipped > 0.01:
                reliability *= 0.6
            if artifact:
                reliability *= 0.3
            if out_of_distribution:
                reliability *= max(0.0, 1.0 - ood_score)

        if not math.isfinite(reliability):
            raise ValueError("reliability computation did not stay finite")

        return SensorHealth(
            reliability=round(reliability, 6),
            flatline_channels=tuple(flat),
            artifact_detected=artifact,
            out_of_distribution=out_of_distribution,
            ood_score=ood_score,
            flags=tuple(flags),
        )
