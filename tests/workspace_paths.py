"""Canonical workspace paths used by cross-repository verification tests.

Product source, reusable IP, firmware, hardware targets, and verification collateral
are maintained in separate repositories. Tests that cross those boundaries must use
these paths rather than assuming that all source lives beneath the SDK repository.
"""

from __future__ import annotations

from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SDK_ROOT.parents[1]
REPOSITORIES_ROOT = WORKSPACE_ROOT / "repositories"
IP_ROOT = REPOSITORIES_ROOT / "atlas-ip"
FIRMWARE_ROOT = REPOSITORIES_ROOT / "argus-fw"
HARDWARE_ROOT = REPOSITORIES_ROOT / "acek-rev-a"
VERIFICATION_ROOT = REPOSITORIES_ROOT / "verification"
VERIFICATION_TB = VERIFICATION_ROOT / "tb"
EARG_ROOT = REPOSITORIES_ROOT / "earg001"
EARG_TARGETS = EARG_ROOT / "targets"
EARG_ASIC_SKY130 = EARG_ROOT / "asic" / "sky130"
ATLAS_COMPUTE_RTL = IP_ROOT / "atlas-compute" / "rtl" / "src"
ATLAS_FABRIC_RTL = IP_ROOT / "atlas-fabric" / "rtl" / "src"
ATLAS_SENTINEL_RTL = IP_ROOT / "atlas-sentinel" / "rtl" / "src"
