"""Run a small, explicitly synthetic development set against a real API and worker."""

import argparse
import hashlib
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output", type=Path, default=Path("docs/phase-4-baseline.json"))
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "datasets/evaluation/phase4.json"
    data = json.loads(path.read_text())
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "split": "development",
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "platform": platform.system() + " " + platform.machine(),
        "cases": [],
    }
    with httpx2.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=90) as client:
        ids = {}
        for filename, content in data["documents"].items():
            response = client.post(
                "/documents/upload", files={"file": ("phase4-" + filename, content.encode())}
            )
            response.raise_for_status()
            item = response.json()
            ids[filename] = item["document_id"]
            deadline = time.monotonic() + 90
            while True:
                job = client.get(f"/jobs/{item['job_id']}")
                job.raise_for_status()
                status = job.json()["status"]
                if status == "succeeded":
                    break
                if status == "failed" or time.monotonic() > deadline:
                    raise RuntimeError("Synthetic ingestion failed or timed out")
                time.sleep(0.2)
        for case in data["cases"]:
            body = {
                "query": case["query"],
                "document_ids": [ids[n] for n in case["documents"]],
                "k": 5,
            }
            retrieval = client.post("/documents/search", json=body)
            retrieval.raise_for_status()
            hits = retrieval.json()["hits"]
            gold = case["gold"]
            # Gold units are distinct annotated spans, not overlapping chunk counts.
            ranks = [
                next((i for i, h in enumerate(hits, 1) if span in h["text"]), None) for span in gold
            ]
            response = client.post("/rag/query", json=body)
            record = {
                "id": case["id"],
                "kind": case["kind"],
                "query": case["query"],
                "http_status": response.status_code,
                "gold_ranks": ranks,
                "recall_at_5": sum(r is not None for r in ranks) / len(gold) if gold else None,
                "response": response.json(),
            }
            result = response.json()
            valid = 0
            if response.status_code == 200:
                for citation in result["citations"]:
                    resolved = client.get(citation["url"])
                    resolved.raise_for_status()
                    source = resolved.json()
                    offset = citation["start"] - source["start"]
                    assert offset >= 0
                    assert (
                        source["quote"][offset : offset + len(citation["quote"])]
                        == citation["quote"]
                    )
                    assert citation["end"] - citation["start"] == len(citation["quote"])
                    assert citation["document_sha256"] == source["document_sha256"]
                    assert citation["chunk_sha256"] == source["chunk_sha256"]
                    assert citation["document_id"] in body["document_ids"]
                    valid += 1
                record["rubric_pass"] = (
                    result["status"] == case["expected_status"]
                    and all(v in result["answer"] for v in case["required"])
                    and not any(v in result["answer"] for v in case["forbidden"])
                )
            else:
                record["rubric_pass"] = False
            record["verified_citations"] = valid
            report["cases"].append(record)
            print(case["id"], response.status_code, record["rubric_pass"], flush=True)
            # Save partial progress if a later case fails or execution is interrupted.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    report["summary"] = {
        "cases": len(report["cases"]),
        "rubric_passes": sum(c["rubric_pass"] for c in report["cases"]),
        "verified_citations": sum(c["verified_citations"] for c in report["cases"]),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
