"""Unit and integration tests for Patent Candidate PAT-001 showcase harness."""

from __future__ import annotations

from pathlib import Path
from argus.safety.interactive_demo import run_pat001_showcase


def test_pat001_showcase_runs_and_verifies_containment(tmp_path: Path) -> None:
    summary = run_pat001_showcase(
        steps_per_phase=4,
        inject_adversarial_override=True,
        interactive_delay_s=0.0,
        output_dir=tmp_path,
    )

    assert summary["patent_id"] == "PAT-001"
    assert summary["status"] == "VERIFIED"
    assert summary["total_frames_evaluated"] == 20
    assert summary["verified_containment"] is True
    assert summary["hardware_supervisory_vetoes"] > 0
    assert summary["state_distribution"]["NOMINAL"] > 0
    assert summary["state_distribution"]["SAFE_HALT"] > 0

    # Verify report written to disk
    report_file = tmp_path / "pat001_safety_showcase_report.json"
    assert report_file.exists()
    assert report_file.stat().st_size > 100


def test_short_verification_is_explicitly_incomplete(tmp_path: Path) -> None:
    summary = run_pat001_showcase(
        steps_per_phase=2,
        mode="verification",
        output_dir=tmp_path,
    )

    assert summary["status"] == "INCOMPLETE_TEST"
    assert summary["verification_complete"] is False
    assert summary["incomplete_reasons"]


def test_smoke_mode_does_not_claim_verification(tmp_path: Path) -> None:
    summary = run_pat001_showcase(
        steps_per_phase=2,
        mode="smoke",
        output_dir=tmp_path,
    )

    assert summary["status"] == "SMOKE_COMPLETE"
    assert summary["test_mode"] == "smoke"
    assert summary["verification_complete"] is False
