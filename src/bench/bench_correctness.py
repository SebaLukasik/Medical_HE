"""Benchmark poprawności: HE vs plaintext na syntetycznych danych.

Generuje N pacjentów (różne rozkłady wskaźników), liczy wszystkie statystyki
dwiema ścieżkami i raportuje błąd względny.

To jest **pierwsza** rzecz do pokazania na prezentacji — dowód, że HE daje
ten sam wynik co plaintext (poniżej 10⁻⁵, zazwyczaj 10⁻⁷).

Wynik: tabelka w STDOUT + CSV w ``src/bench/results/correctness.csv``.

OWNER: Osoba 3 ("Serwer & benchmark").
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..crypto.codec import decrypt_scalar, encrypt_column
from ..crypto.context import make_context
from ..data.synthetic import SyntheticConfig, generate_patients
from ..plaintext import stats_plain as P
from ..server import stats_he as H


COLUMNS_TO_TEST = ["systolic_bp", "bmi", "glucose_mg_dl", "cholesterol_mg_dl"]


def bench(n_patients: int, seed: int = 42, n_buckets: int = 30) -> pd.DataFrame:
    print(f"[bench-correctness] Generuję {n_patients} pacjentów (seed={seed})...")
    df = generate_patients(SyntheticConfig(n_patients=n_patients, seed=seed))

    print(f"[bench-correctness] Tworzę kontekst CKKS...")
    ctx = make_context()

    rows: list[dict] = []
    for col in COLUMNS_TO_TEST:
        values = df[col].to_numpy(dtype=np.float64)
        n = values.size

        # --- Plaintext ---
        oracle_mean = P.mean(values)
        oracle_var = P.variance(values)
        oracle_std = P.std(values)
        oracle_median = P.median(values)

        # --- HE: mean, variance ---
        enc = encrypt_column(values, ctx)
        he_mean = decrypt_scalar(H.he_mean(enc))
        he_var = decrypt_scalar(H.he_variance(enc))
        he_std = float(np.sqrt(max(he_var, 0.0)))

        # --- HE: histogram → mediana ---
        lo, hi = float(values.min()), float(values.max())
        pad = (hi - lo) * 0.001 if hi > lo else 1.0
        edges = np.linspace(lo - pad, hi + pad, n_buckets + 1)
        oh = P.make_one_hot(values, edges)
        bucket_cols = [encrypt_column(oh[:, k], ctx) for k in range(oh.shape[1])]
        he_counts_ct = H.he_histogram(bucket_cols)
        he_counts = np.array([decrypt_scalar(c) for c in he_counts_ct])
        he_hist = P.Histogram(
            edges=edges, counts=np.round(he_counts).astype(np.int64)
        )
        he_median = P.median_from_histogram(he_hist)

        def rel(he: float, oracle: float) -> float:
            return abs(he - oracle) / max(abs(oracle), 1e-12)

        rows.append(
            {
                "n_patients": n,
                "column": col,
                "stat": "mean",
                "he_value": he_mean,
                "plain_value": oracle_mean,
                "rel_error": rel(he_mean, oracle_mean),
            }
        )
        rows.append(
            {
                "n_patients": n,
                "column": col,
                "stat": "variance",
                "he_value": he_var,
                "plain_value": oracle_var,
                "rel_error": rel(he_var, oracle_var),
            }
        )
        rows.append(
            {
                "n_patients": n,
                "column": col,
                "stat": "std",
                "he_value": he_std,
                "plain_value": oracle_std,
                "rel_error": rel(he_std, oracle_std),
            }
        )
        rows.append(
            {
                "n_patients": n,
                "column": col,
                "stat": "median_from_histogram",
                "he_value": he_median,
                "plain_value": oracle_median,
                "rel_error": rel(he_median, oracle_median),
            }
        )

    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark poprawności: HE vs plaintext."
    )
    parser.add_argument("--n", type=int, default=1000, help="Liczba pacjentów")
    parser.add_argument(
        "--out",
        type=str,
        default="src/bench/results/correctness.csv",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--buckets", type=int, default=30)
    args = parser.parse_args(argv)

    df = bench(args.n, args.seed, args.buckets)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"[bench-correctness] Zapisano: {out}")
    print()
    print("== Wyniki ==")
    # Ładnie sformatowane:
    pd.options.display.float_format = "{:.6g}".format
    print(df.to_string(index=False))
    print()
    print("== Statystyka błędów względnych ==")
    print(df.groupby("stat")["rel_error"].agg(["max", "mean", "min"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
