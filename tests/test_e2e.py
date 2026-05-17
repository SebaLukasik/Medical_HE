"""End-to-end testy: klient + serwer FastAPI (in-process).

Używamy TestClient z FastAPI — uruchomienia serwera nie potrzeba. Cały
flow przechodzi przez właściwe endpointy HTTP.

Uruchomienie:
    uv run pytest tests/test_e2e.py -v
"""

from __future__ import annotations

import base64
import numpy as np
import pytest
import tenseal as ts
from fastapi.testclient import TestClient

from src.crypto.codec import (
    decrypt_scalar,
    encrypt_column,
    serialize_column,
)
from src.crypto.context import make_context, serialize_for_server
from src.plaintext import stats_plain as P
from src.server.app import _State, app


@pytest.fixture(autouse=True)
def reset_server():
    """Czyść stan serwera przed każdym testem."""
    _State.reset()
    yield
    _State.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def context():
    return make_context()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_context_upload_rejects_secret_key(client, context):
    """Serwer MUSI odrzucić kontekst zawierający secret_key."""
    full_blob = context.serialize(save_secret_key=True)
    r = client.post("/context", files={"file": ("ctx.tenseal", full_blob)})
    assert r.status_code == 400
    assert "secret" in r.json()["detail"].lower()


def test_context_upload_ok(client, context):
    """Serwer akceptuje kontekst bez secret_key."""
    blob = serialize_for_server(context)
    r = client.post("/context", files={"file": ("ctx.tenseal", blob)})
    assert r.status_code == 200
    assert "context_id" in r.json()


def _upload_context(client, context) -> str:
    blob = serialize_for_server(context)
    r = client.post("/context", files={"file": ("ctx.tenseal", blob)})
    r.raise_for_status()
    return r.json()["context_id"]


def _upload_column(client, context_id, values, context):
    enc = encrypt_column(values, context)
    blobs = serialize_column(enc)
    files = [("files", (f"chunk_{i}.ct", b)) for i, b in enumerate(blobs)]
    r = client.post(
        "/upload",
        data={
            "context_id": context_id,
            "n_samples": str(enc.n_samples),
            "slot_count": str(enc.slot_count),
            "name": "test",
        },
        files=files,
    )
    r.raise_for_status()
    return r.json()["data_id"], enc


def test_compute_mean_e2e(client, context):
    """Pełny przepływ: upload → compute/mean → decrypt → porównanie z NumPy."""
    rng = np.random.default_rng(42)
    values = rng.normal(120, 15, 500)
    expected = P.mean(values)

    ctx_id = _upload_context(client, context)
    data_id, _ = _upload_column(client, ctx_id, values, context)

    r = client.post(
        "/compute/mean", json={"data_id": data_id, "context_id": ctx_id}
    )
    assert r.status_code == 200
    blob = base64.b64decode(r.json()["result_b64"])
    ct = ts.ckks_vector_from(context, blob)
    he = float(ct.decrypt()[0])
    rel = abs(he - expected) / abs(expected)
    assert rel < 1e-5
    assert r.json()["eval_time_ms"] > 0


def test_compute_variance_e2e(client, context):
    rng = np.random.default_rng(0)
    values = rng.normal(25, 4, 1000)
    expected = P.variance(values)

    ctx_id = _upload_context(client, context)
    data_id, _ = _upload_column(client, ctx_id, values, context)

    r = client.post(
        "/compute/variance", json={"data_id": data_id, "context_id": ctx_id}
    )
    assert r.status_code == 200
    blob = base64.b64decode(r.json()["result_b64"])
    he = float(ts.ckks_vector_from(context, blob).decrypt()[0])
    rel = abs(he - expected) / abs(expected)
    assert rel < 1e-4


def test_unknown_data_id_returns_404(client, context):
    ctx_id = _upload_context(client, context)
    r = client.post(
        "/compute/mean", json={"data_id": "nieistnieje", "context_id": ctx_id}
    )
    assert r.status_code == 404


def test_unknown_context_returns_404(client):
    r = client.post(
        "/compute/mean", json={"data_id": "x", "context_id": "y"}
    )
    assert r.status_code == 404


def test_histogram_e2e(client, context):
    """Histogram przez API: K osobnych uploadów + /compute/histogram."""
    rng = np.random.default_rng(7)
    values = rng.normal(120, 15, 500)
    edges = np.linspace(values.min() - 0.1, values.max() + 0.1, 11)  # K=10
    oh = P.make_one_hot(values, edges)

    ctx_id = _upload_context(client, context)
    bucket_ids: list[str] = []
    for k in range(oh.shape[1]):
        did, _ = _upload_column(client, ctx_id, oh[:, k], context)
        bucket_ids.append(did)

    r = client.post(
        "/compute/histogram",
        json={"bucket_data_ids": bucket_ids, "context_id": ctx_id},
    )
    assert r.status_code == 200
    chunks = r.json()["result_chunks_b64"]
    assert len(chunks) == 10
    he_counts = []
    for b64 in chunks:
        ct = ts.ckks_vector_from(context, base64.b64decode(b64))
        he_counts.append(float(ct.decrypt()[0]))
    he_counts = np.round(he_counts).astype(np.int64)
    np_counts = oh.sum(axis=0).astype(np.int64)
    assert np.array_equal(he_counts, np_counts)


def test_correlation_e2e(client, context):
    """Korelacja Pearsona: dwie kolumny + /compute/correlation."""
    rng = np.random.default_rng(99)
    x = rng.normal(25, 4, 400).astype(np.float64)
    y = 70 + 2.3 * (x - 25) + rng.normal(0, 6, 400).astype(np.float64)
    expected = P.correlation_pearson(x, y)

    ctx_id = _upload_context(client, context)
    data_id_x, _ = _upload_column(client, ctx_id, x, context)
    data_id_y, _ = _upload_column(client, ctx_id, y, context)

    r = client.post(
        "/compute/correlation",
        json={
            "data_id_x": data_id_x,
            "data_id_y": data_id_y,
            "context_id": ctx_id,
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j["n_samples"] == 400
    sx = float(ts.ckks_vector_from(context, base64.b64decode(j["sum_x_b64"])).decrypt()[0])
    sy = float(ts.ckks_vector_from(context, base64.b64decode(j["sum_y_b64"])).decrypt()[0])
    sx2 = float(ts.ckks_vector_from(context, base64.b64decode(j["sum_x2_b64"])).decrypt()[0])
    sy2 = float(ts.ckks_vector_from(context, base64.b64decode(j["sum_y2_b64"])).decrypt()[0])
    sxy = float(ts.ckks_vector_from(context, base64.b64decode(j["sum_xy_b64"])).decrypt()[0])
    n = 400
    num = n * sxy - sx * sy
    den = float(np.sqrt(max((n * sx2 - sx * sx) * (n * sy2 - sy * sy), 0.0)))
    he_corr = num / den
    assert abs(he_corr - expected) < 1e-4
