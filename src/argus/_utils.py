"""Internal Atlas utilities shared across the package.

This module contains small helpers that would otherwise be copy-pasted into
every sub-module that needs them. Nothing here is part of the public API.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 hex digest of a file, reading in 1 MB chunks.

    Reading in chunks keeps memory usage flat for large trace or profile
    files. The digest is hex-encoded, lowercase, 64 characters long.
    """
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()
