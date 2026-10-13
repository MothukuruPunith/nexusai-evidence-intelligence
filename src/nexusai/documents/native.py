"""Run FAISS separately from PyTorch: their macOS OpenMP runtimes can conflict.

An import-order workaround passed in-process tests but crashed in the live HTTP server.
Use bounded subprocesses so a native failure becomes a controlled service error.
"""

import io
import json
import subprocess
import sys
import threading

import numpy as np

from nexusai.documents.errors import DocumentError

_SLOTS = threading.BoundedSemaphore(2)


def execute(operation: str, **arrays: np.ndarray) -> bytes:
    payload = io.BytesIO()
    np.savez(payload, **arrays)
    if not _SLOTS.acquire(timeout=3):
        raise DocumentError("index_busy", 503)
    try:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "nexusai.documents.faiss_process", operation],
                input=payload.getvalue(),
                capture_output=True,
                timeout=20,
                check=True,
            )
        except subprocess.TimeoutExpired:
            raise DocumentError("index_timeout", 503) from None
        except subprocess.CalledProcessError:
            raise DocumentError("index_operation_failed", 503) from None
        return result.stdout
    finally:
        _SLOTS.release()


def build(vectors: np.ndarray) -> bytes:
    return execute("build", vectors=vectors)


def nearest(payload: bytes, positions: list[int], query: np.ndarray, k: int, count: int):
    result = execute(
        "search",
        index=np.frombuffer(payload, dtype="uint8"),
        positions=np.array(positions, dtype="int64"),
        query=query,
        limits=np.array([k, count], dtype="int64"),
    )
    try:
        answer = json.loads(result)
        return answer["scores"], answer["ranks"]
    except (ValueError, KeyError):
        raise DocumentError("index_operation_failed", 503) from None
