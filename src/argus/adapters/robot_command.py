"""Robot command trace adapter (Stage 0A).

Reads robot controller command traces from three source formats and converts
them to the Atlas internal RobotCommandTrace representation.

Source formats:
  atlas-trace-json   Atlas native JSON format (primary; no external dependency)
  rosbag2            ROS 2 SQLite3 bag (stdlib sqlite3)
  mcap               MCAP binary (requires `mcap` package; raises clear error if absent)

The adapter enforces the sequence policy declared in the trace manifest:
  - stale command detection (timestamp age > stale_data_age_ms)
  - duplicate sequence number detection
  - out-of-range numeric value detection and rejection/clamping per policy
  - invalid-command flagging per invalid_numeric_behavior

Evidence boundary: this module produces digital_source_verification evidence.
It records no physical latency, power, or safety certification.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .._utils import sha256_file


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    COMMAND = "command"
    STATE_TRANSITION = "state_transition"
    FAULT = "fault"
    RESET = "reset"
    REARM = "rearm"


class SequenceRolloverPolicy(str, Enum):
    TRUNCATE = "truncate"
    WRAP_65535 = "wrap_65535"
    MONOTONIC_64 = "monotonic_64"


class QueueOverflowBehavior(str, Enum):
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    ERROR = "error"


class InvalidNumericBehavior(str, Enum):
    REJECT = "reject"
    CLAMP = "clamp"
    PASS_THROUGH = "pass_through"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AtlasTraceAdapterError(ValueError):
    """Raised when a trace file cannot be parsed or fails validation."""


# ---------------------------------------------------------------------------
# Payload dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DifferentialDrivePayload:
    """Command payload for differential-drive robots (ROS 2 / Nav2 use case)."""
    velocity_lin_mps: float
    velocity_ang_rads: float
    controller_state: str
    fault_flags: int  # uint32
    rearm_requested: bool

    def is_numeric_valid(self) -> bool:
        return (
            math.isfinite(self.velocity_lin_mps)
            and math.isfinite(self.velocity_ang_rads)
            and 0 <= self.fault_flags <= 0xFFFF_FFFF
        )


@dataclass(frozen=True)
class TorquePayload:
    """Command payload for torque-controlled actuators (CAN bus / industrial use case)."""
    torque_mnm: int       # milli-Newton-metres, int32
    velocity_urad_s: int  # micro-radians per second, int32
    controller_state: str
    fault_flags: int      # uint32
    rearm_requested: bool

    def is_numeric_valid(self) -> bool:
        return (
            -(2**31) <= self.torque_mnm <= (2**31 - 1)
            and -(2**31) <= self.velocity_urad_s <= (2**31 - 1)
            and 0 <= self.fault_flags <= 0xFFFF_FFFF
        )


# ---------------------------------------------------------------------------
# Sequence policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SequencePolicy:
    rollover: SequenceRolloverPolicy
    stale_data_age_ms: float          # max age before a command is stale
    reset_epoch: str                  # how sequence resets after restart
    queue_overflow_behavior: QueueOverflowBehavior
    invalid_numeric_behavior: InvalidNumericBehavior

    @classmethod
    def from_dict(cls, data: dict[str, Any], context: str = "sequence_policy") -> "SequencePolicy":
        required = {
            "sequence_rollover", "stale_data_age_ms",
            "reset_epoch", "queue_overflow_behavior", "invalid_numeric_behavior",
        }
        missing = required - set(data)
        if missing:
            raise AtlasTraceAdapterError(
                f"{context}: missing required fields: {', '.join(sorted(missing))}"
            )
        try:
            return cls(
                rollover=SequenceRolloverPolicy(data["sequence_rollover"]),
                stale_data_age_ms=float(data["stale_data_age_ms"]),
                reset_epoch=str(data["reset_epoch"]),
                queue_overflow_behavior=QueueOverflowBehavior(data["queue_overflow_behavior"]),
                invalid_numeric_behavior=InvalidNumericBehavior(data["invalid_numeric_behavior"]),
            )
        except (ValueError, KeyError) as exc:
            raise AtlasTraceAdapterError(f"{context}: invalid value - {exc}") from exc


# ---------------------------------------------------------------------------
# Trace manifest
# ---------------------------------------------------------------------------

@dataclass
class TraceManifest:
    schema_version: str
    session_id: str
    producer_id: str
    receiver_id: str
    sequence_policy: SequencePolicy
    trace_format: str        # "atlas-trace-json" | "rosbag2" | "mcap"
    source_path: str
    source_sha256: str
    event_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: str, source_sha256: str) -> "TraceManifest":
        required = {
            "schema_version", "session_id", "producer_id",
            "receiver_id", "sequence_policy", "trace_format",
        }
        missing = required - set(data)
        if missing:
            raise AtlasTraceAdapterError(
                f"trace manifest missing required fields: {', '.join(sorted(missing))}"
            )
        if data["schema_version"] != "1.0":
            raise AtlasTraceAdapterError(
                f"trace manifest schema_version must be '1.0', got {data['schema_version']!r}"
            )
        return cls(
            schema_version=data["schema_version"],
            session_id=str(data["session_id"]),
            producer_id=str(data["producer_id"]),
            receiver_id=str(data["receiver_id"]),
            sequence_policy=SequencePolicy.from_dict(data["sequence_policy"]),
            trace_format=str(data["trace_format"]),
            source_path=source_path,
            source_sha256=source_sha256,
            event_count=int(data.get("event_count", 0)),
        )


# ---------------------------------------------------------------------------
# Robot command event
# ---------------------------------------------------------------------------

@dataclass
class RobotCommandEvent:
    sequence_number: int
    timestamp_us: int        # microseconds, absolute
    clock_domain_id: str
    event_type: EventType
    payload: DifferentialDrivePayload | TorquePayload | dict[str, Any]

    # Validation flags - set by the adapter after sequence/stale analysis
    is_stale: bool = False
    is_duplicate: bool = False
    is_out_of_range: bool = False
    is_rejected: bool = False   # True when invalid_numeric_behavior == REJECT

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        index: int,
        policy: SequencePolicy,
    ) -> "RobotCommandEvent":
        required = {
            "sequence_number", "timestamp_us", "clock_domain_id",
            "event_type", "payload",
        }
        missing = required - set(data)
        if missing:
            raise AtlasTraceAdapterError(
                f"events[{index}] missing required fields: {', '.join(sorted(missing))}"
            )
        try:
            event_type = EventType(data["event_type"])
        except ValueError as exc:
            raise AtlasTraceAdapterError(
                f"events[{index}].event_type invalid: {data['event_type']!r}"
            ) from exc

        raw_payload = data["payload"]
        if not isinstance(raw_payload, dict):
            raise AtlasTraceAdapterError(f"events[{index}].payload must be an object")

        payload = _parse_payload(event_type, raw_payload, index)

        return cls(
            sequence_number=int(data["sequence_number"]),
            timestamp_us=int(data["timestamp_us"]),
            clock_domain_id=str(data["clock_domain_id"]),
            event_type=event_type,
            payload=payload,
        )


def _parse_payload(
    event_type: EventType,
    raw: dict[str, Any],
    index: int,
) -> DifferentialDrivePayload | TorquePayload | dict[str, Any]:
    """Parse typed payload for command events; pass-through for other event types."""
    if event_type != EventType.COMMAND:
        return raw

    # Detect payload type by presence of discriminating keys
    if "velocity_lin_mps" in raw or "velocity_ang_rads" in raw:
        try:
            return DifferentialDrivePayload(
                velocity_lin_mps=float(raw.get("velocity_lin_mps", 0.0)),
                velocity_ang_rads=float(raw.get("velocity_ang_rads", 0.0)),
                controller_state=str(raw.get("controller_state", "unknown")),
                fault_flags=int(raw.get("fault_flags", 0)),
                rearm_requested=bool(raw.get("rearm_requested", False)),
            )
        except (TypeError, ValueError) as exc:
            raise AtlasTraceAdapterError(
                f"events[{index}].payload diff-drive parse error: {exc}"
            ) from exc

    if "torque_mnm" in raw or "velocity_urad_s" in raw:
        try:
            return TorquePayload(
                torque_mnm=int(raw.get("torque_mnm", 0)),
                velocity_urad_s=int(raw.get("velocity_urad_s", 0)),
                controller_state=str(raw.get("controller_state", "unknown")),
                fault_flags=int(raw.get("fault_flags", 0)),
                rearm_requested=bool(raw.get("rearm_requested", False)),
            )
        except (TypeError, ValueError) as exc:
            raise AtlasTraceAdapterError(
                f"events[{index}].payload torque parse error: {exc}"
            ) from exc

    # Unknown command payload type - pass through as dict
    return raw


# ---------------------------------------------------------------------------
# Complete trace
# ---------------------------------------------------------------------------

@dataclass
class RobotCommandTrace:
    manifest: TraceManifest
    events: list[RobotCommandEvent]

    # Validation summary - populated by _validate_sequence()
    nominal_count: int = 0
    stale_count: int = 0
    fault_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0

    def command_events(self) -> list[RobotCommandEvent]:
        """Return only COMMAND-type events."""
        return [e for e in self.events if e.event_type == EventType.COMMAND]

    def fault_events(self) -> list[RobotCommandEvent]:
        """Return only FAULT-type events."""
        return [e for e in self.events if e.event_type == EventType.FAULT]


# ---------------------------------------------------------------------------
# Sequence validation
# ---------------------------------------------------------------------------

def _validate_sequence(trace: RobotCommandTrace) -> None:
    """Apply sequence policy to all events: stale, duplicate, numeric validity."""
    policy = trace.manifest.sequence_policy
    stale_threshold_us = int(policy.stale_data_age_ms * 1_000)

    seen_sequences: set[int] = set()
    prev_timestamp_us = 0

    for event in trace.events:
        # Duplicate sequence detection
        if event.sequence_number in seen_sequences:
            event.is_duplicate = True
            trace.duplicate_count += 1
        else:
            seen_sequences.add(event.sequence_number)

        # Stale detection: event is stale when it arrives too far after the previous
        if event.event_type == EventType.COMMAND and prev_timestamp_us > 0:
            age_us = event.timestamp_us - prev_timestamp_us
            if age_us > stale_threshold_us:
                event.is_stale = True
                trace.stale_count += 1

        if event.event_type == EventType.COMMAND:
            prev_timestamp_us = event.timestamp_us

        # Numeric validity for typed payloads
        payload = event.payload
        if isinstance(payload, (DifferentialDrivePayload, TorquePayload)):
            if not payload.is_numeric_valid():
                event.is_out_of_range = True
                if policy.invalid_numeric_behavior == InvalidNumericBehavior.REJECT:
                    event.is_rejected = True
                    trace.rejected_count += 1

        # Count event types
        if event.event_type == EventType.FAULT:
            trace.fault_count += 1

    # Count nominal = command events that are not stale, not duplicate, not rejected
    trace.nominal_count = sum(
        1 for e in trace.events
        if e.event_type == EventType.COMMAND
        and not e.is_stale
        and not e.is_duplicate
        and not e.is_rejected
    )


# ---------------------------------------------------------------------------
# Atlas-trace-json loader
# ---------------------------------------------------------------------------

def _sha256_file_local(path: Path) -> str:
    """Convenience alias so the rosbag2/mcap loaders below stay unchanged."""
    return sha256_file(path)

# Keep the original name the loaders use
_sha256_file = _sha256_file_local


def _load_atlas_json(path: Path) -> RobotCommandTrace:
    """Load an Atlas native JSON trace file."""
    raw_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        doc = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise AtlasTraceAdapterError(f"atlas-trace-json parse error in {path}: {exc}") from exc

    if not isinstance(doc, dict):
        raise AtlasTraceAdapterError(f"atlas-trace-json root must be an object in {path}")

    manifest_data = doc.get("manifest")
    if not isinstance(manifest_data, dict):
        raise AtlasTraceAdapterError(f"atlas-trace-json missing 'manifest' object in {path}")

    events_data = doc.get("events")
    if not isinstance(events_data, list):
        raise AtlasTraceAdapterError(f"atlas-trace-json missing 'events' array in {path}")

    manifest = TraceManifest.from_dict(manifest_data, str(path), source_sha256)

    events: list[RobotCommandEvent] = []
    for i, ev in enumerate(events_data):
        if not isinstance(ev, dict):
            raise AtlasTraceAdapterError(f"atlas-trace-json events[{i}] must be an object")
        events.append(RobotCommandEvent.from_dict(ev, i, manifest.sequence_policy))

    manifest.event_count = len(events)
    trace = RobotCommandTrace(manifest=manifest, events=events)
    _validate_sequence(trace)
    return trace


# ---------------------------------------------------------------------------
# rosbag2 loader (stdlib sqlite3)
# ---------------------------------------------------------------------------

def _load_rosbag2(path: Path) -> RobotCommandTrace:
    """Load a ROS 2 bag (SQLite3 format) and extract command events.

    The bag must contain a topic with message schema matching the Atlas
    robot_command_trace_v1 definition. The manifest topic name is
    '/atlas/command_trace_manifest' and commands are on
    '/atlas/robot_commands'.
    """
    if path.suffix != ".db3":
        raise AtlasTraceAdapterError(
            f"rosbag2 files must have .db3 extension, got {path.suffix!r}. "
            "For ROS 2 bag directories, pass the .db3 file inside the bag directory."
        )
    if not path.exists():
        raise AtlasTraceAdapterError(f"rosbag2 file not found: {path}")

    source_sha256 = _sha256_file(path)

    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.cursor()
        # Validate expected tables exist
        tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "messages" not in tables or "topics" not in tables:
            raise AtlasTraceAdapterError(
                f"rosbag2 file {path} missing expected 'messages' or 'topics' tables. "
                "Ensure this is a valid ROS 2 SQLite3 bag."
            )

        # Fetch topic IDs
        topic_rows = cursor.execute(
            "SELECT id, name FROM topics"
        ).fetchall()
        topic_map: dict[str, int] = {name: tid for tid, name in topic_rows}

        manifest_topic_id = topic_map.get("/atlas/command_trace_manifest")
        command_topic_id = topic_map.get("/atlas/robot_commands")

        if manifest_topic_id is None:
            raise AtlasTraceAdapterError(
                f"rosbag2 bag {path} missing required topic '/atlas/command_trace_manifest'. "
                "Record the Atlas trace manifest on that topic before creating the bag."
            )
        if command_topic_id is None:
            raise AtlasTraceAdapterError(
                f"rosbag2 bag {path} missing required topic '/atlas/robot_commands'."
            )

        # Load manifest message (first message on the manifest topic)
        manifest_row = cursor.execute(
            "SELECT data FROM messages WHERE topic_id=? ORDER BY timestamp ASC LIMIT 1",
            (manifest_topic_id,),
        ).fetchone()
        if manifest_row is None:
            raise AtlasTraceAdapterError(
                f"rosbag2 bag {path} has no messages on '/atlas/command_trace_manifest'."
            )
        manifest_data = json.loads(manifest_row[0])
        manifest = TraceManifest.from_dict(manifest_data, str(path), source_sha256)

        # Load command messages
        rows = cursor.execute(
            "SELECT data FROM messages WHERE topic_id=? ORDER BY timestamp ASC",
            (command_topic_id,),
        ).fetchall()

        events: list[RobotCommandEvent] = []
        for i, (data_blob,) in enumerate(rows):
            try:
                ev_dict = json.loads(data_blob)
            except json.JSONDecodeError as exc:
                raise AtlasTraceAdapterError(
                    f"rosbag2 message {i} on /atlas/robot_commands parse error: {exc}"
                ) from exc
            events.append(RobotCommandEvent.from_dict(ev_dict, i, manifest.sequence_policy))

    finally:
        conn.close()

    manifest.event_count = len(events)
    trace = RobotCommandTrace(manifest=manifest, events=events)
    _validate_sequence(trace)
    return trace


# ---------------------------------------------------------------------------
# MCAP loader (optional dependency)
# ---------------------------------------------------------------------------

def _load_mcap(path: Path) -> RobotCommandTrace:
    """Load an MCAP file using the `mcap` Python package.

    The mcap package is not in Atlas's core dependencies. Install it with:
        pip install mcap mcap-ros2-support

    MCAP topic conventions (same as rosbag2 above):
        /atlas/command_trace_manifest  - TraceManifest JSON (one message)
        /atlas/robot_commands          - RobotCommandEvent JSON (per command)
    """
    try:
        from mcap.reader import make_reader  # type: ignore[import]
    except ImportError as exc:
        raise AtlasTraceAdapterError(
            "MCAP format requires the 'mcap' package. "
            "Install with: pip install mcap\n"
            "Atlas internal JSON traces (.atlas-trace.json) are available without extra dependencies."
        ) from exc

    source_sha256 = _sha256_file(path)
    manifest: TraceManifest | None = None
    events: list[RobotCommandEvent] = []

    with path.open("rb") as fh:
        reader = make_reader(fh)
        for schema, channel, message in reader.iter_messages():
            if channel.topic == "/atlas/command_trace_manifest":
                manifest_data = json.loads(message.data)
                manifest = TraceManifest.from_dict(manifest_data, str(path), source_sha256)
            elif channel.topic == "/atlas/robot_commands":
                ev_dict = json.loads(message.data)
                idx = len(events)
                if manifest is None:
                    raise AtlasTraceAdapterError(
                        "MCAP file contains robot_commands before command_trace_manifest. "
                        "The manifest message must appear first in the file."
                    )
                events.append(RobotCommandEvent.from_dict(ev_dict, idx, manifest.sequence_policy))

    if manifest is None:
        raise AtlasTraceAdapterError(
            f"MCAP file {path} missing required topic '/atlas/command_trace_manifest'."
        )

    manifest.event_count = len(events)
    trace = RobotCommandTrace(manifest=manifest, events=events)
    _validate_sequence(trace)
    return trace


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

_FORMAT_DISPATCH: dict[str, Any] = {
    "atlas-trace-json": _load_atlas_json,
    "rosbag2": _load_rosbag2,
    "mcap": _load_mcap,
}

_EXTENSION_MAP: dict[str, str] = {
    ".json": "atlas-trace-json",
    ".db3": "rosbag2",
    ".mcap": "mcap",
}


def load_trace(path: Path | str, *, fmt: str | None = None) -> RobotCommandTrace:
    """Load a robot command trace from a supported file format.

    Parameters
    ----------
    path:
        Path to the trace file.
    fmt:
        Format override: "atlas-trace-json", "rosbag2", or "mcap".
        If None, inferred from the file extension.

    Returns
    -------
    RobotCommandTrace
        Validated trace with sequence analysis applied.

    Raises
    ------
    AtlasTraceAdapterError
        If the file cannot be parsed, required fields are missing,
        or an unsupported format is requested without its dependency.
    """
    path = Path(path)
    if not path.exists():
        raise AtlasTraceAdapterError(f"trace file not found: {path}")

    if fmt is None:
        fmt = _EXTENSION_MAP.get(path.suffix.lower())
        if fmt is None:
            raise AtlasTraceAdapterError(
                f"cannot infer trace format from extension {path.suffix!r}. "
                "Supported extensions: .json (atlas-trace-json), .db3 (rosbag2), .mcap (mcap). "
                "Pass fmt= explicitly to override."
            )

    loader = _FORMAT_DISPATCH.get(fmt)
    if loader is None:
        raise AtlasTraceAdapterError(
            f"unknown trace format {fmt!r}. "
            f"Supported: {', '.join(_FORMAT_DISPATCH)}"
        )

    return loader(path)


# ---------------------------------------------------------------------------
# Synthetic trace generator (for testing and demo)
# ---------------------------------------------------------------------------

def generate_synthetic_trace(
    *,
    session_id: str | None = None,
    producer_id: str = "synthetic_diff_drive_producer",
    receiver_id: str = "synthetic_motion_controller",
    nominal_count: int = 100,
    stale_count: int = 10,
    fault_count: int = 3,
    command_rate_hz: float = 10.0,
    max_lin_mps: float = 1.5,
    max_ang_rads: float = 1.0,
    seed: int = 20_260_915,
) -> "dict[str, Any]":
    """Generate a synthetic Atlas trace JSON document.

    Returns the trace as a Python dict (can be written to JSON).
    The generated trace contains:
      - nominal_count valid command events
      - stale_count stale command events (timestamp gap > stale threshold)
      - fault_count fault injection events

    Parameters follow the robot_diff_drive_ros2_v0 profile defaults.
    """
    import random
    rng = random.Random(seed)

    if session_id is None:
        # Derive a deterministic UUID from the seed so the same seed always gives the same trace
        session_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))

    interval_us = int(1_000_000 / command_rate_hz)
    stale_gap_us = interval_us * 200  # 200x normal interval -> always stale

    manifest = {
        "schema_version": "1.0",
        "session_id": session_id,
        "producer_id": producer_id,
        "receiver_id": receiver_id,
        "trace_format": "atlas-trace-json",
        "sequence_policy": {
            "sequence_rollover": "monotonic_64",
            "stale_data_age_ms": 500.0,
            "reset_epoch": "controller_start",
            "queue_overflow_behavior": "drop_oldest",
            "invalid_numeric_behavior": "reject",
        },
    }

    events: list[dict[str, Any]] = []
    seq = 0
    timestamp_us = 1_000_000  # start at t=1s

    # Nominal commands
    for _ in range(nominal_count):
        events.append({
            "sequence_number": seq,
            "timestamp_us": timestamp_us,
            "clock_domain_id": "controller_monotonic",
            "event_type": "command",
            "payload": {
                "velocity_lin_mps": round(rng.uniform(0.0, max_lin_mps), 4),
                "velocity_ang_rads": round(rng.uniform(-max_ang_rads, max_ang_rads), 4),
                "controller_state": "nominal",
                "fault_flags": 0,
                "rearm_requested": False,
            },
        })
        seq += 1
        timestamp_us += interval_us

    # Stale commands (large time gap between consecutive commands)
    for i in range(stale_count):
        timestamp_us += stale_gap_us  # gap that exceeds stale_data_age_ms
        events.append({
            "sequence_number": seq,
            "timestamp_us": timestamp_us,
            "clock_domain_id": "controller_monotonic",
            "event_type": "command",
            "payload": {
                "velocity_lin_mps": round(rng.uniform(0.0, max_lin_mps), 4),
                "velocity_ang_rads": round(rng.uniform(-max_ang_rads, max_ang_rads), 4),
                "controller_state": "stale_detected",
                "fault_flags": 0x0001,  # stale flag
                "rearm_requested": False,
            },
        })
        seq += 1
        timestamp_us += interval_us

    # Fault injection events (interspersed after nominal section)
    fault_kinds = ["stale_command", "missing_burst", "corrupt_frame"]
    for i in range(fault_count):
        events.append({
            "sequence_number": seq,
            "timestamp_us": timestamp_us,
            "clock_domain_id": "controller_monotonic",
            "event_type": "fault",
            "payload": {
                "fault_kind": fault_kinds[i % len(fault_kinds)],
                "description": f"Injected fault: {fault_kinds[i % len(fault_kinds)]}",
                "expected_state": "safe_halt",
            },
        })
        seq += 1
        timestamp_us += interval_us

    manifest["event_count"] = len(events)

    return {
        "manifest": manifest,
        "events": events,
    }
