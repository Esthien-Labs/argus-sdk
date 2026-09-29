"""Integration tests for the robot command trace adapter (Stage 0A acceptance gate).

Acceptance criteria:
  - A synthetic MCAP trace with 100 nominal commands, 10 stale commands,
    and 3 fault injections
  - Field extraction verified against golden expected values
  - Sequence validation (stale detection) verified
  - Invalid command rejection verified
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from argus.adapters.robot_command import (
    AtlasTraceAdapterError,
    DifferentialDrivePayload,
    EventType,
    InvalidNumericBehavior,
    QueueOverflowBehavior,
    RobotCommandTrace,
    SequenceRolloverPolicy,
    generate_synthetic_trace,
    load_trace,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_trace_path(tmp_path: Path) -> Path:
    """Write a synthetic trace to a temp file and return the path."""
    doc = generate_synthetic_trace(
        nominal_count=100,
        stale_count=10,
        fault_count=3,
        seed=20_260_915,
    )
    trace_file = tmp_path / "test_trace.json"
    trace_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return trace_file


@pytest.fixture()
def loaded_trace(synthetic_trace_path: Path) -> RobotCommandTrace:
    return load_trace(synthetic_trace_path)


# ---------------------------------------------------------------------------
# 1. Manifest field extraction
# ---------------------------------------------------------------------------

class TestManifestFields:
    def test_schema_version(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.schema_version == "1.0"

    def test_session_id_present(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.session_id
        assert isinstance(loaded_trace.manifest.session_id, str)

    def test_producer_id(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.producer_id == "synthetic_diff_drive_producer"

    def test_receiver_id(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.receiver_id == "synthetic_motion_controller"

    def test_trace_format(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.trace_format == "atlas-trace-json"

    def test_sequence_policy_rollover(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.sequence_policy.rollover == SequenceRolloverPolicy.MONOTONIC_64

    def test_sequence_policy_stale_age(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.sequence_policy.stale_data_age_ms == 500.0

    def test_sequence_policy_overflow(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.sequence_policy.queue_overflow_behavior == QueueOverflowBehavior.DROP_OLDEST

    def test_sequence_policy_invalid_behavior(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.manifest.sequence_policy.invalid_numeric_behavior == InvalidNumericBehavior.REJECT


# ---------------------------------------------------------------------------
# 2. Event counts and types
# ---------------------------------------------------------------------------

class TestEventCounts:
    def test_total_event_count(self, loaded_trace: RobotCommandTrace) -> None:
        # 100 nominal + 10 stale + 3 fault injection = 113
        assert len(loaded_trace.events) == 113

    def test_command_event_count(self, loaded_trace: RobotCommandTrace) -> None:
        command_events = loaded_trace.command_events()
        # 100 nominal + 10 stale = 110 command events
        assert len(command_events) == 110

    def test_fault_event_count(self, loaded_trace: RobotCommandTrace) -> None:
        fault_events = loaded_trace.fault_events()
        assert len(fault_events) == 3

    def test_command_event_types(self, loaded_trace: RobotCommandTrace) -> None:
        for event in loaded_trace.command_events():
            assert event.event_type == EventType.COMMAND

    def test_fault_event_types(self, loaded_trace: RobotCommandTrace) -> None:
        for event in loaded_trace.fault_events():
            assert event.event_type == EventType.FAULT


# ---------------------------------------------------------------------------
# 3. Field extraction for command events
# ---------------------------------------------------------------------------

class TestCommandPayloadFields:
    def test_first_command_has_diff_drive_payload(self, loaded_trace: RobotCommandTrace) -> None:
        first_cmd = loaded_trace.command_events()[0]
        assert isinstance(first_cmd.payload, DifferentialDrivePayload)

    def test_velocities_are_finite(self, loaded_trace: RobotCommandTrace) -> None:
        for event in loaded_trace.command_events():
            payload = event.payload
            if isinstance(payload, DifferentialDrivePayload):
                assert math.isfinite(payload.velocity_lin_mps)
                assert math.isfinite(payload.velocity_ang_rads)

    def test_sequence_numbers_present(self, loaded_trace: RobotCommandTrace) -> None:
        seqs = [e.sequence_number for e in loaded_trace.events]
        assert len(seqs) == len(loaded_trace.events)
        assert all(isinstance(s, int) for s in seqs)

    def test_timestamps_monotonically_increasing_for_non_stale(
        self, loaded_trace: RobotCommandTrace
    ) -> None:
        # The first 100 nominal commands should have increasing timestamps
        nominal_cmds = [
            e for e in loaded_trace.command_events()
            if not e.is_stale
        ][:100]
        timestamps = [e.timestamp_us for e in nominal_cmds]
        assert all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))

    def test_clock_domain_id_present(self, loaded_trace: RobotCommandTrace) -> None:
        for event in loaded_trace.events:
            assert event.clock_domain_id
            assert isinstance(event.clock_domain_id, str)


# ---------------------------------------------------------------------------
# 4. Stale detection
# ---------------------------------------------------------------------------

class TestStaleDetection:
    def test_stale_count_is_10(self, loaded_trace: RobotCommandTrace) -> None:
        assert loaded_trace.stale_count == 10

    def test_stale_events_flagged(self, loaded_trace: RobotCommandTrace) -> None:
        stale_events = [e for e in loaded_trace.command_events() if e.is_stale]
        assert len(stale_events) == 10

    def test_non_stale_events_not_flagged(self, loaded_trace: RobotCommandTrace) -> None:
        non_stale = [
            e for e in loaded_trace.command_events()
            if not e.is_stale
        ]
        assert len(non_stale) == 100  # 110 total - 10 stale = 100


# ---------------------------------------------------------------------------
# 5. Invalid command rejection
# ---------------------------------------------------------------------------

class TestInvalidRejection:
    def test_nan_command_is_rejected(self, tmp_path: Path) -> None:
        """A command with NaN velocity must be rejected when policy is 'reject'."""
        doc = generate_synthetic_trace(nominal_count=5, stale_count=0, fault_count=0)
        # Inject a NaN command
        doc["events"].append({
            "sequence_number": 9999,
            "timestamp_us": doc["events"][-1]["timestamp_us"] + 100_000,
            "clock_domain_id": "controller_monotonic",
            "event_type": "command",
            "payload": {
                "velocity_lin_mps": float("nan"),
                "velocity_ang_rads": 0.5,
                "controller_state": "nominal",
                "fault_flags": 0,
                "rearm_requested": False,
            },
        })
        trace_file = tmp_path / "nan_trace.json"
        trace_file.write_text(json.dumps(doc), encoding="utf-8")

        trace = load_trace(trace_file)
        nan_events = [e for e in trace.command_events() if e.is_rejected]
        assert len(nan_events) >= 1, "NaN command must be rejected when policy is 'reject'"

    def test_inf_command_is_rejected(self, tmp_path: Path) -> None:
        doc = generate_synthetic_trace(nominal_count=5, stale_count=0, fault_count=0)
        doc["events"].append({
            "sequence_number": 8888,
            "timestamp_us": doc["events"][-1]["timestamp_us"] + 100_000,
            "clock_domain_id": "controller_monotonic",
            "event_type": "command",
            "payload": {
                "velocity_lin_mps": float("inf"),
                "velocity_ang_rads": 0.0,
                "controller_state": "nominal",
                "fault_flags": 0,
                "rearm_requested": False,
            },
        })
        trace_file = tmp_path / "inf_trace.json"
        trace_file.write_text(json.dumps(doc), encoding="utf-8")

        trace = load_trace(trace_file)
        inf_events = [e for e in trace.command_events() if e.is_rejected]
        assert len(inf_events) >= 1, "Inf command must be rejected when policy is 'reject'"


# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AtlasTraceAdapterError, match="not found"):
            load_trace(tmp_path / "nonexistent.json")

    def test_unknown_extension_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "trace.xyz"
        f.write_text("{}", encoding="utf-8")
        with pytest.raises(AtlasTraceAdapterError, match="cannot infer trace format"):
            load_trace(f)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(AtlasTraceAdapterError, match="parse error"):
            load_trace(f)

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "no_manifest.json"
        f.write_text('{"events": []}', encoding="utf-8")
        with pytest.raises(AtlasTraceAdapterError, match="missing 'manifest'"):
            load_trace(f)

    def test_wrong_schema_version_raises(self, tmp_path: Path) -> None:
        doc = generate_synthetic_trace(nominal_count=1)
        doc["manifest"]["schema_version"] = "2.0"
        f = tmp_path / "wrong_version.json"
        f.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(AtlasTraceAdapterError, match="schema_version"):
            load_trace(f)


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_produces_identical_traces(self) -> None:
        doc1 = generate_synthetic_trace(seed=42)
        doc2 = generate_synthetic_trace(seed=42)
        assert doc1 == doc2

    def test_different_seeds_produce_different_traces(self) -> None:
        doc1 = generate_synthetic_trace(seed=1)
        doc2 = generate_synthetic_trace(seed=2)
        # The manifests differ in session_id; check that payloads differ
        payloads1 = [e["payload"] for e in doc1["events"] if e["event_type"] == "command"]
        payloads2 = [e["payload"] for e in doc2["events"] if e["event_type"] == "command"]
        assert payloads1 != payloads2
