import hashlib
import os
from pathlib import Path
from uuid import uuid4

from nexusai.documents.errors import DocumentError


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{uuid4()}.tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def parse_isolated(path: Path, kind: str) -> list[dict]:
    import json
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "nexusai.documents.parser", str(path), kind],
            capture_output=True,
            timeout=20,
            check=True,
        )
        payload = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise DocumentError("parser_timeout") from None
    except (subprocess.CalledProcessError, ValueError):
        raise DocumentError("parser_failure") from None
    if "error" in payload:
        raise DocumentError(payload["error"])
    return payload["blocks"]
