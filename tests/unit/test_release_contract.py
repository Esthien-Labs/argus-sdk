"""Release-contract checks for the public Argus SDK interfaces."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from argus import __version__
from argus.release_cli import main
from argus.packaged_profiles import default_regression_profile_path
from argus.release import (
    V073_INSTALLER_CANDIDATE_TARGETS,
    V073_PLANNED_HOST_TARGETS,
    runtime_info,
)


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_version_matches_package_metadata() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == metadata["project"]["version"] == "0.7.4"


def test_cli_version_reports_runtime_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == f"argus {__version__}"


def test_packaged_default_profile_is_available_without_source_checkout() -> None:
    profile_path = default_regression_profile_path()
    assert profile_path.is_file()
    assert profile_path.name == "robot_diff_drive_ros2_v0.json"


def test_release_contract_declares_all_planned_host_tuples() -> None:
    assert {(target.operating_system, target.architecture) for target in V073_PLANNED_HOST_TARGETS} == {
        ("Windows", "x64"),
        ("Windows", "arm64"),
        ("macOS", "x64"),
        ("macOS", "arm64"),
        ("Linux", "x64"),
        ("Linux", "arm64"),
    }


def test_installer_candidate_scope_is_truthful() -> None:
    assert {(target.operating_system, target.architecture) for target in V073_INSTALLER_CANDIDATE_TARGETS} == {
        ("Windows", "x64"),
        ("Windows", "arm64"),
        ("macOS", "x64"),
        ("macOS", "arm64"),
        ("Linux", "x64"),
        ("Linux", "arm64"),
    }


def test_runtime_info_declares_python_api_and_cli() -> None:
    assert runtime_info()["interfaces"] == ["python_api", "cli"]


def test_runtime_info_labels_the_release_approval_boundary() -> None:
    info = runtime_info()
    assert info["release_status"] == "public_beta"
    assert "Public beta release" in str(info["evidence_boundary"])
