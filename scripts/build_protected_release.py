"""Build script for Argus SDK with Cython source protection.

This script compiles IP-dense Python modules to native extensions before
building the wheel. The compiled .pyd/.so files replace the .py files in
the built distribution.

Usage:
    python scripts/build_protected_release.py --out dist/release

Output:
    dist/release/argus_sdk-0.7.4-py3-none-any.whl  (with compiled extensions)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "cython_protected"


def compile_cython_modules() -> None:
    """Compile IP-dense Python modules to native extensions."""
    # Check if Cython is available
    try:
        import Cython
    except ImportError:
        print("Installing Cython...")
        subprocess.run([sys.executable, "-m", "pip", "install", "cython>=3.0"], check=True)

    from Cython.Build import cythonize
    from setuptools import Extension
    from setuptools.command.build_ext import build_ext
    from distutils.dist import Distribution

    # IP-dense modules to compile
    modules = [
        ("argus.safety.envelope", "src/argus/safety/envelope.py"),
        ("argus.compiler.compiler", "src/argus/compiler/compiler.py"),
        ("argus.compiler.schema", "src/argus/compiler/schema.py"),
    ]

    # Create build directory
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Copy source files to build directory with relative paths
    for module_name, source_path in modules:
        source = ROOT / source_path
        if not source.exists():
            print(f"Warning: {source} not found, skipping", file=sys.stderr)
            continue

        # Create the .pyx file (copy of .py)
        pyx_file = BUILD_DIR / f"{module_name.replace('.', '_')}.pyx"
        shutil.copy(source, pyx_file)

        # Create extension
        ext = Extension(
            module_name,
            sources=[str(pyx_file)],
            language="c++",
            extra_compile_args=["/O2" if os.name == "nt" else "-O3"],
        )

        # Build the extension
        dist = Distribution({"ext_modules": [ext]})
        cmd = build_ext(dist)
        cmd.build_lib = str(BUILD_DIR)
        cmd.build_temp = str(BUILD_DIR / "temp")
        cmd.ensure_finalized()
        cmd.run()

        # Find and copy the built extension
        system = platform.system()
        if system == "Windows":
            pattern = "*.pyd"
        elif system == "Darwin":
            pattern = "*.dylib"
        else:
            pattern = "*.so"

        # Search recursively in build directory
        for lib_file in BUILD_DIR.rglob(pattern):
            # Determine target location based on module name
            # argus.safety.envelope -> src/argus/safety/envelope.cp311-win_amd64.pyd
            parts = module_name.split(".")[1:]  # Remove "argus" prefix
            target_dir = ROOT / "src" / "argus"
            for part in parts[:-1]:
                target_dir = target_dir / part
            target_dir.mkdir(parents=True, exist_ok=True)

            # Use the original module name with platform suffix
            target_file = target_dir / f"{parts[-1]}{lib_file.suffix}"
            shutil.copy(lib_file, target_file)
            print(f"Built: {target_file}")


def build_wheel(output_dir: Path) -> None:
    """Build the wheel with compiled extensions.

    Before building, this removes the .py source files for compiled modules
    so they are not included in the wheel. Only the compiled .pyd/.so files
    are packaged.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Modules that have been compiled to native code
    # Move .py files aside so they are not included in the wheel
    compiled_modules = [
        ("src/argus/safety/envelope.py", "src/argus/safety/envelope.py.bak"),
        ("src/argus/compiler/compiler.py", "src/argus/compiler/compiler.py.bak"),
        ("src/argus/compiler/schema.py", "src/argus/compiler/schema.py.bak"),
    ]

    moved_files = []
    for source_rel, backup_rel in compiled_modules:
        source = ROOT / source_rel
        backup = ROOT / backup_rel
        if source.exists():
            shutil.move(source, backup)
            moved_files.append((source, backup))
            print(f"Moved: {source} -> {backup}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(output_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Wheel build failed: {result.stderr}", file=sys.stderr)
            raise RuntimeError("Wheel build failed")

        print(f"Wheel built: {output_dir}")

    finally:
        # Restore .py files and clean up .pyd files from source directory
        # (they would shadow the .py files during development/testing)
        for source, backup in moved_files:
            if backup.exists():
                shutil.move(backup, source)
                print(f"Restored: {backup} -> {source}")

        # Clean up compiled extensions from source directory
        import platform
        system = platform.system()
        if system == "Windows":
            pattern = "*.pyd"
        elif system == "Darwin":
            pattern = "*.dylib"
        else:
            pattern = "*.so"

        for ext_file in (ROOT / "src").rglob(pattern):
            ext_file.unlink()
            print(f"Cleaned: {ext_file}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build protected Argus SDK release")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "protected")
    args = parser.parse_args()

    print("Step 1: Compiling Cython extensions...")
    compile_cython_modules()

    print("Step 2: Building wheel...")
    build_wheel(args.out.resolve())

    print("Done. Protected wheel contains compiled extensions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
