"""Controller regression profile schema and validation (Stage 0B).

Defines the controller_regression_v0 profile format for the Atlas
regression evaluation product. This profile is used with:

  atlas regression-eval --profile <controller_regression_profile.json>

Profile format (controller_regression_v0):
  schema_version:    "1.0"
  profile_id:        identifier string
  producer_config:   source system (ROS2 diff drive, CAN ECU, cobot joint, proprietary SPI, custom)
  receiver_config:   target controller (safety supervisor, motion controller, actuator driver, fleet OS)
  command_limits:    max velocity/torque bounds (profile-type-specific)
  fault_corpus:      declared fault cases the evaluation must exercise
  applicable_standards: governed standards registry citations

Evidence boundary: this module validates profile schema only.
It does not run any evaluation or produce physical evidence.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .standards import validate_standards_citations


class ControllerRegressionSchemaError(ValueError):
    """Raised when a controller regression profile fails schema validation."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class InterfaceType(str, Enum):
    ROS2_DIFF_DRIVE = "ros2_diff_drive"
    CAN_BUS_TORQUE = "can_bus_torque"
    PROPRIETARY_SPI = "proprietary_spi"
    CUSTOM = "custom"


class ControllerType(str, Enum):
    SAFETY_SUPERVISOR = "safety_supervisor"
    MOTION_CONTROLLER = "motion_controller"
    ACTUATOR_DRIVER = "actuator_driver"
    FLEET_OS = "fleet_os"


class SafetyFunctionClass(str, Enum):
    SIL1 = "SIL1"
    SIL2 = "SIL2"
    SIL3 = "SIL3"
    SIL4 = "SIL4"
    PL_C = "PLc"
    PL_D = "PLd"
    PL_E = "PLe"
    ASIL_A = "ASIL_A"
    ASIL_B = "ASIL_B"
    ASIL_C = "ASIL_C"
    ASIL_D = "ASIL_D"
    CUSTOM = "custom"


class FaultKind(str, Enum):
    STALE_COMMAND = "stale_command"
    MISSING_BURST = "missing_burst"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    OUT_OF_ORDER = "out_of_order"
    CORRUPT_FRAME = "corrupt_frame"
    OUT_OF_RANGE = "out_of_range"
    NAN_INPUT = "nan_input"
    HOST_RESTART = "host_restart"
    RECONNECT = "reconnect"


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")

