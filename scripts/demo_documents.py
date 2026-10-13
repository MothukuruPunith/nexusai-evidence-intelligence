"""Exercise the running API and separate ingestion worker using synthetic fixtures only."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = [
        ("hr-policy.txt", "text/plain", "hr_policy", "How many annual leave days?", "20"),
        (
            "operations-note.txt",
            "text/plain",
            "technical_documentation",
            "When is customer support open?",
            "09:00",
        ),
        ("sales.csv", "text/csv", "financial_report", "September 2025 revenue", "85000.00"),
    ]
    report = {"recorded_at": datetime.now(UTC).isoformat(), "synthetic": True, "checks": []}
    with httpx2.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30) as client:
        client.get("/health").raise_for_status()
        for filename, mime, category, query, expected in cases:
            content = (root / "datasets" / "samples" / filename).read_bytes()
            response = client.post(
                "/documents/upload",
                files={"file": (filename, content, mime)},
                data={"category": category},
            )
            response.raise_for_status()
            upload = response.json()
            deadline = time.monotonic() + 90
            while True:
                response = client.get(f"/jobs/{upload['job_id']}")
                response.raise_for_status()
                job = response.json()
                if job["status"] == "succeeded":
                    break
                if job["status"] == "failed":
                    raise SystemExit(f"Ingestion failed for {filename}: {job['error']}")
                if time.monotonic() >= deadline:
                    raise SystemExit("Ingestion timed out. Start the separate ingestion worker.")
                time.sleep(0.25)
            response = client.post(
                "/documents/search",
                json={
                    "query": query,
                    "k": 5,
                    "document_ids": [upload["document_id"]],
                    "category": category,
                },
            )
            response.raise_for_status()
            result = response.json()
            matches = [
                (rank, hit) for rank, hit in enumerate(result["hits"], 1) if expected in hit["text"]
            ]
            if not matches:
                raise SystemExit(
                    f"Expected evidence was absent from the retrieved set for {filename}"
                )
            rank, hit = matches[0]
            response = client.get(f"/documents/{upload['document_id']}/chunks")
            response.raise_for_status()
            source = next(row for row in response.json() if row["id"] == hit["id"])
            assert source["text"] == hit["text"]
            report["checks"].append(
                {
                    "file": filename,
                    "query": query,
                    "status": "retrieved_and_source_verified",
                    "rank": rank,
                    "top_hit_matches": rank == 1,
                    "document_id": upload["document_id"],
                    "chunk_id": hit["id"],
                    "locator": hit["locator"],
                    "quote": hit["text"],
                    "retrieval_score": hit["score"],
                    "generation_id": result["generation_id"],
                }
            )
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    print(encoded)


if __name__ == "__main__":
    main()
