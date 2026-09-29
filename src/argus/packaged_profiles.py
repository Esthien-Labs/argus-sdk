"""Access packaged Argus reference profiles without a source checkout."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def packaged_profile_path(profile_name: str) -> Path:
    """Return the installed filesystem path for a packaged reference profile."""

    resource = resources.files("argus.resources").joinpath("profiles").joinpath(profile_name)
    if not resource.is_file():
        raise FileNotFoundError(f"Packaged Argus profile not found: {profile_name}")
    return Path(str(resource))


def default_regression_profile_path() -> Path:
    """Return the default profile used by ``argus regression-eval``."""

    return packaged_profile_path("robot_diff_drive_ros2_v0.json")
