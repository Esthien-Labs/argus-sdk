"""Upload Argus SDK to PyPI.

This script builds the wheel and uploads it to PyPI using twine.
It requires PyPI credentials to be configured in ~/.pypirc or via
environment variables.

Usage:
    python scripts/upload_to_pypi.py [--test]

Options:
    --test    Upload to TestPyPI instead of PyPI
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "pypi"


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload Argus SDK to PyPI")
    parser.add_argument("--test", action="store_true", help="Upload to TestPyPI")
    args = parser.parse_args()

    # Build the wheel
    print("Building wheel...")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST_DIR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Wheel build failed: {result.stderr}", file=sys.stderr)
        return 1

    # Find the wheel
    wheels = list(DIST_DIR.glob("*.whl"))
    if not wheels:
        print("No wheel found in dist directory", file=sys.stderr)
        return 1

    wheel = wheels[0]
    print(f"Built: {wheel}")

    # Upload to PyPI or TestPyPI
    repository = "testpypi" if args.test else "pypi"
    print(f"Uploading to {repository}...")

    result = subprocess.run(
        [sys.executable, "-m", "twine", "upload", "--repository", repository, str(wheel)],
        cwd=ROOT,
    )

    if result.returncode != 0:
        print("Upload failed", file=sys.stderr)
        return 1

    print(f"Successfully uploaded {wheel.name} to {repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
