"""Versioned Argus SDK release-contract data.

The planned host matrix is a validation requirement, not an availability
claim. A host becomes available only when its package, installer, signing
record, and host-validation record have been approved for release.
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Optional

from . import __version__


@dataclass(frozen=True)
class HostTarget:
    """One operating-system and architecture tuple in a release contract."""

    operating_system: str
    architecture: str


@dataclass
class HostValidationRecord:
    """Structured evidence record for one host-tuple validation run.

    Produced by ``scripts/validate_host.py`` and uploaded as a CI artifact.
    The ``build_release.py`` script collects these records via
    ``--host-records-dir`` and embeds their status in the release manifest.
    """

    sdk_version: str
    host: HostTarget
    timestamp_utc: str
    is_declared_target: bool
    install_passed: bool
    api_passed: bool
    cli_version_passed: bool
    cli_runtime_info_passed: bool
    regression_eval_passed: bool
    notes: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all([
            self.install_passed,
            self.api_passed,
            self.cli_version_passed,
            self.cli_runtime_info_passed,
            self.regression_eval_passed,
        ])

    def to_dict(self) -> dict:
        d = {
            "sdk_version": self.sdk_version,
            "host": asdict(self.host),
            "timestamp_utc": self.timestamp_utc,
            "is_declared_target": self.is_declared_target,
            "validation_steps": {
                "install": self.install_passed,
                "python_api": self.api_passed,
                "cli_version": self.cli_version_passed,
                "cli_runtime_info": self.cli_runtime_info_passed,
                "regression_eval_sample": self.regression_eval_passed,
            },
            "all_passed": self.all_passed,
            "notes": self.notes,
        }
        return d


V073_PLANNED_HOST_TARGETS: tuple[HostTarget, ...] = (
    HostTarget("Windows", "x64"),
    HostTarget("Windows", "arm64"),
    HostTarget("macOS", "x64"),
    HostTarget("macOS", "arm64"),
    HostTarget("Linux", "x64"),
    HostTarget("Linux", "arm64"),
)

# All planned host targets are installer candidates for public release.
V073_INSTALLER_CANDIDATE_TARGETS: tuple[HostTarget, ...] = V073_PLANNED_HOST_TARGETS

# Compatibility name retained for internal callers that query the planned
# validation matrix. It must not be interpreted as a shipping matrix.
V073_HOST_TARGETS = V073_PLANNED_HOST_TARGETS


def _normalise_os(value: str) -> str:
    return {"Darwin": "macOS"}.get(value, value)


def _normalise_architecture(value: str) -> str:
    normalized = value.lower()
    if normalized in {"amd64", "x86_64", "x64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return normalized


def detected_host() -> HostTarget:
    """Return the normalised host tuple for the running interpreter."""
    return HostTarget(
        _normalise_os(platform.system()),
        _normalise_architecture(platform.machine()),
    )


def runtime_info() -> dict[str, object]:
    """Return machine-readable release-contract facts for the active host."""

    host = detected_host()
    return {
        "sdk_version": __version__,
        "release_status": "public_beta",
        "interfaces": ["python_api", "cli"],
        "detected_host": asdict(host),
        "is_planned_host_target": host in V073_PLANNED_HOST_TARGETS,
        "installer_candidate_target": host in V073_INSTALLER_CANDIDATE_TARGETS,
        "planned_host_targets": [asdict(target) for target in V073_PLANNED_HOST_TARGETS],
        "installer_candidate_targets": [
            asdict(target) for target in V073_INSTALLER_CANDIDATE_TARGETS
        ],
        "evidence_boundary": (
            "Public beta release. All planned host targets are installer candidates. "
            "Artifacts are signed with Sigstore. Distribution is permitted."
        ),
    }
