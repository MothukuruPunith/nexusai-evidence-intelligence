"""Pinned, local-only model inference; downloads are an explicit setup operation."""

import hashlib
import json
import threading
from pathlib import Path

import numpy as np

from nexusai.documents.errors import DocumentError

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SIGNATURE = f"{MODEL_ID}@{MODEL_REVISION}:normalized:384:chunk-v1"


class Embedder:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self._model = None
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            if self._model is None:
                try:
                    manifest = json.loads((self.model_dir / "nexus-manifest.json").read_text())
                    if manifest["revision"] != MODEL_REVISION or not manifest["files"]:
                        raise ValueError("revision mismatch")
                    for name, digest in manifest["files"].items():
                        path = self.model_dir / name
                        if not path.resolve().is_relative_to(self.model_dir.resolve()):
                            raise ValueError("invalid artifact path")
                        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                            raise ValueError("checksum mismatch")
                except (OSError, ValueError, KeyError):
                    raise DocumentError("embedding_model_missing_or_invalid", 503) from None
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(2)
                self._model = SentenceTransformer(
                    str(self.model_dir),
                    device="cpu",
                    local_files_only=True,
                    trust_remote_code=False,
                    model_kwargs={"use_safetensors": True},
                )
            return self._model

    def chunks(self, blocks: list[dict]) -> list[dict]:
        tokenizer = self.load().tokenizer
        limit = min(224, self.load().max_seq_length - tokenizer.num_special_tokens_to_add(False))
        chunks = []
        for block_no, block in enumerate(blocks):
            offsets = tokenizer(
                block["text"],
                add_special_tokens=False,
                return_offsets_mapping=True,
                truncation=False,
            )["offset_mapping"]
            for start in range(0, len(offsets), limit - 32):
                end = min(start + limit, len(offsets))
                if start and len(offsets) <= start + 32:
                    break
                a, b = offsets[start][0], offsets[end - 1][1]
                value = block["text"][a:b]
                if len(tokenizer(value)["input_ids"]) > self.load().max_seq_length:
                    raise DocumentError("chunk_exceeds_model_limit")
                chunks.append(
                    {
                        "block": block_no,
                        "locator": block["locator"],
                        "start": a,
                        "end": b,
                        "text": value,
                    }
                )
                if len(chunks) > 2000:
                    raise DocumentError("too_many_chunks")
                if end == len(offsets):
                    break
        return chunks

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            model = self.load()
            if any(
                len(model.tokenizer(value)["input_ids"]) > model.max_seq_length for value in texts
            ):
                raise DocumentError("embedding_input_too_long")
            result = model.encode(
                texts,
                batch_size=16,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = np.ascontiguousarray(result, dtype="float32")
            if vectors.shape != (len(texts), 384) or not np.isfinite(vectors).all():
                raise DocumentError("invalid_embedding", 503)
            return vectors
