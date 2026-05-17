"""Klient szpitala (lekarza) — orkiestracja end-to-end.

Dwa tryby:

1. **Local** (``--local``): klient i "serwer" w tym samym procesie. Używamy
   bezpośrednio modułu ``src/server/stats_he.py`` — bez HTTP. Przyda się do
   szybkich testów i benchmarków poprawności.

2. **Remote** (``--server URL``): klient mówi do FastAPI w ``src/server/app.py``
   po HTTP (multipart upload kluczy + ciphertextów, odpytywanie endpointów).
   Pełny "produkcyjny" scenariusz.

Demo flow:

1. Wczytaj ``patients.csv``.
2. Wygeneruj kontekst CKKS (klucze).
3. Zaszyfruj wskazaną kolumnę.
4. Wyślij na serwer (lub policz lokalnie).
5. Odbierz zaszyfrowany wynik, odszyfruj.
6. Porównaj z plaintextem (NumPy) i wypisz tabelkę.

OWNER: Osoba 2 ("Krypto & klient").
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import base64

import numpy as np
import pandas as pd
import tenseal as ts

from ..crypto.codec import (
    decrypt_scalar,
    encrypt_column,
    serialize_column,
)
from ..crypto.context import (
    make_context,
    serialize_for_server,
)
from ..plaintext import stats_plain as P
from ..server import stats_he as H


@dataclass
class Timings:
    """Pomiary czasów dla pełnego flow (w ms)."""

    keygen: float = 0.0
    encrypt: float = 0.0
    eval_server: float = 0.0
    transport: float = 0.0  # tylko w trybie remote
    decrypt: float = 0.0

    def total_he(self) -> float:
        return self.keygen + self.encrypt + self.eval_server + self.transport + self.decrypt


# ──────────────────────────────────────────────────────────────────────────────
# Local mode (serwer w tym samym procesie)
# ──────────────────────────────────────────────────────────────────────────────


def run_local(
    values_x: np.ndarray,
    stat: str,
    *,
    values_y: np.ndarray | None = None,
    n_buckets: int = 30,
) -> tuple[Any, Timings]:
    """Pełny przepływ HE bez sieci. Zwraca (wynik_HE, czasy)."""
    timings = Timings()

    t0 = time.perf_counter()
    ctx = make_context()
    timings.keygen = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    enc = encrypt_column(values_x, ctx)
    timings.encrypt = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    if stat == "mean":
        result_ct = H.he_mean(enc)
    elif stat == "variance":
        result_ct = H.he_variance(enc)
    elif stat == "sum":
        result_ct = H.he_sum(enc)
    elif stat == "histogram":
        lo, hi = float(values_x.min()), float(values_x.max())
        pad = (hi - lo) * 0.001 if hi > lo else 1.0
        edges = np.linspace(lo - pad, hi + pad, n_buckets + 1)
        # Klient prepuje one-hot w plaintekście i szyfruje per-bucket
        oh = P.make_one_hot(values_x, edges)
        bucket_cols = [encrypt_column(oh[:, k], ctx, name=f"b{k}") for k in range(oh.shape[1])]
        # OK — to encryption time, ale w prawdziwym e2e bucket_cols byłyby
        # wysłane razem z normalną kolumną. Dla uproszczenia liczymy razem.
        result_cts = H.he_histogram(bucket_cols)
        timings.eval_server = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        counts = np.array([decrypt_scalar(ct) for ct in result_cts])
        timings.decrypt = (time.perf_counter() - t0) * 1000
        hist = P.Histogram(edges=edges, counts=np.round(counts).astype(np.int64))
        return hist, timings
    elif stat == "correlation":
        if values_y is None:
            raise ValueError("Korelacja wymaga drugiej kolumny (--column2).")
        t0_enc = time.perf_counter()
        enc_y = encrypt_column(values_y, ctx)
        timings.encrypt += (time.perf_counter() - t0_enc) * 1000
        t0 = time.perf_counter()
        comps = H.he_correlation_components(enc, enc_y)
        timings.eval_server = (time.perf_counter() - t0) * 1000
        t0_dec = time.perf_counter()
        sx = decrypt_scalar(comps["sum_x"])
        sy = decrypt_scalar(comps["sum_y"])
        sx2 = decrypt_scalar(comps["sum_x2"])
        sy2 = decrypt_scalar(comps["sum_y2"])
        sxy = decrypt_scalar(comps["sum_xy"])
        timings.decrypt = (time.perf_counter() - t0_dec) * 1000
        num = n * sxy - sx * sy
        den = float(np.sqrt(max((n * sx2 - sx * sx) * (n * sy2 - sy * sy), 0.0)))
        corr = num / den if den > 0 else float("nan")
        return corr, timings
    else:
        raise ValueError(f"Nieznana statystyka: {stat}")
    timings.eval_server = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    value = decrypt_scalar(result_ct)
    timings.decrypt = (time.perf_counter() - t0) * 1000

    return value, timings


# ──────────────────────────────────────────────────────────────────────────────
# Remote mode (FastAPI)
# ──────────────────────────────────────────────────────────────────────────────


def run_remote(
    values_x: np.ndarray,
    stat: str,
    server_url: str,
    *,
    values_y: np.ndarray | None = None,
    n_buckets: int = 30,
) -> tuple[Any, Timings]:
    """Pełny przepływ HE przez HTTP do serwera FastAPI."""
    import httpx

    timings = Timings()
    server_url = server_url.rstrip("/")

    # 1) Generacja kluczy
    t0 = time.perf_counter()
    ctx = make_context()
    timings.keygen = (time.perf_counter() - t0) * 1000

    # 2) Wyślij kontekst (bez secret_key)
    ctx_bytes = serialize_for_server(ctx)
    t0 = time.perf_counter()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{server_url}/context", files={"file": ("ctx.tenseal", ctx_bytes)})
        r.raise_for_status()
        context_id = r.json()["context_id"]
    timings.transport += (time.perf_counter() - t0) * 1000

    # 3a) Zaszyfruj i upload pierwszej kolumny
    t0 = time.perf_counter()
    enc_x = encrypt_column(values_x, ctx)
    timings.encrypt = (time.perf_counter() - t0) * 1000

    blobs_x = serialize_column(enc_x)
    t0 = time.perf_counter()
    with httpx.Client(timeout=300.0) as client:
        files = [("files", (f"chunk_{i}.ct", b)) for i, b in enumerate(blobs_x)]
        r = client.post(
            f"{server_url}/upload",
            data={
                "context_id": context_id,
                "n_samples": str(enc_x.n_samples),
                "slot_count": str(enc_x.slot_count),
                "name": "col_x",
            },
            files=files,
        )
        r.raise_for_status()
        data_id_x = r.json()["data_id"]
    timings.transport += (time.perf_counter() - t0) * 1000

    # 3b) Korelacja — druga kolumna osobno
    data_id = data_id_x
    if stat == "correlation":
        if values_y is None:
            raise ValueError("Korelacja wymaga drugiej kolumny (--column2).")
        t0 = time.perf_counter()
        enc_y = encrypt_column(values_y, ctx)
        timings.encrypt += (time.perf_counter() - t0) * 1000
        blobs_y = serialize_column(enc_y)
        t0 = time.perf_counter()
        with httpx.Client(timeout=300.0) as client:
            files = [("files", (f"chunk_{i}.ct", b)) for i, b in enumerate(blobs_y)]
            r = client.post(
                f"{server_url}/upload",
                data={
                    "context_id": context_id,
                    "n_samples": str(enc_y.n_samples),
                    "slot_count": str(enc_y.slot_count),
                    "name": "col_y",
                },
                files=files,
            )
            r.raise_for_status()
            data_id_y = r.json()["data_id"]
        timings.transport += (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        with httpx.Client(timeout=300.0) as client:
            r = client.post(
                f"{server_url}/compute/correlation",
                json={
                    "data_id_x": data_id_x,
                    "data_id_y": data_id_y,
                    "context_id": context_id,
                },
            )
            r.raise_for_status()
            body = r.json()
            server_eval_ms = body["eval_time_ms"]
        timings.transport += (time.perf_counter() - t0) * 1000 - server_eval_ms
        timings.eval_server = server_eval_ms

        n = int(body["n_samples"])
        t0 = time.perf_counter()
        sx = decrypt_scalar(ts.ckks_vector_from(ctx, base64.b64decode(body["sum_x_b64"])))
        sy = decrypt_scalar(ts.ckks_vector_from(ctx, base64.b64decode(body["sum_y_b64"])))
        sx2 = decrypt_scalar(ts.ckks_vector_from(ctx, base64.b64decode(body["sum_x2_b64"])))
        sy2 = decrypt_scalar(ts.ckks_vector_from(ctx, base64.b64decode(body["sum_y2_b64"])))
        sxy = decrypt_scalar(ts.ckks_vector_from(ctx, base64.b64decode(body["sum_xy_b64"])))
        num = n * sxy - sx * sy
        den = float(np.sqrt(max((n * sx2 - sx * sx) * (n * sy2 - sy * sy), 0.0)))
        corr = num / den if den > 0 else float("nan")
        # decrypt_scalar już zużył czas — używamy tego bloku jako "decrypt"
        timings.decrypt = (time.perf_counter() - t0) * 1000
        return corr, timings

    # 4) Histogram (osobna gałąź — wiele uploadów bucketów)
    t0 = time.perf_counter()
    if stat == "histogram":
        lo, hi = float(values_x.min()), float(values_x.max())
        pad = (hi - lo) * 0.001 if hi > lo else 1.0
        edges = np.linspace(lo - pad, hi + pad, n_buckets + 1)
        oh = P.make_one_hot(values_x, edges)
        bucket_data_ids: list[str] = []
        with httpx.Client(timeout=300.0) as client:
            for k in range(oh.shape[1]):
                enc_b = encrypt_column(oh[:, k], ctx, name=f"b{k}")
                files = [
                    ("files", (f"chunk_{i}.ct", b))
                    for i, b in enumerate(serialize_column(enc_b))
                ]
                r = client.post(
                    f"{server_url}/upload",
                    data={
                        "context_id": context_id,
                        "n_samples": str(enc_b.n_samples),
                        "slot_count": str(enc_b.slot_count),
                        "name": f"hist_bucket_{k}",
                    },
                    files=files,
                )
                r.raise_for_status()
                bucket_data_ids.append(r.json()["data_id"])
            r = client.post(
                f"{server_url}/compute/histogram",
                json={"bucket_data_ids": bucket_data_ids, "context_id": context_id},
            )
            r.raise_for_status()
            result_blobs = r.json()["result_chunks_b64"]
            server_eval_ms = r.json()["eval_time_ms"]
        timings.transport += (time.perf_counter() - t0) * 1000 - server_eval_ms
        timings.eval_server = server_eval_ms

        t0 = time.perf_counter()
        counts = []
        for b64 in result_blobs:
            ct = ts.ckks_vector_from(ctx, base64.b64decode(b64))
            counts.append(ct.decrypt()[0])
        timings.decrypt = (time.perf_counter() - t0) * 1000

        hist = P.Histogram(edges=edges, counts=np.round(counts).astype(np.int64))
        return hist, timings

    # Statystyki skalarne (mean / variance / sum)
    t0 = time.perf_counter()
    with httpx.Client(timeout=300.0) as client:
        r = client.post(
            f"{server_url}/compute/{stat}",
            json={"data_id": data_id, "context_id": context_id},
        )
        r.raise_for_status()
        result_blob_b64 = r.json()["result_b64"]
        server_eval_ms = r.json()["eval_time_ms"]

    timings.transport += (time.perf_counter() - t0) * 1000 - server_eval_ms
    timings.eval_server = server_eval_ms

    t0 = time.perf_counter()
    result_ct = ts.ckks_vector_from(ctx, base64.b64decode(result_blob_b64))
    value = decrypt_scalar(result_ct)
    timings.decrypt = (time.perf_counter() - t0) * 1000

    return value, timings


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────


def _format_timings(t: Timings, n: int) -> str:
    lines = [
        f"  Keygen:         {t.keygen:8.2f} ms",
        f"  Szyfrowanie:    {t.encrypt:8.2f} ms",
        f"  Obliczenie:     {t.eval_server:8.2f} ms  (serwer)",
        f"  Deszyfracja:    {t.decrypt:8.2f} ms",
    ]
    if t.transport > 0:
        lines.append(f"  Transport:      {t.transport:8.2f} ms  (HTTP)")
    lines.append(f"  Razem HE:       {t.total_he():8.2f} ms")
    lines.append(f"  Dla N = {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Klient lekarza — analiza w HE.")
    parser.add_argument("--csv", required=True, help="Ścieżka do patients.csv")
    parser.add_argument(
        "--column", required=True, help="Pierwsza kolumna (np. systolic_bp)"
    )
    parser.add_argument(
        "--column2",
        default=None,
        help="Druga kolumna — wymagana dla --stat correlation (np. diastolic_bp)",
    )
    parser.add_argument(
        "--stat",
        choices=["mean", "variance", "sum", "histogram", "correlation"],
        default="mean",
        help="Statystyka do wyliczenia",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Tryb lokalny (bez serwera). Bez --server domyślnie LOCAL.",
    )
    parser.add_argument(
        "--server",
        type=str,
        default=None,
        help="URL serwera FastAPI, np. http://localhost:8000",
    )
    parser.add_argument(
        "--buckets", type=int, default=30, help="Liczba bucketów dla histogramu/mediany"
    )
    args = parser.parse_args(argv)

    if args.stat == "correlation" and not args.column2:
        print("Korelacja Pearsona wymaga --column2 (druga zmienna).", file=sys.stderr)
        return 1

    if not args.local and not args.server:
        args.local = True

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Brak pliku {csv_path}. Wygeneruj go najpierw:", file=sys.stderr)
        print("  uv run python -m src.data.preprocess --fake 1000", file=sys.stderr)
        return 1

    df = pd.read_csv(csv_path, dtype={"pesel": str})
    if args.column not in df.columns:
        print(f"Brak kolumny '{args.column}'. Dostępne: {list(df.columns)}", file=sys.stderr)
        return 1
    if args.column2 and args.column2 not in df.columns:
        print(f"Brak kolumny '{args.column2}'. Dostępne: {list(df.columns)}", file=sys.stderr)
        return 1

    if args.column2:
        pair = df[[args.column, args.column2]].dropna()
        values_x = pair[args.column].to_numpy(dtype=np.float64)
        values_y = pair[args.column2].to_numpy(dtype=np.float64)
    else:
        values_x = df[args.column].dropna().to_numpy(dtype=np.float64)
        values_y = None

    n = int(values_x.size)
    print(
        f"[client] Wczytano N={n} "
        + (
            f"(kolumny '{args.column}' × '{args.column2}', wiersze bez NaN)"
            if args.column2
            else f"wartości z kolumny '{args.column}'"
        )
        + f" z {csv_path}"
    )

    # --- Plaintext oracle
    t0 = time.perf_counter()
    if args.stat == "mean":
        oracle = P.mean(values_x)
    elif args.stat == "variance":
        oracle = P.variance(values_x)
    elif args.stat == "sum":
        oracle = float(np.sum(values_x))
    elif args.stat == "histogram":
        lo, hi = float(values_x.min()), float(values_x.max())
        pad = (hi - lo) * 0.001 if hi > lo else 1.0
        edges = np.linspace(lo - pad, hi + pad, args.buckets + 1)
        oh = P.make_one_hot(values_x, edges)
        oracle = P.histogram_from_one_hot(oh, edges)
    else:  # correlation
        assert values_y is not None
        oracle = P.correlation_pearson(values_x, values_y)
    t_oracle = (time.perf_counter() - t0) * 1000

    # --- HE
    if args.local:
        print("[client] Tryb LOCAL — bez sieci")
        he_value, timings = run_local(
            values_x,
            args.stat,
            values_y=values_y,
            n_buckets=args.buckets,
        )
    else:
        assert args.server is not None
        print(f"[client] Tryb REMOTE — serwer {args.server}")
        he_value, timings = run_remote(
            values_x,
            args.stat,
            args.server,
            values_y=values_y,
            n_buckets=args.buckets,
        )

    # --- Wynik
    print()
    title_cols = (
        f"{args.column} × {args.column2}" if args.column2 else args.column
    )
    print(f"== {args.stat.upper()} ({title_cols}) ==")
    if args.stat == "histogram":
        max_err = int(np.abs(he_value.counts - oracle.counts).max())
        he_med = P.median_from_histogram(he_value)
        np_med = P.median_from_histogram(oracle)
        np_med_exact = P.median(values_x)
        print("  Histogram zliczeń:")
        print(f"    Liczba bucketów: {he_value.k}")
        print(f"    Maks. różnica vs plaintext: {max_err}")
        print(f"  Mediana z HE histogramu:    {he_med:.6f}")
        print(f"  Mediana z plaintext hist.:  {np_med:.6f}")
        print(f"  Mediana dokładna (NumPy):   {np_med_exact:.6f}")
        print(
            f"  Błąd histogramu vs dokładnej: {abs(he_med - np_med_exact)/abs(np_med_exact):.2e}"
        )
    else:
        rel_err = abs(he_value - oracle) / max(abs(oracle), 1e-12)
        print(f"  HE:        {he_value:.6f}")
        print(f"  Plaintext: {oracle:.6f}")
        print(f"  Błąd wzgl.: {rel_err:.3e}")
    print()
    print("== Czasy ==")
    print(_format_timings(timings, n))
    print(f"  Plaintext NumPy: {t_oracle:.4f} ms")
    if t_oracle > 0:
        print(f"  Narzut HE: ~{timings.total_he() / t_oracle:.0f}× wolniej")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
