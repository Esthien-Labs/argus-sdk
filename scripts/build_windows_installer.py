"""Build a Windows installer from a validated PyInstaller onedir payload."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = ROOT / "packaging" / "windows" / "argus-sdk.nsi"
LICENSE_FILE = ROOT / "LICENSE"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--payload", type=Path, required=True, help="PyInstaller executable payload")
    result.add_argument("--arch", choices=("x64", "arm64"), required=True, help="Payload architecture")
    result.add_argument("--version", default="0.7.4", help="SDK version used in installer metadata")
    result.add_argument("--out", type=Path, required=True, help="Installer executable output path")
    result.add_argument("--makensis", type=Path, default=None, help="Path to makensis.exe")
    return result


def default_makensis() -> Path:
    configured = os.environ.get("MAKENSIS")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Program Files (x86)\NSIS\makensis.exe"),
        Path(r"C:\Program Files\NSIS\makensis.exe"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("makensis.exe was not found. Install NSIS or set MAKENSIS.")


def main() -> int:
    args = parser().parse_args()
    payload = args.payload.resolve()
    if not payload.is_file() or payload.name.lower() != "argus.exe":
        raise FileNotFoundError(f"expected PyInstaller executable named argus.exe at {payload}")
    if not INSTALLER_SOURCE.is_file() or not LICENSE_FILE.is_file():
        raise FileNotFoundError("installer source or license file is missing")

    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    makensis = args.makensis.resolve() if args.makensis else default_makensis()
    command = [
        str(makensis),
        f"/DARGUS_PAYLOAD_EXE={payload}",
        f"/DARGUS_TARGET_ARCH={args.arch}",
        f"/DARGUS_VERSION={args.version}",
        f"/DARGUS_OUTFILE={output}",
        f"/DARGUS_LICENSE_FILE={LICENSE_FILE}",
        str(INSTALLER_SOURCE),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("NSIS did not produce the requested installer")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
