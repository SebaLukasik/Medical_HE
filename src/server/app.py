"""Serwer FastAPI dla zewnętrznych obliczeń statystyk HE.

Architektura jak w `docs/architecture.md`. Serwer **nie ma** klucza
sekretnego — zaszyfrowane wyniki zwraca klientowi do deszyfracji.

Endpointy:

- ``POST /context``                   — upload klucza ewaluacji (kontekst bez secret_key)
- ``POST /upload``                    — upload zaszyfrowanej kolumny (chunks)
- ``POST /compute/mean``              — średnia (zwraca ciphertext base64)
- ``POST /compute/variance``          — wariancja
- ``POST /compute/sum``               — suma
- ``POST /compute/correlation``       — składowe korelacji Pearsona (sum_x, sum_y, sum_x2, …)
- ``POST /compute/histogram``         — histogram (lista zaszyfrowanych counts)
- ``GET  /healthz``                   — heartbeat

Wszystkie ciphertexty trzymane w pamięci procesu (proste — to demo). W
produkcji użylibyście Redisa / object store.

OWNER: Osoba 3 ("Serwer & benchmark").
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import tenseal as ts
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..crypto.codec import EncryptedColumn, deserialize_column
from ..crypto.context import load_context
from ..server import stats_he as H


app = FastAPI(
    title="Medical HE Stats Server",
    description=(
        "Niezaufany serwer obliczeniowy. Otrzymuje zaszyfrowane kolumny "
        "danych medycznych i wykonuje statystyki w HE bez deszyfracji."
    ),
    version="0.1.0",
)


# ──────────────────────────────────────────────────────────────────────────────
# In-memory state — wystarczy do demo i benchmarków.
# W produkcji każdy klient miałby własny session/context.
# ──────────────────────────────────────────────────────────────────────────────


class _State:
    contexts: dict[str, ts.Context] = {}
    data: dict[str, EncryptedColumn] = {}

    @classmethod
    def reset(cls) -> None:
        cls.contexts.clear()
        cls.data.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "contexts_loaded": len(_State.contexts),
        "datasets_loaded": len(_State.data),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Context upload
# ──────────────────────────────────────────────────────────────────────────────


@app.post("/context")
async def upload_context(file: UploadFile = File(...)) -> dict[str, str]:
    """Upload kontekstu CKKS (bez secret_key) — klucze ewaluacji + public_key."""
    blob = await file.read()
    try:
        ctx = load_context(blob)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Nieprawidłowy kontekst: {e}")
    # Sprawdzamy, że NIE ma secret_key — serwer nie powinien go dostać.
    if ctx.is_private():
        raise HTTPException(
            status_code=400,
            detail="Kontekst zawiera secret_key. Serwer odmawia przyjęcia.",
        )
    context_id = str(uuid.uuid4())
    _State.contexts[context_id] = ctx
    return {"context_id": context_id, "size_bytes": str(len(blob))}


# ──────────────────────────────────────────────────────────────────────────────
# Data upload
# ──────────────────────────────────────────────────────────────────────────────


@app.post("/upload")
async def upload_data(
    context_id: str = Form(...),
    n_samples: int = Form(...),
    slot_count: int = Form(...),
    name: str = Form("unnamed"),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload zaszyfrowanej kolumny — lista chunków (po jednym pliku każdy)."""
    if context_id not in _State.contexts:
        raise HTTPException(404, "Nieznany context_id — najpierw POST /context.")
    ctx = _State.contexts[context_id]
    blobs: list[bytes] = []
    for f in files:
        blobs.append(await f.read())
    try:
        enc = deserialize_column(blobs, ctx, n_samples, slot_count, name=name)
    except Exception as e:
        raise HTTPException(400, f"Błąd deserializacji ciphertextów: {e}")
    data_id = str(uuid.uuid4())
    _State.data[data_id] = enc
    return {
        "data_id": data_id,
        "name": name,
        "n_samples": n_samples,
        "n_chunks": enc.n_chunks(),
        "total_bytes": sum(len(b) for b in blobs),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Compute: statystyki skalarne
# ──────────────────────────────────────────────────────────────────────────────


class ComputeRequest(BaseModel):
    data_id: str
    context_id: str


def _get(data_id: str, context_id: str) -> EncryptedColumn:
    if context_id not in _State.contexts:
        raise HTTPException(404, "Nieznany context_id")
    if data_id not in _State.data:
        raise HTTPException(404, "Nieznany data_id")
    return _State.data[data_id]


@app.post("/compute/sum")
def compute_sum(req: ComputeRequest) -> dict[str, Any]:
    col = _get(req.data_id, req.context_id)
    t0 = time.perf_counter()
    res = H.he_sum(col)
    eval_ms = (time.perf_counter() - t0) * 1000
    return {
        "result_b64": base64.b64encode(res.serialize()).decode(),
        "eval_time_ms": eval_ms,
    }


@app.post("/compute/mean")
def compute_mean(req: ComputeRequest) -> dict[str, Any]:
    col = _get(req.data_id, req.context_id)
    t0 = time.perf_counter()
    res = H.he_mean(col)
    eval_ms = (time.perf_counter() - t0) * 1000
    return {
        "result_b64": base64.b64encode(res.serialize()).decode(),
        "eval_time_ms": eval_ms,
    }


@app.post("/compute/variance")
def compute_variance(req: ComputeRequest) -> dict[str, Any]:
    col = _get(req.data_id, req.context_id)
    t0 = time.perf_counter()
    res = H.he_variance(col)
    eval_ms = (time.perf_counter() - t0) * 1000
    return {
        "result_b64": base64.b64encode(res.serialize()).decode(),
        "eval_time_ms": eval_ms,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Compute: histogram (lista bucketów)
# ──────────────────────────────────────────────────────────────────────────────


class HistogramRequest(BaseModel):
    bucket_data_ids: list[str]
    context_id: str


# ──────────────────────────────────────────────────────────────────────────────
# Compute: korelacja Pearsona (komponenty HE → klient liczy wynik końcowy)
# ──────────────────────────────────────────────────────────────────────────────


class CorrelationRequest(BaseModel):
    """Dwie kolumny (te same N chunków, ta sama długość próby)."""

    data_id_x: str
    data_id_y: str
    context_id: str


@app.post("/compute/correlation")
def compute_correlation(req: CorrelationRequest) -> dict[str, Any]:
    if req.context_id not in _State.contexts:
        raise HTTPException(404, "Nieznany context_id")
    x = _State.data.get(req.data_id_x)
    y = _State.data.get(req.data_id_y)
    if x is None or y is None:
        raise HTTPException(404, "Nieznany data_id_x lub data_id_y")

    t0 = time.perf_counter()
    comps = H.he_correlation_components(x, y)
    eval_ms = (time.perf_counter() - t0) * 1000
    return {
        "n_samples": x.n_samples,
        "sum_x_b64": base64.b64encode(comps["sum_x"].serialize()).decode(),
        "sum_y_b64": base64.b64encode(comps["sum_y"].serialize()).decode(),
        "sum_x2_b64": base64.b64encode(comps["sum_x2"].serialize()).decode(),
        "sum_y2_b64": base64.b64encode(comps["sum_y2"].serialize()).decode(),
        "sum_xy_b64": base64.b64encode(comps["sum_xy"].serialize()).decode(),
        "eval_time_ms": eval_ms,
    }


@app.post("/compute/histogram")
def compute_histogram(req: HistogramRequest) -> dict[str, Any]:
    if req.context_id not in _State.contexts:
        raise HTTPException(404, "Nieznany context_id")
    bucket_cols: list[EncryptedColumn] = []
    for did in req.bucket_data_ids:
        if did not in _State.data:
            raise HTTPException(404, f"Nieznany data_id {did}")
        bucket_cols.append(_State.data[did])
    t0 = time.perf_counter()
    cts = H.he_histogram(bucket_cols)
    eval_ms = (time.perf_counter() - t0) * 1000
    return {
        "result_chunks_b64": [base64.b64encode(c.serialize()).decode() for c in cts],
        "n_buckets": len(cts),
        "eval_time_ms": eval_ms,
    }
