"""Unit tests for the controller regression profile schema (Stage 0B acceptance gate).

Acceptance criteria:
  - All fields validated
  - Invalid configurations rejected
  - applicable_standards entries pass whitelist check against governed standards registry
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.regression.schema import (
    ControllerRegressionProfile,
    ControllerRegressionSchemaError,
    FaultKind,
    InterfaceType,
    SafetyFunctionClass,
    load_controller_regression_profile,
)
from argus.regression.standards import StandardsCitationError


ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "config" / "profiles" / "regression"


# ---------------------------------------------------------------------------
# 1. Reference profile loading
# ---------------------------------------------------------------------------

class TestReferenceProfiles:
    def test_robot_diff_drive_ros2_v0_loads(self) -> None:
        profile = load_controller_regression_profile(
            PROFILES_DIR / "robot_diff_drive_ros2_v0.json"
        )
        assert profile.schema_version == "1.0"
        assert profile.profile_id == "robot_diff_drive_ros2_v0"
        assert profile.producer_config.interface_type == InterfaceType.ROS2_DIFF_DRIVE
        assert profile.receiver_config.safety_function_class == SafetyFunctionClass.SIL2
        assert profile.command_limits.max_linear_velocity_mps == 1.5
        assert profile.command_limits.max_angular_velocity_rads == 1.0
        assert len(profile.fault_corpus.faults) == 9
        assert "ISO 3691-4:2023" in profile.applicable_standards

    def test_automotive_ecu_can_v0_loads(self) -> None:
        profile = load_controller_regression_profile(
            PROFILES_DIR / "automotive_ecu_can_v0.json"
        )
        assert profile.profile_id == "automotive_ecu_can_v0"
        assert profile.producer_config.interface_type == InterfaceType.CAN_BUS_TORQUE
        assert profile.receiver_config.safety_function_class == SafetyFunctionClass.ASIL_C
        assert profile.command_limits.max_torque_mnm == 50000
        assert len(profile.fault_corpus.faults) == 9
        assert "ISO 26262:2018" in profile.applicable_standards

    def test_industrial_cobot_joint_v0_loads(self) -> None:
        profile = load_controller_regression_profile(
            PROFILES_DIR / "industrial_cobot_joint_v0.json"
        )
        assert profile.profile_id == "industrial_cobot_joint_v0"
        assert profile.producer_config.interface_type == InterfaceType.PROPRIETARY_SPI
        assert profile.receiver_config.safety_function_class == SafetyFunctionClass.PL_D
        assert len(profile.command_limits.custom_limits) == 4
        assert len(profile.fault_corpus.faults) == 9
        assert "ISO 10218-1:2011" in profile.applicable_standards


# ---------------------------------------------------------------------------
# 2. Schema validation - producer_config
# ---------------------------------------------------------------------------

def _base_profile_dict() -> dict:
    """Return a minimal valid controller_regression_v0 profile dict."""
    return {
        "schema_version": "1.0",
        "profile_id": "test_profile_v0",
        "producer_config": {
            "name": "test_producer",
            "interface_type": "ros2_diff_drive",
            "command_rate_hz": 10.0,
            "sequence_policy": {
                "sequence_rollover": "monotonic_64",
                "stale_data_age_ms": 500.0,
                "reset_epoch": "controller_start",
                "queue_overflow_behavior": "drop_oldest",
                "invalid_numeric_behavior": "reject",
            },
        },
        "receiver_config": {
            "name": "test_receiver",
            "controller_type": "motion_controller",
            "max_latency_deadline_ms": 100.0,
            "safety_function_class": "SIL2",
        },
        "command_limits": {
            "max_linear_velocity_mps": 1.5,
            "max_angular_velocity_rads": 1.0,
        },
        "fault_corpus": {
            "faults": [
                {
                    "fault_id": "fc_test_001",
                    "kind": "stale_command",
                    "description": "Test stale command fault",
                    "expected_state": "safe_halt",
                }
            ]
        },
        "applicable_standards": ["ISO 3691-4:2023"],
    }


class TestProducerConfigValidation:
    def test_valid_ros2_diff_drive_accepted(self) -> None:
        data = _base_profile_dict()
        profile = ControllerRegressionProfile.from_dict(data)
        assert profile.producer_config.interface_type == InterfaceType.ROS2_DIFF_DRIVE

    def test_invalid_interface_type_rejected(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["interface_type"] = "invalid_type"
        with pytest.raises(ControllerRegressionSchemaError, match="interface_type"):
            ControllerRegressionProfile.from_dict(data)

    def test_missing_name_rejected(self) -> None:
        data = _base_profile_dict()
        del data["producer_config"]["name"]
        with pytest.raises(ControllerRegressionSchemaError, match="name"):
            ControllerRegressionProfile.from_dict(data)

    def test_negative_command_rate_rejected(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["command_rate_hz"] = -5.0
        with pytest.raises(ControllerRegressionSchemaError):
            ControllerRegressionProfile.from_dict(data)

    def test_zero_command_rate_rejected(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["command_rate_hz"] = 0.0
        with pytest.raises(ControllerRegressionSchemaError):
            ControllerRegressionProfile.from_dict(data)

    def test_invalid_sequence_rollover_rejected(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["sequence_policy"]["sequence_rollover"] = "invalid"
        with pytest.raises(ControllerRegressionSchemaError, match="sequence_rollover"):
            ControllerRegressionProfile.from_dict(data)

    def test_invalid_overflow_behavior_rejected(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["sequence_policy"]["queue_overflow_behavior"] = "garbage"
        with pytest.raises(ControllerRegressionSchemaError, match="queue_overflow_behavior"):
            ControllerRegressionProfile.from_dict(data)


# ---------------------------------------------------------------------------
# 3. Schema validation - receiver_config
# ---------------------------------------------------------------------------

class TestReceiverConfigValidation:
    def test_invalid_controller_type_rejected(self) -> None:
        data = _base_profile_dict()
        data["receiver_config"]["controller_type"] = "not_a_type"
        with pytest.raises(ControllerRegressionSchemaError, match="controller_type"):
            ControllerRegressionProfile.from_dict(data)

    def test_invalid_safety_function_class_rejected(self) -> None:
        data = _base_profile_dict()
        data["receiver_config"]["safety_function_class"] = "ASIL_X"
        with pytest.raises(ControllerRegressionSchemaError, match="safety_function_class"):
            ControllerRegressionProfile.from_dict(data)

    def test_zero_latency_deadline_rejected(self) -> None:
        data = _base_profile_dict()
        data["receiver_config"]["max_latency_deadline_ms"] = 0.0
        with pytest.raises(ControllerRegressionSchemaError):
            ControllerRegressionProfile.from_dict(data)

    def test_all_safety_function_classes_accepted(self) -> None:
        valid_classes = [
            "SIL1", "SIL2", "SIL3", "SIL4",
            "PLc", "PLd", "PLe",
            "ASIL_A", "ASIL_B", "ASIL_C", "ASIL_D",
            "custom",
        ]
        for sfc in valid_classes:
            data = _base_profile_dict()
            data["receiver_config"]["safety_function_class"] = sfc
            profile = ControllerRegressionProfile.from_dict(data)
            assert profile.receiver_config.safety_function_class.value == sfc


# ---------------------------------------------------------------------------
# 4. Schema validation - command_limits
# ---------------------------------------------------------------------------

class TestCommandLimitsValidation:
    def test_diff_drive_requires_linear_velocity(self) -> None:
        data = _base_profile_dict()
        del data["command_limits"]["max_linear_velocity_mps"]
        with pytest.raises(ControllerRegressionSchemaError, match="max_linear_velocity_mps"):
            ControllerRegressionProfile.from_dict(data)

    def test_diff_drive_requires_angular_velocity(self) -> None:
        data = _base_profile_dict()
        del data["command_limits"]["max_angular_velocity_rads"]
        with pytest.raises(ControllerRegressionSchemaError, match="max_angular_velocity_rads"):
            ControllerRegressionProfile.from_dict(data)

    def test_can_torque_requires_max_torque_mnm(self) -> None:
        data = _base_profile_dict()
        data["producer_config"]["interface_type"] = "can_bus_torque"
        data["command_limits"] = {}
        with pytest.raises(ControllerRegressionSchemaError, match="max_torque_mnm"):
            ControllerRegressionProfile.from_dict(data)

    def test_diff_drive_limits_used_for_supervision(self) -> None:
        data = _base_profile_dict()
        profile = ControllerRegressionProfile.from_dict(data)
        within, _ = profile.command_limits.check_diff_drive_command(1.0, 0.5)
        assert within is True

    def test_over_limit_command_detected(self) -> None:
        data = _base_profile_dict()
        profile = ControllerRegressionProfile.from_dict(data)
        within, reason = profile.command_limits.check_diff_drive_command(2.0, 0.5)
        assert within is False
        assert "linear velocity" in reason


# ---------------------------------------------------------------------------
# 5. Fault corpus validation
# ---------------------------------------------------------------------------

class TestFaultCorpusValidation:
    def test_all_fault_kinds_accepted(self) -> None:
        data = _base_profile_dict()
        faults = [
            {
                "fault_id": f"fc_{kind.value}_001",
                "kind": kind.value,
                "description": f"Test {kind.value}",
                "expected_state": "safe_halt",
            }
            for kind in FaultKind
        ]
        data["fault_corpus"]["faults"] = faults
        profile = ControllerRegressionProfile.from_dict(data)
        assert len(profile.fault_corpus.faults) == len(FaultKind)

    def test_duplicate_fault_ids_rejected(self) -> None:
        data = _base_profile_dict()
        data["fault_corpus"]["faults"] = [
            {"fault_id": "same_id", "kind": "stale_command",
             "description": "First", "expected_state": "safe_halt"},
            {"fault_id": "same_id", "kind": "missing_burst",
             "description": "Second", "expected_state": "safe_halt"},
        ]
        with pytest.raises(ControllerRegressionSchemaError, match="duplicate fault_ids"):
            ControllerRegressionProfile.from_dict(data)

    def test_empty_fault_corpus_rejected(self) -> None:
        data = _base_profile_dict()
        data["fault_corpus"]["faults"] = []
        with pytest.raises(ControllerRegressionSchemaError, match="non-empty"):
            ControllerRegressionProfile.from_dict(data)

    def test_invalid_fault_kind_rejected(self) -> None:
        data = _base_profile_dict()
        data["fault_corpus"]["faults"][0]["kind"] = "not_a_real_fault"
        with pytest.raises(ControllerRegressionSchemaError, match="kind"):
            ControllerRegressionProfile.from_dict(data)


# ---------------------------------------------------------------------------
# 6. Standards whitelist validation
# ---------------------------------------------------------------------------

class TestStandardsWhitelist:
    def test_valid_standard_accepted(self) -> None:
        data = _base_profile_dict()
        data["applicable_standards"] = ["ISO 3691-4:2023"]
        profile = ControllerRegressionProfile.from_dict(data)
        assert "ISO 3691-4:2023" in profile.applicable_standards

    def test_multiple_valid_standards_accepted(self) -> None:
        data = _base_profile_dict()
        data["applicable_standards"] = [
            "ISO 3691-4:2023",
            "IEC 61508:2010",
            "ISO 26262:2018",
        ]
        profile = ControllerRegressionProfile.from_dict(data)
        assert len(profile.applicable_standards) == 3

    def test_invalid_standard_rejected(self) -> None:
        data = _base_profile_dict()
        data["applicable_standards"] = ["INVENTED_STANDARD_9999"]
        with pytest.raises((ControllerRegressionSchemaError, StandardsCitationError)):
            ControllerRegressionProfile.from_dict(data)

    def test_empty_standards_list_accepted(self) -> None:
        data = _base_profile_dict()
        data["applicable_standards"] = []
        profile = ControllerRegressionProfile.from_dict(data)
        assert profile.applicable_standards == []

    def test_all_reference_profiles_have_valid_standards(self) -> None:
        """All three reference profiles must pass standards validation."""
        for profile_file in [
            "robot_diff_drive_ros2_v0.json",
            "automotive_ecu_can_v0.json",
            "industrial_cobot_joint_v0.json",
        ]:
            profile = load_controller_regression_profile(PROFILES_DIR / profile_file)
            assert len(profile.applicable_standards) >= 1


# ---------------------------------------------------------------------------
# 7. Profile identity
# ---------------------------------------------------------------------------

class TestProfileIdentity:
    def test_wrong_schema_version_rejected(self) -> None:
        data = _base_profile_dict()
        data["schema_version"] = "2.0"
        with pytest.raises(ControllerRegressionSchemaError, match="schema_version"):
            ControllerRegressionProfile.from_dict(data)

    def test_invalid_profile_id_pattern_rejected(self) -> None:
        data = _base_profile_dict()
        data["profile_id"] = "INVALID PROFILE ID!"
        with pytest.raises(ControllerRegressionSchemaError, match="profile_id"):
            ControllerRegressionProfile.from_dict(data)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ControllerRegressionSchemaError, match="not found"):
            load_controller_regression_profile(tmp_path / "nonexistent.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(ControllerRegressionSchemaError, match="parse error"):
            load_controller_regression_profile(f)
