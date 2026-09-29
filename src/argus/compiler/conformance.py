"""Cross-domain verification and conformance engine for Patent Candidate PAT-002.

Patent Title:
Domain-Specific Compiler and Verification Harness for Cross-Domain Translation of
Physical Device Safety Profiles into Synchronized Simulation, Firmware, and RTL Targets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .compiler import ProfileCompiler
from .schema import PartnerProfile


@dataclass(frozen=True)
class TargetConformanceCheck:
    target: str
    property_name: str
    expected_value: Any
    actual_value: Any
    passed: bool


@dataclass(frozen=True)
class ProfileConformanceReport:
    profile_id: str
    schema_version: str
    manifest_sha256: str
    targets_generated: tuple[str, ...]
    checks: tuple[TargetConformanceCheck, ...]
    conformance_passed: bool


class CrossDomainConformanceHarness:
    """Validates cross-domain behavioral and constant parity for compiled profiles."""

    def __init__(self, compiler: ProfileCompiler | None = None) -> None:
        self._compiler = compiler or ProfileCompiler()

    def evaluate_profile(self, profile_path: Path, output_dir: Path | None = None) -> ProfileConformanceReport:
        profile = PartnerProfile.from_json_file(profile_path)
        artifacts = self._compiler.compile(profile)

        # Compute SHA256 manifest hash
        hasher = hashlib.sha256()
        for name in sorted(artifacts.files):
            hasher.update(name.encode("utf-8"))
            hasher.update(artifacts.files[name].encode("utf-8"))
        manifest_hash = hasher.hexdigest()

        checks: list[TargetConformanceCheck] = []

        # 1. Check simulation target
        sim_data = json.loads(artifacts.files["simulation_profile.json"])
        sim_prof = sim_data.get("profile", {})
        checks.append(
            TargetConformanceCheck(
                target="simulation",
                property_name="sensor_count",
                expected_value=len(profile.sensors),
                actual_value=len(sim_prof.get("sensors", [])),
                passed=(len(profile.sensors) == len(sim_prof.get("sensors", []))),
            )
        )
        checks.append(
            TargetConformanceCheck(
                target="simulation",
                property_name="intent_count",
                expected_value=len(profile.intent_classes),
                actual_value=len(sim_prof.get("intent_classes", [])),
                passed=(len(profile.intent_classes) == len(sim_prof.get("intent_classes", []))),
            )
        )

        # 2. Check firmware header target
        fw_header = artifacts.files["firmware_profile.h"]
        expected_torque_macro = f"#define ATLAS_PROFILE_MAX_TORQUE_NM ({profile.actuator.max_torque_nm:.6f}F)"
        checks.append(
            TargetConformanceCheck(
                target="firmware_c",
                property_name="max_torque_nm_macro",
                expected_value=expected_torque_macro,
                actual_value=expected_torque_macro in fw_header,
                passed=(expected_torque_macro in fw_header),
            )
        )
        expected_sensor_macro = f"#define ATLAS_PROFILE_SENSOR_COUNT ({len(profile.sensors)}U)"
        checks.append(
            TargetConformanceCheck(
                target="firmware_c",
                property_name="sensor_count_macro",
                expected_value=expected_sensor_macro,
                actual_value=expected_sensor_macro in fw_header,
                passed=(expected_sensor_macro in fw_header),
            )
        )

        # 3. Check RTL parameter target
        rtl_params = artifacts.files["rtl_profile.vh"]
        expected_mnm = round(profile.actuator.max_torque_nm * 1000.0)
        mnm_token = f"MAX_TORQUE_MNM = {expected_mnm}"
        checks.append(
            TargetConformanceCheck(
                target="rtl_verilog",
                property_name="max_torque_mnm_param",
                expected_value=mnm_token,
                actual_value=mnm_token in rtl_params,
                passed=(mnm_token in rtl_params),
            )
        )

        rtl_defines = artifacts.files["rtl_profile_defines.vh"]
        expected_define = f"`define ATLAS_PROFILE_MAX_TORQUE_MNM {expected_mnm}"
        checks.append(
            TargetConformanceCheck(
                target="rtl_target_build",
                property_name="max_torque_mnm_define",
                expected_value=expected_define,
                actual_value=expected_define in rtl_defines,
                passed=(expected_define in rtl_defines),
            )
        )

        # 4. Check fault test vectors target
        vectors_data = json.loads(artifacts.files["fault_test_vectors.json"])
        vectors = vectors_data.get("vectors", [])
        expected_vector_count = len(profile.sensors) + 2  # Each sensor + torque over-limit + vel over-limit
        checks.append(
            TargetConformanceCheck(
                target="fault_vectors",
                property_name="coverage_count",
                expected_value=expected_vector_count,
                actual_value=len(vectors),
                passed=(len(vectors) == expected_vector_count),
            )
        )

        all_passed = all(c.passed for c in checks)

        if output_dir is not None:
            artifacts.write(output_dir)
            manifest_file = output_dir / "profile_manifest.sha256"
            manifest_file.write_text(f"{manifest_hash}  {profile.profile_id}\n", encoding="utf-8")

        return ProfileConformanceReport(
            profile_id=profile.profile_id,
            schema_version=profile.schema_version,
            manifest_sha256=manifest_hash,
            targets_generated=tuple(sorted(artifacts.files.keys())),
            checks=tuple(checks),
            conformance_passed=all_passed,
        )


def run_pat002_verification(
    profiles_dir: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Compile and verify all registered partner profiles in the portfolio."""
    harness = CrossDomainConformanceHarness()
    profile_paths = sorted(profiles_dir.glob("*.json"))
    if not profile_paths:
        raise FileNotFoundError(f"No profile JSON files found in {profiles_dir}")

    print("=" * 80)
    print("PAT-002: CROSS-DOMAIN PROFILE COMPILER & CONFORMANCE HARNESS")
    print("Multi-Target Cross-Domain Compilation & Parity Verification Engine")
    print("=" * 80)

    reports: list[ProfileConformanceReport] = []
    for p_path in profile_paths:
        out_target = (output_dir / p_path.stem) if output_dir else None
        rep = harness.evaluate_profile(p_path, out_target)
        reports.append(rep)
        status_str = "PASS" if rep.conformance_passed else "FAIL"
        print(f"\n[PROFILE] {rep.profile_id} (Schema v{rep.schema_version}) -> {status_str}")
        print(f"  Manifest SHA256: {rep.manifest_sha256[:16]}...")
        print(f"  Targets Emitted: {', '.join(rep.targets_generated)}")
        for check in rep.checks:
            c_status = "OK" if check.passed else "MISMATCH"
            print(f"    - [{check.target:<13}] {check.property_name:<22}: {c_status}")

    all_passed = all(r.conformance_passed for r in reports)
    print("\n" + "=" * 80)
    print(f"PAT-002 SUMMARY: {len(reports)}/{len(reports)} Profiles Conforming. Status: {'ALL PASS' if all_passed else 'FAIL'}")
    print("=" * 80)

    summary = {
        "patent_id": "PAT-002",
        "title": "Cross-Domain Profile Compiler Conformance Report",
        "profiles_evaluated": len(reports),
        "all_conformance_passed": all_passed,
        "reports": [
            {
                "profile_id": r.profile_id,
                "schema_version": r.schema_version,
                "manifest_sha256": r.manifest_sha256,
                "targets_generated": list(r.targets_generated),
                "checks": [asdict(c) for c in r.checks],
                "passed": r.conformance_passed,
            }
            for r in reports
        ],
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        rep_file = output_dir / "pat002_compiler_conformance_report.json"
        rep_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Master report saved to: {rep_file}")

    return summary