_SEQUENCE_ROLLOVER_VALUES = frozenset({"truncate", "wrap_65535", "monotonic_64"})
_OVERFLOW_BEHAVIOR_VALUES = frozenset({"drop_oldest", "drop_newest", "error"})
_INVALID_NUMERIC_VALUES = frozenset({"reject", "clamp", "pass_through"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(data: dict[str, Any], key: str, context: str) -> Any:
    if key not in data:
        raise ControllerRegressionSchemaError(
            f"{context}: missing required field '{key}'"
        )
    return data[key]


def _require_positive_float(data: dict[str, Any], key: str, context: str) -> float:
    val = _require(data, key, context)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise ControllerRegressionSchemaError(f"{context}.{key} must be a number")
    fval = float(val)
    if not math.isfinite(fval) or fval <= 0.0:
        raise ControllerRegressionSchemaError(f"{context}.{key} must be finite and > 0")
    return fval


def _require_positive_int(data: dict[str, Any], key: str, context: str) -> int:
    val = _require(data, key, context)
    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
        raise ControllerRegressionSchemaError(f"{context}.{key} must be a positive integer")
    return val


def _require_string(data: dict[str, Any], key: str, context: str) -> str:
    val = _require(data, key, context)
    if not isinstance(val, str) or not val:
        raise ControllerRegressionSchemaError(f"{context}.{key} must be a non-empty string")
    return val


# ---------------------------------------------------------------------------
# Nested dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SequencePolicyConfig:
    rollover: str
    stale_age_ms: float
    reset_epoch: str
    overflow_behavior: str
    invalid_behavior: str

    @classmethod
    def from_dict(cls, data: Any, context: str) -> "SequencePolicyConfig":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{context}.sequence_policy must be an object")
        rollover = _require_string(data, "sequence_rollover", context)
        if rollover not in _SEQUENCE_ROLLOVER_VALUES:
            raise ControllerRegressionSchemaError(
                f"{context}.sequence_policy.sequence_rollover must be one of "
                f"{sorted(_SEQUENCE_ROLLOVER_VALUES)}, got {rollover!r}"
            )
        stale_age_ms = _require_positive_float(data, "stale_data_age_ms", context)
        reset_epoch = _require_string(data, "reset_epoch", context)
        overflow = _require_string(data, "queue_overflow_behavior", context)
        if overflow not in _OVERFLOW_BEHAVIOR_VALUES:
            raise ControllerRegressionSchemaError(
                f"{context}.sequence_policy.queue_overflow_behavior must be one of "
                f"{sorted(_OVERFLOW_BEHAVIOR_VALUES)}, got {overflow!r}"
            )
        invalid = _require_string(data, "invalid_numeric_behavior", context)
        if invalid not in _INVALID_NUMERIC_VALUES:
            raise ControllerRegressionSchemaError(
                f"{context}.sequence_policy.invalid_numeric_behavior must be one of "
                f"{sorted(_INVALID_NUMERIC_VALUES)}, got {invalid!r}"
            )
        return cls(
            rollover=rollover,
            stale_age_ms=stale_age_ms,
            reset_epoch=reset_epoch,
            overflow_behavior=overflow,
            invalid_behavior=invalid,
        )


@dataclass(frozen=True)
class ProducerConfig:
    name: str
    interface_type: InterfaceType
    command_rate_hz: float
    sequence_policy: SequencePolicyConfig

    @classmethod
    def from_dict(cls, data: Any, context: str = "producer_config") -> "ProducerConfig":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{context} must be an object")
        name = _require_string(data, "name", context)
        itype_raw = _require_string(data, "interface_type", context)
        try:
            itype = InterfaceType(itype_raw)
        except ValueError:
            raise ControllerRegressionSchemaError(
                f"{context}.interface_type must be one of "
                f"{[e.value for e in InterfaceType]}, got {itype_raw!r}"
            )
        rate = _require_positive_float(data, "command_rate_hz", context)
        policy = SequencePolicyConfig.from_dict(
            _require(data, "sequence_policy", context), context
        )
        return cls(name=name, interface_type=itype, command_rate_hz=rate, sequence_policy=policy)


@dataclass(frozen=True)
class ReceiverConfig:
    name: str
    controller_type: ControllerType
    max_latency_deadline_ms: float
    safety_function_class: SafetyFunctionClass

    @classmethod
    def from_dict(cls, data: Any, context: str = "receiver_config") -> "ReceiverConfig":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{context} must be an object")
        name = _require_string(data, "name", context)
        ctype_raw = _require_string(data, "controller_type", context)
        try:
            ctype = ControllerType(ctype_raw)
        except ValueError:
            raise ControllerRegressionSchemaError(
                f"{context}.controller_type must be one of "
                f"{[e.value for e in ControllerType]}, got {ctype_raw!r}"
            )
        latency = _require_positive_float(data, "max_latency_deadline_ms", context)
        sfc_raw = _require_string(data, "safety_function_class", context)
        try:
            sfc = SafetyFunctionClass(sfc_raw)
        except ValueError:
            raise ControllerRegressionSchemaError(
                f"{context}.safety_function_class must be one of "
                f"{[e.value for e in SafetyFunctionClass]}, got {sfc_raw!r}"
            )
        return cls(
            name=name, controller_type=ctype,
            max_latency_deadline_ms=latency, safety_function_class=sfc,
        )


@dataclass(frozen=True)
class CommandLimits:
    """Velocity and torque bounds for command supervision.

    For differential-drive profiles, max_linear_velocity_mps and
    max_angular_velocity_rads are required. For torque-controlled profiles,
    max_torque_mnm is required. Custom limits are stored in custom_limits.
    """
    max_linear_velocity_mps: float | None = None
    max_angular_velocity_rads: float | None = None
    max_torque_mnm: int | None = None
    custom_limits: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any, interface_type: InterfaceType, context: str = "command_limits") -> "CommandLimits":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{context} must be an object")

        lin_vel = None
        ang_vel = None
        torque = None
        custom: list[dict[str, Any]] = []

        if interface_type == InterfaceType.ROS2_DIFF_DRIVE:
            lin_vel = _require_positive_float(data, "max_linear_velocity_mps", context)
            ang_vel = _require_positive_float(data, "max_angular_velocity_rads", context)
        elif interface_type == InterfaceType.CAN_BUS_TORQUE:
            val = _require(data, "max_torque_mnm", context)
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise ControllerRegressionSchemaError(f"{context}.max_torque_mnm must be a positive integer")
            torque = val
        elif interface_type == InterfaceType.PROPRIETARY_SPI:
            # Proprietary SPI uses custom_limits
            raw_custom = data.get("custom_limits", [])
            if not isinstance(raw_custom, list):
                raise ControllerRegressionSchemaError(f"{context}.custom_limits must be a list")
            custom = raw_custom
        elif interface_type == InterfaceType.CUSTOM:
            raw_custom = data.get("custom_limits", [])
            if not isinstance(raw_custom, list):
                raise ControllerRegressionSchemaError(f"{context}.custom_limits must be a list")
            custom = raw_custom

        return cls(
            max_linear_velocity_mps=lin_vel,
            max_angular_velocity_rads=ang_vel,
            max_torque_mnm=torque,
            custom_limits=custom,
        )

    def check_diff_drive_command(
        self, lin_mps: float, ang_rads: float
    ) -> tuple[bool, str]:
        """Check whether a diff-drive command is within declared limits.

        Returns (within_limits, reason_string).
        """
        if self.max_linear_velocity_mps is not None:
            if abs(lin_mps) > self.max_linear_velocity_mps:
                return False, (
                    f"linear velocity {lin_mps:.4f} m/s exceeds limit "
                    f"{self.max_linear_velocity_mps:.4f} m/s"
                )
        if self.max_angular_velocity_rads is not None:
            if abs(ang_rads) > self.max_angular_velocity_rads:
                return False, (
                    f"angular velocity {ang_rads:.4f} rad/s exceeds limit "
                    f"{self.max_angular_velocity_rads:.4f} rad/s"
                )
        return True, "within_limits"


@dataclass(frozen=True)
class FaultCase:
    fault_id: str
    kind: FaultKind
    description: str
    expected_state: str

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "FaultCase":
        ctx = f"fault_corpus.faults[{index}]"
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{ctx} must be an object")
        fault_id = _require_string(data, "fault_id", ctx)
        kind_raw = _require_string(data, "kind", ctx)
        try:
            kind = FaultKind(kind_raw)
        except ValueError:
            raise ControllerRegressionSchemaError(
                f"{ctx}.kind must be one of {[e.value for e in FaultKind]}, "
                f"got {kind_raw!r}"
            )
        desc = _require_string(data, "description", ctx)
        expected = _require_string(data, "expected_state", ctx)
        return cls(fault_id=fault_id, kind=kind, description=desc, expected_state=expected)


@dataclass(frozen=True)
class FaultCorpus:
    faults: list[FaultCase]

    @classmethod
    def from_dict(cls, data: Any, context: str = "fault_corpus") -> "FaultCorpus":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError(f"{context} must be an object")
        faults_raw = _require(data, "faults", context)
        if not isinstance(faults_raw, list) or not faults_raw:
            raise ControllerRegressionSchemaError(
                f"{context}.faults must be a non-empty list"
            )
        faults = [FaultCase.from_dict(f, i) for i, f in enumerate(faults_raw)]
        # Validate unique fault_ids
        ids = [f.fault_id for f in faults]
        if len(ids) != len(set(ids)):
            duplicates = {fid for fid in ids if ids.count(fid) > 1}
            raise ControllerRegressionSchemaError(
                f"{context}.faults contains duplicate fault_ids: {sorted(duplicates)}"
            )
        return cls(faults=faults)


# ---------------------------------------------------------------------------
# Top-level profile
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ControllerRegressionProfile:
    schema_version: str
    profile_id: str
    producer_config: ProducerConfig
    receiver_config: ReceiverConfig
    command_limits: CommandLimits
    fault_corpus: FaultCorpus
    applicable_standards: list[str]

    @classmethod
    def from_dict(cls, data: Any) -> "ControllerRegressionProfile":
        if not isinstance(data, dict):
            raise ControllerRegressionSchemaError("profile root must be an object")

        # schema_version
        sv = data.get("schema_version")
        if sv != "1.0":
            raise ControllerRegressionSchemaError(
                f"schema_version must be '1.0', got {sv!r}"
            )

        # profile_id
        pid = data.get("profile_id")
        if not isinstance(pid, str) or not pid:
            raise ControllerRegressionSchemaError("profile_id must be a non-empty string")
        if _IDENTIFIER_RE.fullmatch(pid) is None:
            raise ControllerRegressionSchemaError(
                f"profile_id {pid!r} must match pattern [a-z][a-z0-9_-]{{2,63}}"
            )

        # producer_config
        producer = ProducerConfig.from_dict(
            data.get("producer_config"), "producer_config"
        )

        # receiver_config
        receiver = ReceiverConfig.from_dict(
            data.get("receiver_config"), "receiver_config"
        )

        # command_limits (validated against interface_type)
        limits_raw = data.get("command_limits")
        if limits_raw is None:
            raise ControllerRegressionSchemaError("profile missing required field 'command_limits'")
        limits = CommandLimits.from_dict(limits_raw, producer.interface_type, "command_limits")

        # fault_corpus
        corpus_raw = data.get("fault_corpus")
        if corpus_raw is None:
            raise ControllerRegressionSchemaError("profile missing required field 'fault_corpus'")
        corpus = FaultCorpus.from_dict(corpus_raw)

        # applicable_standards
        standards_raw = data.get("applicable_standards", [])
        if not isinstance(standards_raw, list):
            raise ControllerRegressionSchemaError("applicable_standards must be a list")
        validated_standards = validate_standards_citations(standards_raw)

        return cls(
            schema_version=sv,
            profile_id=pid,
            producer_config=producer,
            receiver_config=receiver,
            command_limits=limits,
            fault_corpus=corpus,
            applicable_standards=validated_standards,
        )

    @classmethod
    def from_json_file(cls, path: Path | str) -> "ControllerRegressionProfile":
        path = Path(path)
        if not path.exists():
            raise ControllerRegressionSchemaError(f"profile file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ControllerRegressionSchemaError(
                f"profile JSON parse error in {path}: {exc}"
            ) from exc
        return cls.from_dict(data)


def load_controller_regression_profile(path: Path | str) -> ControllerRegressionProfile:
    """Load and validate a controller regression profile from a JSON file."""
    return ControllerRegressionProfile.from_json_file(path)
