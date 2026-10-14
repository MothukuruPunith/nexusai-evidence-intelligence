"""Record the digest of an explicitly downloaded local Qwen model. Never pulls models."""

import json
from datetime import UTC, datetime

from nexusai.core.config import Settings
from nexusai.documents.storage import atomic_write
from nexusai.rag.generator import MODEL
from nexusai.rag.ollama_process import exchange


def main():
    settings = Settings()
    models = exchange(settings.ollama_url, "/api/tags")["models"]
    model = next((item for item in models if item["name"] == MODEL), None)
    if model is None:
        raise SystemExit(f"Download {MODEL} into your local Ollama instance first.")
    version = exchange(settings.ollama_url, "/api/version")["version"]
    manifest = {
        "model": MODEL,
        "digest": model["digest"],
        "ollama_version": version,
        "recorded_at": datetime.now(UTC).isoformat(),
        "details": model.get("details", {}),
    }
    if settings.llm_manifest.exists():
        previous = json.loads(settings.llm_manifest.read_text())
        if previous["digest"] != manifest["digest"]:
            raise SystemExit(
                "Model digest changed. Review the model and archive the old manifest first."
            )
    atomic_write(settings.llm_manifest, (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
