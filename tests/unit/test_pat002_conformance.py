"""Unit and integration tests for Patent Candidate PAT-002 conformance harness."""

from __future__ import annotations

from pathlib import Path
from argus.compiler.conformance import (
    CrossDomainConformanceHarness,
    run_pat002_verification,
)

PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "profiles"


def test_pat002_all_registered_profiles_conform(tmp_path: Path) -> None:
    summary = run_pat002_verification(
        profiles_dir=PROFILES_DIR,
        output_dir=tmp_path,
    )

    assert summary["patent_id"] == "PAT-002"
    assert summary["profiles_evaluated"] >= 3  # assistive_controller_v0, bionic_wrist_v1, exoskeleton_gait_v0
    assert summary["all_conformance_passed"] is True

    # Verify that generated artifacts for each profile exist
    for rep in summary["reports"]:
        prof_dir = tmp_path / rep["profile_id"]
        assert prof_dir.exists()
        assert (prof_dir / "simulation_profile.json").exists()
        assert (prof_dir / "firmware_profile.h").exists()
        assert (prof_dir / "rtl_profile.vh").exists()
        assert (prof_dir / "fault_test_vectors.json").exists()
        assert (prof_dir / "profile_manifest.sha256").exists()


def test_pat002_single_profile_conformance() -> None:
    harness = CrossDomainConformanceHarness()
    report = harness.evaluate_profile(PROFILES_DIR / "bionic_wrist_v1.json")
    assert report.profile_id == "bionic_wrist_v1"
    assert report.conformance_passed is True
    assert len(report.checks) >= 6
