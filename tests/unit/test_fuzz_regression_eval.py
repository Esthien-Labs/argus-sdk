"""Malformed-input fuzz tests for the argus regression-eval public CLI path.

Covers the two public input surfaces:
  - --trace: user-supplied trace file (JSON, extension detection, missing fields)
  - --profile: user-supplied regression profile file

Every case must exit with a non-zero status and must not produce a traceback
or unhandled exception in stderr. The CLI catches (OSError, ValueError) and
exits 2 - anything else is a bug.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ARGUS = [sys.executable, "-m", "argus"]


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*ARGUS, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
    )


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Trace file: malformed JSON and structural violations
# ---------------------------------------------------------------------------

class TestTraceMalformedJson:
    def test_empty_file(self, tmp_path: Path) -> None:
        f = write(tmp_path / "empty.json", "")
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_not_json(self, tmp_path: Path) -> None:
        f = write(tmp_path / "bad.json", "this is not json at all {{{")
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_json_array_root(self, tmp_path: Path) -> None:
        f = write(tmp_path / "arr.json", json.dumps([1, 2, 3]))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_json_null_root(self, tmp_path: Path) -> None:
        f = write(tmp_path / "null.json", "null")
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_json_string_root(self, tmp_path: Path) -> None:
        f = write(tmp_path / "str.json", '"hello"')
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_json_number_root(self, tmp_path: Path) -> None:
        f = write(tmp_path / "num.json", "42")
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_truncated_json(self, tmp_path: Path) -> None:
        f = write(tmp_path / "trunc.json", '{"manifest": {"session_id": "abc",')
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


class TestTraceMissingFields:
    def _base(self) -> dict:
        return {
            "manifest": {
                "session_id": "test-session",
                "producer_id": "p",
                "receiver_id": "r",
            },
            "events": [],
        }

    def test_no_manifest(self, tmp_path: Path) -> None:
        f = write(tmp_path / "no_manifest.json", json.dumps({"events": []}))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_no_events(self, tmp_path: Path) -> None:
        f = write(tmp_path / "no_events.json", json.dumps({"manifest": {"session_id": "s"}}))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_events_not_array(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = "not_an_array"
        f = write(tmp_path / "ev_str.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_events_null(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = None
        f = write(tmp_path / "ev_null.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_event_not_object(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = ["not_an_object"]
        f = write(tmp_path / "ev_item_str.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_event_missing_timestamp(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1}}]
        f = write(tmp_path / "ev_no_ts.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_event_missing_payload(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": 1000000}]
        f = write(tmp_path / "ev_no_payload.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


class TestTraceBadValues:
    def _base(self) -> dict:
        return {
            "manifest": {
                "session_id": "test-session",
                "producer_id": "p",
                "receiver_id": "r",
            },
            "events": [],
        }

    def test_timestamp_string(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": "not_a_number", "payload": {}}]
        f = write(tmp_path / "ts_str.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_timestamp_negative(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": -999, "payload": {"linear_x_mps": 0.0, "angular_z_radps": 0.0}}]
        f = write(tmp_path / "ts_neg.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_timestamp_float_nan(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": float("nan"), "payload": {}}]
        f = write(tmp_path / "ts_nan.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_payload_not_object(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": 1000000, "payload": "not_an_object"}]
        f = write(tmp_path / "payload_str.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_payload_null(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": 1000000, "payload": None}]
        f = write(tmp_path / "payload_null.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_extremely_large_timestamp(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [{"timestamp_us": 2**63, "payload": {"linear_x_mps": 0.0, "angular_z_radps": 0.0}}]
        f = write(tmp_path / "ts_huge.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_deeply_nested_payload(self, tmp_path: Path) -> None:
        nested: dict = {}
        current = nested
        for i in range(200):
            current["x"] = {}
            current = current["x"]
        doc = self._base()
        doc["events"] = [{"timestamp_us": 1000000, "payload": nested}]
        f = write(tmp_path / "nested.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


class TestTraceFileSystem:
    def test_nonexistent_file(self, tmp_path: Path) -> None:
        r = run_cli("regression-eval", "--trace", str(tmp_path / "ghost.json"), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_directory_as_trace(self, tmp_path: Path) -> None:
        r = run_cli("regression-eval", "--trace", str(tmp_path), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_unknown_extension(self, tmp_path: Path) -> None:
        f = write(tmp_path / "trace.xyz", json.dumps({"manifest": {}, "events": []}))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_uppercase_extension(self, tmp_path: Path) -> None:
        doc = {
            "manifest": {"session_id": "s", "producer_id": "p", "receiver_id": "r"},
            "events": [],
        }
        f = write(tmp_path / "trace.JSON", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        # Should load (extension map is case-insensitive) or fail cleanly
        assert "Traceback" not in r.stderr

    def test_empty_filename(self, tmp_path: Path) -> None:
        r = run_cli("regression-eval", "--trace", "", "--out", str(tmp_path / "out"))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


# ---------------------------------------------------------------------------
# Profile file: malformed inputs
# ---------------------------------------------------------------------------

class TestProfileMalformed:
    def _valid_trace(self, tmp_path: Path) -> Path:
        doc = {
            "manifest": {"session_id": "s", "producer_id": "p", "receiver_id": "r"},
            "events": [
                {
                    "timestamp_us": 1000000,
                    "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1},
                }
            ],
        }
        return write(tmp_path / "trace.json", json.dumps(doc))

    def test_profile_not_found(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--profile", str(tmp_path / "ghost.json"),
            "--out", str(tmp_path / "out"),
        )
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_profile_not_json(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        profile = write(tmp_path / "profile.json", "not json {{{")
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--profile", str(profile),
            "--out", str(tmp_path / "out"),
        )
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_profile_empty(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        profile = write(tmp_path / "profile.json", "")
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--profile", str(profile),
            "--out", str(tmp_path / "out"),
        )
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_profile_array_root(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        profile = write(tmp_path / "profile.json", json.dumps([1, 2, 3]))
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--profile", str(profile),
            "--out", str(tmp_path / "out"),
        )
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_profile_null(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        profile = write(tmp_path / "profile.json", "null")
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--profile", str(profile),
            "--out", str(tmp_path / "out"),
        )
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


# ---------------------------------------------------------------------------
# Output path: malformed or hostile output directories
# ---------------------------------------------------------------------------

class TestOutputPath:
    def _valid_trace(self, tmp_path: Path) -> Path:
        doc = {
            "manifest": {"session_id": "s", "producer_id": "p", "receiver_id": "r"},
            "events": [
                {
                    "timestamp_us": 1000000,
                    "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1},
                }
            ],
        }
        return write(tmp_path / "trace.json", json.dumps(doc))

    def test_output_to_existing_file(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        out_file = write(tmp_path / "blocked", "already a file")
        r = run_cli("regression-eval", "--trace", str(trace), "--out", str(out_file))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr

    def test_output_deeply_nested(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "out"
        r = run_cli("regression-eval", "--trace", str(trace), "--out", str(deep))
        assert "Traceback" not in r.stderr

    def test_output_relative_path(self, tmp_path: Path) -> None:
        trace = self._valid_trace(tmp_path)
        r = run_cli(
            "regression-eval", "--trace", str(trace),
            "--out", "relative_out",
            cwd=tmp_path,
        )
        assert "Traceback" not in r.stderr


# ---------------------------------------------------------------------------
# Large and adversarial payloads
# ---------------------------------------------------------------------------

class TestAdversarialPayloads:
    def _base(self) -> dict:
        return {
            "manifest": {"session_id": "s", "producer_id": "p", "receiver_id": "r"},
            "events": [],
        }

    def test_10000_events(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [
            {"timestamp_us": 1000000 + i * 100, "payload": {"linear_x_mps": 0.1, "angular_z_radps": 0.0}}
            for i in range(10_000)
        ]
        f = write(tmp_path / "large.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert "Traceback" not in r.stderr

    def test_event_with_extra_unknown_fields(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [
            {
                "timestamp_us": 1000000,
                "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1},
                "unknown_field": "should be ignored or rejected cleanly",
                "another": {"nested": True},
            }
        ]
        f = write(tmp_path / "extra.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert "Traceback" not in r.stderr

    def test_unicode_in_strings(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["manifest"]["session_id"] = "session-\u00e9\u00e8\u00ea-\u4e2d\u6587"
        doc["events"] = [
            {"timestamp_us": 1000000, "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1}}
        ]
        f = write(tmp_path / "unicode.json", json.dumps(doc, ensure_ascii=False))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert "Traceback" not in r.stderr

    def test_null_bytes_in_string(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["manifest"]["session_id"] = "session\x00null"
        doc["events"] = [
            {"timestamp_us": 1000000, "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1}}
        ]
        f = write(tmp_path / "nullbyte.json", json.dumps(doc))
        r = run_cli("regression-eval", "--trace", str(f), "--out", str(tmp_path / "out"))
        assert "Traceback" not in r.stderr

    def test_bom_prefixed_json(self, tmp_path: Path) -> None:
        doc = self._base()
        doc["events"] = [
            {"timestamp_us": 1000000, "payload": {"linear_x_mps": 0.5, "angular_z_radps": 0.1}}
        ]
        path = tmp_path / "bom.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps(doc).encode("utf-8"))
        r = run_cli("regression-eval", "--trace", str(path), "--out", str(tmp_path / "out"))
        assert "Traceback" not in r.stderr
