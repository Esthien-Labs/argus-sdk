"""Atlas adapters - convert external trace formats to the Atlas internal representation.

Supported formats:
  atlas-trace-json   Native Atlas JSON trace (primary, no external dependency)
  rosbag2            ROS 2 bag via sqlite3 (stdlib)
  mcap               MCAP binary format (requires `mcap` package; graceful error if absent)

All adapters produce a RobotCommandTrace with a validated TraceManifest.
"""

from .robot_command import (
    AtlasTraceAdapterError,
    DifferentialDrivePayload,
    EventType,
    InvalidNumericBehavior,
    QueueOverflowBehavior,
    RobotCommandEvent,
    RobotCommandTrace,
    SequencePolicy,
    SequenceRolloverPolicy,
    TorquePayload,
    TraceManifest,
    generate_synthetic_trace,
    load_trace,
)

__all__ = [
    "AtlasTraceAdapterError",
    "DifferentialDrivePayload",
    "EventType",
    "InvalidNumericBehavior",
    "QueueOverflowBehavior",
    "RobotCommandEvent",
    "RobotCommandTrace",
    "SequencePolicy",
    "SequenceRolloverPolicy",
    "TorquePayload",
    "TraceManifest",
    "generate_synthetic_trace",
    "load_trace",
]
