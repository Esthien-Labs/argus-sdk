"""Standalone Argus SDK host-tuple validation script.

Runs the five required checks for one host tuple and writes a structured
``host_validation_record.json`` to the declared output directory.

Usage (run on the target host after installing the package):

    python scripts/validate_host.py --out out/host-validation

The script is intentionally self-contained: it uses only the stdlib plus the
``argus`` package. It does not require any test framework.

Exit codes:
    0  all five checks passed
    1  one or more checks failed (details in the JSON record)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the installed package to get version and release helpers.
# ---------------------------------------------------------------------------
try:
    import argus
    from argus.release import (
        HostValidationRecord,
        V073_HOST_TARGETS,
        detected_host,
    )

    _import_ok = True
except Exception as exc:  # noqa: BLE001
    _import_ok = False
    _import_error = str(exc)


def _run(cmd: list[str]) -> tuple[bool, str]:
    """Run a subprocess command; return (passed, combined output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_install() -> tuple[bool, str]:
    """Verify the package imports and exposes the expected version."""
    if not _import_ok:
        return False, f"import failed: {_import_error}"
    try:
        assert argus.__version__ == "0.7.4", f"unexpected version: {argus.__version__}"
        return True, f"version={argus.__version__}"
    except AssertionError as exc:
        return False, str(exc)


def _check_api() -> tuple[bool, str]:
    """Verify the public Python API surface is importable."""
    if not _import_ok:
        return False, "package not importable"
    try:
        from argus import (  # noqa: F401
            ConfidenceCoupledSafetyEnvelope,
            ProfileCompiler,
            CapabilityManifest,
            CapabilityNegotiator,
            NegotiationPolicy,
            ActuatorCommand,
            EnvelopeState,
            Prediction,
            SafetyConfig,
            SignalQuality,
            SignalQualityGate,
        )
        return True, "all public API symbols importable"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _release_command(*arguments: str) -> tuple[bool, str]:
    """Run the installed release command before any module fallback.

    The ``argus`` console entry point is the supported command-line boundary.
    The module form remains a development fallback only, so package validation
    exercises the same command users receive from an installer.
    """

    ok, output = _run(["argus", *arguments])
    if ok:
        return ok, output
    return _run([sys.executable, "-m", "argus", *arguments])


def _check_cli_version() -> tuple[bool, str]:
    """Verify ``argus --version`` exits 0 and contains the expected version."""
    ok, output = _release_command("--version")
    if ok and "0.7.4" in output:
        return True, output
    return False, output or "empty output"


def _check_cli_runtime_info() -> tuple[bool, str]:
    """Verify ``argus runtime-info`` exits 0 and returns valid JSON."""
    ok, output = _release_command("runtime-info")
    if not ok:
        return False, output
    try:
        data = json.loads(output)
        assert "sdk_version" in data and "detected_host" in data
        return True, f"sdk_version={data['sdk_version']} is_planned_host_target={data.get('is_planned_host_target')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"JSON parse error: {exc}\noutput: {output[:400]}"


def _check_regression_eval(out_dir: Path) -> tuple[bool, str]:
    """Verify ``argus regression-eval --sample`` exits 0."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_out = out_dir / "regression-eval-sample"
    ok, output = _release_command(
        "regression-eval", "--sample", "--out", str(sample_out)
    )
    return ok, output[:400] if output else "no output"


def validate(out_dir: Path) -> HostValidationRecord:
    """Run all checks and return a populated HostValidationRecord."""
    out_dir.mkdir(parents=True, exist_ok=True)

    host = detected_host() if _import_ok else None
    from argus.release import HostTarget  # type: ignore[import]
    if host is None:
        import platform

        def _norm_os(v: str) -> str:
            return {"Darwin": "macOS"}.get(v, v)

        def _norm_arch(v: str) -> str:
            n = v.lower()
            if n in {"amd64", "x86_64", "x64"}:
                return "x64"
            if n in {"arm64", "aarch64"}:
                return "arm64"
            return n

        host = HostTarget(_norm_os(platform.system()), _norm_arch(platform.machine()))

    notes: list[str] = []

    install_ok, note = _check_install()
    notes.append(f"install: {note}")

    api_ok, note = _check_api()
    notes.append(f"python_api: {note}")

    cli_ver_ok, note = _check_cli_version()
    notes.append(f"cli_version: {note}")

    cli_rt_ok, note = _check_cli_runtime_info()
    notes.append(f"cli_runtime_info: {note}")

    reg_ok, note = _check_regression_eval(out_dir)
    notes.append(f"regression_eval: {note}")

    return HostValidationRecord(
        sdk_version="0.7.4",
        host=host,
        timestamp_utc=datetime.now(UTC).isoformat(),
        is_declared_target=host in V073_HOST_TARGETS if _import_ok else False,
        install_passed=install_ok,
        api_passed=api_ok,
        cli_version_passed=cli_ver_ok,
        cli_runtime_info_passed=cli_rt_ok,
        regression_eval_passed=reg_ok,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the installed Argus SDK on this host and write a structured evidence record."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/host-validation"),
        help="Directory to write host_validation_record.json",
    )
    args = parser.parse_args(argv)

    out_dir: Path = args.out.resolve()
    print(f"Argus SDK host validation - writing record to {out_dir}")
    print()

    record = validate(out_dir)

    record_path = out_dir / "host_validation_record.json"
    record_path.write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    status = "PASS" if record.all_passed else "FAIL"
    print(f"Host:    {record.host.operating_system} / {record.host.architecture}")
    print(f"Version: {record.sdk_version}")
    print(f"Status:  {status}")
    print()
    for note in record.notes:
        marker = "  [ok]" if any(
            step in note and "FAIL" not in note.upper()
            for step in ("install:", "python_api:", "cli_version:", "cli_runtime_info:", "regression_eval:")
        ) else "  [!] "
        print(f"{marker} {note}")
    print()
    print(f"Record: {record_path}")
    return 0 if record.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
