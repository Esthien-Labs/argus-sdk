"""Verify a Sigstore signature for an Argus SDK artifact.

Usage:
    python scripts/verify_signature.py <artifact> <signature.json>

Exit codes:
    0 - signature valid
    1 - signature invalid or verification failed
    2 - usage error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: verify_signature.py <artifact> <signature.json>", file=sys.stderr)
        return 2

    artifact = Path(args[0])
    signature_file = Path(args[1])

    if not artifact.is_file():
        print(f"artifact not found: {artifact}", file=sys.stderr)
        return 2
    if not signature_file.is_file():
        print(f"signature file not found: {signature_file}", file=sys.stderr)
        return 2

    try:
        from sigstore.verify import Verifier
        from sigstore.models import Bundle
    except ImportError:
        print("sigstore not installed. Run: pip install sigstore", file=sys.stderr)
        return 2

    try:
        bundle = Bundle.from_json(signature_file.read_text(encoding="utf-8"))
        verifier = Verifier.production()
        verifier.verify(artifact.read_bytes(), bundle)
        print(f"OK: {artifact.name} signature is valid")
        return 0
    except Exception as exc:
        print(f"FAIL: {artifact.name} signature verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
