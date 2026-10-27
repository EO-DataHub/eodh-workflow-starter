"""
Checksum of this folder, so CI notices local edits to the helpers.

`CHECKSUM` holds the value for the released folder. If you choose to fork the helpers, delete
`tests/helpers/test_helpers_unchanged.py` and say so in your README.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent
CHECKSUM_FILE = ROOT / "CHECKSUM"


def compute() -> str:
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == CHECKSUM_FILE or "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def recorded() -> str:
    return CHECKSUM_FILE.read_text().strip()
