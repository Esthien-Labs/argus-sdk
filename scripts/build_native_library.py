"""Build the Argus native safety-envelope library from the C ABI source.

Compiles ``src/argus/abi/argus_native.c`` into the platform shared library that
the language wrappers bind to:

    Windows   argus.dll
    Linux     libargus.so
    macOS     libargus.dylib

Usage:
    python scripts/build_native_library.py [--out <dir>] [--compiler auto|gcc|clang|cl]

The build fails loudly if no C compiler is found or the compile step errors.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "argus" / "abi" / "argus_native.c"
HEADER_DIR = ROOT / "src" / "argus" / "abi"
DEF_FILE = HEADER_DIR / "argus.def"


def library_name(system: str) -> str:
    if system == "Windows":
        return "argus.dll"
    if system == "Darwin":
        return "libargus.dylib"
    return "libargus.so"


VSWHERE = Path(
    "C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
)


def find_msvc_devcmd() -> Path | None:
    """Locate VsDevCmd.bat for the latest Visual Studio build tools install."""
    if not VSWHERE.is_file():
        return None
    result = subprocess.run(
        [str(VSWHERE), "-latest", "-products", "*", "-property", "installationPath"],
        capture_output=True,
        text=True,
    )
    install = result.stdout.strip().splitlines()
    if not install:
        return None
    devcmd = Path(install[0]) / "Common7" / "Tools" / "VsDevCmd.bat"
    return devcmd if devcmd.is_file() else None


def find_compiler(choice: str) -> tuple[str, Path | None]:
    """Return (compiler tag, msvc_devcmd). msvc_devcmd is set only for MSVC."""
    if choice == "cl":
        devcmd = find_msvc_devcmd()
        if devcmd is None:
            raise RuntimeError("MSVC requested but VsDevCmd.bat was not found")
        return "cl", devcmd
    if choice in {"gcc", "clang"}:
        exe = shutil.which(choice)
        if exe is None:
            raise RuntimeError(f"requested compiler {choice!r} not found on PATH")
        return choice, None
    # auto: prefer a working 64-bit compiler. On Windows prefer MSVC.
    if platform.system() == "Windows":
        devcmd = find_msvc_devcmd()
        if devcmd is not None:
            return "cl", devcmd
    for name in ("gcc", "clang"):
        if shutil.which(name) is not None:
            return name, None
    devcmd = find_msvc_devcmd()
    if devcmd is not None:
        return "cl", devcmd
    raise RuntimeError("no C compiler found (looked for MSVC, gcc, clang)")


def build_command(compiler: str, system: str, out: Path) -> list[str]:
    name = out.name
    if compiler == "cl":
        # MSVC: /LD builds a DLL, /Fe sets the output file. The .def file lists
        # the exported C ABI symbols; MSVC does not export them otherwise.
        return ["cl", "/nologo", "/LD", "/O2", f"/Fe:{name}", str(SOURCE), str(DEF_FILE)]
    if system == "Darwin":
        return [compiler, "-dynamiclib", "-O2", "-fPIC", "-o", name, str(SOURCE), "-lm"]
    return [compiler, "-shared", "-O2", "-fPIC", "-o", name, str(SOURCE), "-lm"]


def run_build(cmd: list[str], devcmd: Path | None, cwd: Path) -> subprocess.CompletedProcess:
    """Run the compiler, entering the MSVC environment first when required."""
    if devcmd is None:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    # Enter the MSVC developer environment via a temporary batch file so the
    # compiler sees INCLUDE and LIB.
    bat = cwd / "_build_native.bat"
    lines = [
        "@echo off",
        f'call "{devcmd}" -arch=amd64 -host_arch=amd64 || exit /b 1',
        " ".join(cmd),
    ]
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    try:
        return subprocess.run(["cmd", "/c", str(bat)], cwd=cwd, capture_output=True, text=True)
    finally:
        bat.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Argus native library.")
    parser.add_argument("--out", type=Path, default=HEADER_DIR, help="Output directory.")
    parser.add_argument("--compiler", default="auto", choices=["auto", "gcc", "clang", "cl"])
    args = parser.parse_args(argv)

    if not SOURCE.is_file():
        print(f"source not found: {SOURCE}", file=sys.stderr)
        return 1

    system = platform.system()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / library_name(system)

    tag, devcmd = find_compiler(args.compiler)
    cmd = build_command(tag, system, out_path)

    print(f"compiler: {tag}")
    print(f"output:   {out_path}")
    result = run_build(cmd, devcmd, out_dir)
    if result.returncode != 0:
        print("native library build failed:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    if not out_path.is_file():
        print(f"build reported success but {out_path} is missing", file=sys.stderr)
        return 1

    if tag == "cl":
        # Remove MSVC intermediates; keep the import library used to link consumers.
        for junk in (out_dir / "argus.exp", out_dir / f"{SOURCE.stem}.obj"):
            junk.unlink(missing_ok=True)

    print(f"built {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
