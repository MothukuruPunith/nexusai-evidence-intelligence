"""Native index subprocess. Never import embedding, torch, API, or worker modules here."""

import io
import json
import sys

import faiss
import numpy as np


def main() -> None:
    faiss.omp_set_num_threads(2)
    with np.load(io.BytesIO(sys.stdin.buffer.read()), allow_pickle=False) as payload:
        if sys.argv[1] == "build":
            vectors = payload["vectors"]
            if vectors.ndim != 2 or vectors.shape[1] != 384 or len(vectors) > 10_000:
                raise ValueError("invalid vector shape")
            index = faiss.IndexFlatIP(384)
            if len(vectors):
                index.add(np.ascontiguousarray(vectors, dtype="float32"))
            sys.stdout.buffer.write(faiss.serialize_index(index).tobytes())
        elif sys.argv[1] == "search":
            index = faiss.deserialize_index(payload["index"])
            k, count = payload["limits"]
            if index.d != 384 or index.ntotal != count:
                raise ValueError("invalid index shape")
            positions = payload["positions"]
            if len(positions) == 0:
                print(json.dumps({"scores": [], "ranks": []}))
                return
            subset = faiss.IndexFlatIP(384)
            subset.add(index.reconstruct_batch(positions))
            scores, ranks = subset.search(payload["query"], min(int(k), len(positions)))
            print(json.dumps({"scores": scores[0].tolist(), "ranks": ranks[0].tolist()}))
        else:
            raise ValueError("unsupported operation")


if __name__ == "__main__":
    main()
