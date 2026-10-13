import subprocess
import sys

import numpy as np
import pytest

from nexusai.documents import native
from nexusai.documents.errors import DocumentError


def test_native_index_operations_do_not_import_faiss_into_host():
    vectors = np.zeros((2, 384), dtype="float32")
    vectors[0, 0] = 1
    vectors[1, 1] = 1
    payload = native.build(vectors)
    scores, ranks = native.nearest(payload, [0, 1], vectors[:1], 2, 2)
    assert ranks == [0, 1]
    assert scores == pytest.approx([1, 0])
    assert "faiss" not in sys.modules


@pytest.mark.parametrize(
    "failure,code",
    [
        (subprocess.TimeoutExpired("faiss", 20), "index_timeout"),
        (subprocess.CalledProcessError(134, "faiss"), "index_operation_failed"),
    ],
)
def test_native_failure_is_translated_to_service_error(monkeypatch, failure, code):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(DocumentError, match=code) as error:
        native.build(np.zeros((1, 384), dtype="float32"))
    assert error.value.status == 503
