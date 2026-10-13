"""Download one public, pinned model explicitly; runtime inference never fetches models."""

import hashlib
import json
import os

from huggingface_hub import snapshot_download

from nexusai.core.config import Settings
from nexusai.documents.embedding import MODEL_ID, MODEL_REVISION


def main():
    settings = Settings()
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=settings.model_dir,
        allow_patterns=["*.json", "*.txt", "model.safetensors"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    files = {
        str(p.relative_to(settings.model_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in settings.model_dir.rglob("*")
        if p.is_file() and ".cache" not in p.parts and p.name != "nexus-manifest.json"
    }
    (settings.model_dir / "nexus-manifest.json").write_text(
        json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": files}, indent=2)
    )
    print(f"Downloaded pinned model revision {MODEL_REVISION}; recorded {len(files)} checksums.")


if __name__ == "__main__":
    main()
