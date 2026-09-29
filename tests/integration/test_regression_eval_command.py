"""Integration tests for the Argus regression-eval command (Stage 0C acceptance gate).

Acceptance criteria:
  - All output files present
  - All standard citations present
  - All mandatory sections present
  - Evidence boundary statement complete
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.adapters.robot_command import generate_synthetic_trace, load_trace
from argus.regression import (
    load_controller_regression_profile,
    run_regression_evaluation,
    write_regression_report,
)
from argus.regression.pipeline import RegressionEvaluationError


ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "config" / "profiles" / "regression"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ros2_profile_path() -> Path:
    return PROFILES_DIR / "robot_diff_drive_ros2_v0.json"


@pytest.fixture()
def automotive_profile_path() -> Path:
    return PROFILES_DIR / "automotive_ecu_can_v0.json"


@pytest.fixture()
def cobot_profile_path() -> Path:
    return PROFILES_DIR / "industrial_cobot_joint_v0.json"


@pytest.fixture()
def synthetic_trace_path(tmp_path: Path) -> Path:
    doc = generate_synthetic_trace(nominal_count=100, stale_count=10, fault_count=3)
    trace_file = tmp_path / "test_trace.json"
    trace_file.write_text(json.dumps(doc), encoding="utf-8")
    return trace_file


@pytest.fixture()
def evaluation_result(synthetic_trace_path: Path, ros2_profile_path: Path):
    trace = load_trace(synthetic_trace_path)
    profile = load_controller_regression_profile(ros2_profile_path)
    return run_regression_evaluation(
        trace=trace,
        profile=profile,
        trace_path=synthetic_trace_path,
        profile_path=ros2_profile_path,
        evidence_class="digital_source_verification",
    )


@pytest.fixture()
def report_paths(evaluation_result, tmp_path: Path) -> dict[str, Path]:
    return write_regression_report(evaluation_result, tmp_path / "regression-eval")


# ---------------------------------------------------------------------------
# 1. All output files are present
# ---------------------------------------------------------------------------

class TestOutputFilesPresent:
    def test_json_report_present(self, report_paths: dict[str, Path]) -> None:
        assert report_paths["json"].exists()
        assert report_paths["json"].name == "regression_report.json"

    def test_md_report_present(self, report_paths: dict[str, Path]) -> None:
        assert report_paths["md"].exists()
        assert report_paths["md"].name == "regression_report.md"

    def test_html_report_present(self, report_paths: dict[str, Path]) -> None:
        assert report_paths["html"].exists()
        assert report_paths["html"].name == "regression_report.html"

    def test_manifest_present(self, report_paths: dict[str, Path]) -> None:
        assert report_paths["manifest"].exists()
        assert report_paths["manifest"].name == "evidence_manifest.json"


# ---------------------------------------------------------------------------
# 2. Evidence boundary statement is complete and first
# ---------------------------------------------------------------------------

class TestEvidenceBoundaryStatement:
    def test_json_has_evidence_boundary_section(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "evidence_boundary" in report

    def test_evidence_boundary_has_what_this_proves(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        eb = report["evidence_boundary"]
        assert "what_this_proves" in eb
        assert isinstance(eb["what_this_proves"], str)
        assert len(eb["what_this_proves"]) > 50  # non-trivial statement

    def test_evidence_boundary_has_does_not_prove(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        eb = report["evidence_boundary"]
        assert "what_this_does_not_prove" in eb
        assert len(eb["what_this_does_not_prove"]) >= 3

    def test_evidence_boundary_has_applicable_standards(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        eb = report["evidence_boundary"]
        assert "applicable_standards" in eb
        assert len(eb["applicable_standards"]) >= 1

    def test_markdown_starts_with_evidence_boundary(self, report_paths: dict[str, Path]) -> None:
        md = report_paths["md"].read_text(encoding="utf-8")
        assert "Evidence Boundary Statement" in md
        # Evidence boundary should appear before Section 2
        eb_pos = md.index("Evidence Boundary Statement")
        baseline_pos = md.index("Baseline Behavior")
        assert eb_pos < baseline_pos

    def test_html_has_evidence_boundary(self, report_paths: dict[str, Path]) -> None:
        html = report_paths["html"].read_text(encoding="utf-8")
        assert "Evidence Boundary Statement" in html
        assert "what_this_proves" in html or "What this evaluation proves" in html


# ---------------------------------------------------------------------------
# 3. All mandatory sections present
# ---------------------------------------------------------------------------

class TestMandatorySections:
    def test_json_has_baseline_behavior_section(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "baseline_behavior" in report

    def test_json_has_fault_matrix_section(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "fault_matrix" in report

    def test_json_has_comparison_section(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "comparison" in report

    def test_json_has_limitations_section(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "limitations" in report
        assert len(report["limitations"]) >= 3


# ---------------------------------------------------------------------------
# 4. All standard citations present in evidence manifest
# ---------------------------------------------------------------------------

class TestStandardsCitations:
    def test_manifest_has_applicable_standards(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        assert "applicable_standards" in manifest
        assert len(manifest["applicable_standards"]) >= 1

    def test_manifest_standards_have_section_fields(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        for citation in manifest["applicable_standards"]:
            assert "standard" in citation
            assert "section" in citation
            assert "coverage" in citation

    def test_manifest_has_source_hashes(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        assert "sources" in manifest
        sources = manifest["sources"]
        assert "trace_sha256" in sources
        assert "profile_sha256" in sources
        assert "atlas_version" in sources

    def test_manifest_has_output_hashes(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        assert "outputs" in manifest
        outputs = manifest["outputs"]
        assert "regression_report_json_sha256" in outputs
        assert "regression_report_md_sha256" in outputs
        assert "regression_report_html_sha256" in outputs

    def test_hashes_are_valid_sha256_format(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        for key, val in manifest["outputs"].items():
            assert len(val) == 64, f"{key} hash must be 64 hex characters"
            assert all(c in "0123456789abcdef" for c in val), f"{key} must be lowercase hex"


# ---------------------------------------------------------------------------
# 5. Fault matrix correctness
# ---------------------------------------------------------------------------

class TestFaultMatrix:
    def test_all_9_ros2_faults_evaluated(self, evaluation_result) -> None:
        assert evaluation_result.fault_cases_total == 9

    def test_all_fault_cases_pass_with_atlas(self, evaluation_result) -> None:
        assert evaluation_result.all_fault_cases_passed, (
            f"Expected all fault cases to pass. Failed: "
            f"{[fr.fault_id for fr in evaluation_result.fault_results if not fr.atlas_pass]}"
        )

    def test_no_trials_dropped(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        total = report["fault_matrix"]["total"]
        passed = report["fault_matrix"]["passed"]
        failed = report["fault_matrix"]["failed"]
        assert passed + failed == total, "All fault cases must be reported; none may be dropped"

    def test_fault_matrix_has_per_case_results(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        cases = report["fault_matrix"]["cases"]
        assert len(cases) == report["fault_matrix"]["total"]
        for case in cases:
            assert "fault_id" in case
            assert "fault_kind" in case
            assert "expected_state" in case
            assert "baseline_observed_state" in case
            assert "atlas_observed_state" in case
            assert "atlas_pass" in case


# ---------------------------------------------------------------------------
# 6. False-stop rate is reported explicitly
# ---------------------------------------------------------------------------

class TestFalseStopRate:
    def test_comparison_has_false_stop_rate(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        assert "false_stop_rate" in report["comparison"]

    def test_atlas_false_stop_rate_is_low(self, evaluation_result) -> None:
        # On a synthetic trace with only valid nominal commands + declared stale/faults,
        # Atlas should have near-zero false stop rate on nominal commands
        assert evaluation_result.atlas_false_stop_rate < 0.05, (
            f"False-stop rate {evaluation_result.atlas_false_stop_rate:.4f} too high"
        )

    def test_false_stop_rate_in_manifest_summary(self, report_paths: dict[str, Path]) -> None:
        manifest = json.loads(report_paths["manifest"].read_text(encoding="utf-8"))
        summary = manifest.get("summary", {})
        assert "atlas_false_stop_rate" in summary


# ---------------------------------------------------------------------------
# 7. Latency labels state they are not worst-case bounds
# ---------------------------------------------------------------------------

class TestLatencyLabeling:
    def test_json_latency_labeled_as_host_measured(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        baseline = report["baseline_behavior"]
        assert baseline["latency_label"] == "host_measured_not_embedded_not_worst_case_bound"

    def test_comparison_max_latency_labeled_not_worst_case(
        self, report_paths: dict[str, Path]
    ) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        cmp = report["comparison"]
        assert "finite_observed_maximum_not_worst_case" in cmp["max_latency_us"]["label"]

    def test_limitations_mention_host_measured(self, report_paths: dict[str, Path]) -> None:
        report = json.loads(report_paths["json"].read_text(encoding="utf-8"))
        all_limitations = " ".join(report["limitations"]).lower()
        assert "host" in all_limitations or "workstation" in all_limitations


# ---------------------------------------------------------------------------
# 8. Multiple profiles work end-to-end
# ---------------------------------------------------------------------------

class TestMultipleProfiles:
    def test_automotive_profile_end_to_end(
        self, tmp_path: Path, automotive_profile_path: Path
    ) -> None:
        """Automotive ECU profile uses CAN torque commands; trace uses diff-drive.
        Pipeline should run and produce reports even when profile type differs from trace type.
        """
        doc = generate_synthetic_trace(nominal_count=50, stale_count=5, fault_count=2)
        trace_file = tmp_path / "auto_trace.json"
        trace_file.write_text(json.dumps(doc), encoding="utf-8")

        trace = load_trace(trace_file)
        profile = load_controller_regression_profile(automotive_profile_path)
        result = run_regression_evaluation(
            trace=trace, profile=profile,
            trace_path=trace_file, profile_path=automotive_profile_path,
        )
        paths = write_regression_report(result, tmp_path / "auto-eval")
        assert all(p.exists() for p in paths.values())

    def test_cobot_profile_end_to_end(
        self, tmp_path: Path, cobot_profile_path: Path
    ) -> None:
        doc = generate_synthetic_trace(nominal_count=50, stale_count=5, fault_count=2)
        trace_file = tmp_path / "cobot_trace.json"
        trace_file.write_text(json.dumps(doc), encoding="utf-8")

        trace = load_trace(trace_file)
        profile = load_controller_regression_profile(cobot_profile_path)
        result = run_regression_evaluation(
            trace=trace, profile=profile,
            trace_path=trace_file, profile_path=cobot_profile_path,
        )
        paths = write_regression_report(result, tmp_path / "cobot-eval")
        assert all(p.exists() for p in paths.values())


# ---------------------------------------------------------------------------
# 9. Empty trace raises error
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_trace_raises(self, tmp_path: Path, ros2_profile_path: Path) -> None:
        doc = generate_synthetic_trace(nominal_count=0, stale_count=0, fault_count=0)
        trace_file = tmp_path / "empty_trace.json"
        trace_file.write_text(json.dumps(doc), encoding="utf-8")

        trace = load_trace(trace_file)
        profile = load_controller_regression_profile(ros2_profile_path)
        with pytest.raises(RegressionEvaluationError, match="no COMMAND events"):
            run_regression_evaluation(
                trace=trace, profile=profile,
                trace_path=trace_file, profile_path=ros2_profile_path,
            )

    def test_invalid_evidence_class_raises(
        self, synthetic_trace_path: Path, ros2_profile_path: Path
    ) -> None:
        trace = load_trace(synthetic_trace_path)
        profile = load_controller_regression_profile(ros2_profile_path)
        with pytest.raises(RegressionEvaluationError, match="evidence_class"):
            run_regression_evaluation(
                trace=trace, profile=profile,
                trace_path=synthetic_trace_path, profile_path=ros2_profile_path,
                evidence_class="made_up_class",
            )
