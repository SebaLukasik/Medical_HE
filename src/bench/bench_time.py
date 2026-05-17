"""Benchmark czasu: jak skaluje się HE w zależności od liczby pacjentów.

Dla każdego N ∈ {sizes} mierzymy:

- ``encrypt`` — czas zaszyfrowania kolumny (klient)
- ``eval_mean`` — czas obliczenia średniej (serwer)
- ``eval_variance`` — czas wariancji (serwer)
- ``eval_histogram`` — czas histogramu (serwer)
- ``decrypt`` — czas deszyfracji wyniku
- ``plain_mean``, ``plain_variance``, ``plain_median`` — czasy NumPy (oracle)

Wynik: CSV w ``src/bench/results/timing.csv``. Każdy pomiar powtarzamy
``--repeat`` razy i bierzemy medianę.

OWNER: Osoba 3 ("Serwer & benchmark").
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..crypto.codec import decrypt_scalar, encrypt_column
from ..crypto.context import make_context
from ..data.synthetic import SyntheticConfig, generate_patients
from ..plaintext import stats_plain as P
from ..server import stats_he as H


def _bench(fn: Callable[[], object], repeat: int = 3) -> float:
    """Zwraca medianę czasu wykonania w ms."""
    times: list[float] = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def bench_size(
    n: int,
    *,
    seed: int = 42,
    repeat: int = 3,
    n_buckets: int = 20,
) -> dict[str, float]:
    df = generate_patients(SyntheticConfig(n_patients=n, seed=seed))
    values = df["systolic_bp"].to_numpy(dtype=np.float64)

    # Plaintext (NumPy)
    t_plain_mean = _bench(lambda: P.mean(values), repeat)
    t_plain_var = _bench(lambda: P.variance(values), repeat)
    t_plain_median = _bench(lambda: P.median(values), repeat)

    # Kontekst (raz — keygen jest stały, nie zależy od N)
    t0 = time.perf_counter()
    ctx = make_context()
    t_keygen = (time.perf_counter() - t0) * 1000

    # HE: encrypt
    t_encrypt = _bench(lambda: encrypt_column(values, ctx), repeat)

    enc = encrypt_column(values, ctx)
    n_chunks = enc.n_chunks()

    # HE: mean
    t_mean = _bench(lambda: H.he_mean(enc), repeat)

    # HE: variance
    t_var = _bench(lambda: H.he_variance(enc), repeat)

    # HE: decrypt scalar (1 ciphertext result)
    res_mean = H.he_mean(enc)
    t_decrypt = _bench(lambda: decrypt_scalar(res_mean), repeat)

    # HE: histogram
    lo, hi = float(values.min()), float(values.max())
    pad = (hi - lo) * 0.001 if hi > lo else 1.0
    edges = np.linspace(lo - pad, hi + pad, n_buckets + 1)
    oh = P.make_one_hot(values, edges)
    # Czas: enc + eval (osobno)
    t0 = time.perf_counter()
    bucket_cols = [encrypt_column(oh[:, k], ctx) for k in range(oh.shape[1])]
    t_hist_encrypt = (time.perf_counter() - t0) * 1000

    t_hist_eval = _bench(lambda: H.he_histogram(bucket_cols), repeat)

    return {
        "n_patients": n,
        "n_chunks": n_chunks,
        "encrypt_ms": t_encrypt,
        "keygen_ms": t_keygen,
        "decrypt_ms": t_decrypt,
        "he_mean_ms": t_mean,
        "he_variance_ms": t_var,
        "he_hist_encrypt_ms": t_hist_encrypt,
        "he_hist_eval_ms": t_hist_eval,
        "plain_mean_ms": t_plain_mean,
        "plain_variance_ms": t_plain_var,
        "plain_median_ms": t_plain_median,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark czasu w funkcji N.")
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[100, 500, 1000, 5000, 10000, 50000],
        help="Rozmiary N do przetestowania",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--out", type=str, default="src/bench/results/timing.csv"
    )
    parser.add_argument("--buckets", type=int, default=20)
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for n in args.sizes:
        print(f"[bench-time] N = {n}...")
        rows.append(bench_size(n, repeat=args.repeat, n_buckets=args.buckets))

    df = pd.DataFrame(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print()
    print(f"[bench-time] Zapisano: {out}")
    print()
    print("== Wyniki ==")
    pd.options.display.float_format = "{:.2f}".format
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
