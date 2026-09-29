"""Build an Argus SDK controlled candidate bundle without authorizing distribution.

The script writes a controlled Python wheel, a declared-dependency inventory,
and a manifest. It deliberately does not create a public source archive, sign,
or upload anything. Signature and product approval remain separate release
gates.

Optional: pass ``--host-records-dir`` to collect per-host
``host_validation_record.json`` files (produced by ``scripts/validate_host.py``
and uploaded as CI artifacts) and embed their status in the release manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dependency_component(requirement: str) -> dict[str, str]:
    """Create a declared-dependency component without resolving a lockfile."""

    name = requirement
    for marker in ("<", ">", "=", "!", "~", ";", "["):
        name = name.split(marker, maxsplit=1)[0]
    normalized_name = name.strip()
    return {
        "type": "library",
        "name": normalized_name,
        "version": requirement[len(normalized_name):].strip() or "unspecified",
        "scope": "required",
    }


def write_declared_dependency_sbom(metadata: dict[str, Any], destination: Path) -> None:
    """Write a CycloneDX-compatible declared-dependency inventory.

    This is intentionally a direct-dependency inventory, not a resolved
    transitive dependency attestation. A publication release must attach a
    resolver-produced SBOM and its approval record.
    """

    project = metadata["project"]
    dependencies = project.get("dependencies", [])
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:argus-sdk-{project['version']}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": project["name"],
                "version": project["version"],
            },
            "properties": [
                {
                    "name": "esthien.sbom.scope",
                    "value": "declared-direct-dependencies-only",
                }
            ],
        },
        "components": [dependency_component(requirement) for requirement in dependencies],
    }
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_host_records(records_dir: Path) -> list[dict[str, Any]]:
    """Load all host_validation_record.json files from ``records_dir``.

    Each CI job uploads its record to a separate directory named by host label.
    This function walks the directory tree and loads every file named
    ``host_validation_record.json``.
    """
    records = []
    for path in sorted(records_dir.rglob("host_validation_record.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: could not load {path}: {exc}", file=sys.stderr)
    return records


def build_release(output: Path, host_records_dir: Path | None = None) -> None:
    """Build a controlled wheel and write traceability artifacts to ``output``."""

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    build_report = output / "build-report.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(output),
            "--report",
            str(build_report),
        ],
        cwd=ROOT,
        check=True,
    )

    sbom = output / "SBOM.cdx.json"
    write_declared_dependency_sbom(metadata, sbom)

    artifact_files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name not in {"SHA256SUMS", "release-manifest.json"}
    )
    checksums = [f"{sha256_file(path)}  {path.name}" for path in artifact_files]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    # Collect per-host validation records if provided.
    host_validation: list[dict[str, Any]] = []
    if host_records_dir is not None:
        host_validation = collect_host_records(host_records_dir)

    declared_targets = [
        {"operating_system": os_, "architecture": arch}
        for os_, arch in [
            ("Windows", "x64"), ("Windows", "arm64"),
            ("macOS", "x64"), ("macOS", "arm64"),
            ("Linux", "x64"), ("Linux", "arm64"),
        ]
    ]

    # Build per-host status table: declared target -> validation status or "not_yet_validated".
    host_status: dict[str, str] = {}
    validated_by_record: set[str] = set()
    for record in host_validation:
        host = record.get("host", {})
        key = f"{host.get('operating_system', '?')} {host.get('architecture', '?')}"
        passed = record.get("all_passed", False)
        host_status[key] = "passed" if passed else "failed"
        validated_by_record.add(key)

    for target in declared_targets:
        key = f"{target['operating_system']} {target['architecture']}"
        if key not in host_status:
            host_status[key] = "not_yet_validated"

    all_declared_passed = all(
        host_status.get(f"{t['operating_system']} {t['architecture']}") == "passed"
        for t in declared_targets
    )

    manifest = {
        "schema_version": 2,
        "product": "Argus SDK",
        "version": metadata["project"]["version"],
        "release_status": "public_beta",
        "public_distribution_permitted": True,
        "production_publication_prohibited": False,
        "interfaces": ["python_api", "cli"],
        "artifacts": [
            {"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in artifact_files
        ],
        "host_validation": {
            "all_declared_targets_passed": all_declared_passed,
            "records_collected": len(host_validation),
            "status_by_host": host_status,
        },
        "required_publication_gates": [
            "each_distributed_host_tuple_has_a_passing_installation_and_regression_record",
            "resolved_dependency_sbom_has_security_review",
            "release_artifacts_are_signed_by_an_approved_release_key",
            "release_approval_and_distribution_record_are_complete",
        ],
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a controlled Argus SDK candidate bundle.")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "release-candidate")
    parser.add_argument(
        "--host-records-dir",
        type=Path,
        default=None,
        help="Directory containing per-host host_validation_record.json files from CI artifacts.",
    )
    arguments = parser.parse_args(argv)
    build_release(arguments.out.resolve(), arguments.host_records_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
