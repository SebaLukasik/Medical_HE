"""Wykresy z wyników benchmarków (matplotlib) — do prezentacji.

Generuje:

1. ``time_scaling.png``   — czas vs N (log-log) dla mean, variance, histogram
2. ``he_vs_plain.png``    — czas HE vs NumPy (bar chart, jedno N)
3. ``correctness.png``    — błąd względny vs N (jeśli mamy wiele N)

Wynik w ``src/bench/results/``.

OWNER: Osoba 3 ("Serwer & benchmark").
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # noqa: E402  — backend bez DISPLAY
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd


def plot_time_scaling(timing_csv: Path, out_path: Path) -> None:
    df = pd.read_csv(timing_csv)
    fig, ax = plt.subplots(figsize=(9, 6))

    ax.plot(df["n_patients"], df["he_mean_ms"], "o-", label="HE: mean")
    ax.plot(df["n_patients"], df["he_variance_ms"], "s-", label="HE: variance")
    ax.plot(df["n_patients"], df["he_hist_eval_ms"], "^-", label="HE: histogram (eval)")
    ax.plot(df["n_patients"], df["encrypt_ms"], "d--", label="HE: encrypt (klient)", color="gray")
    ax.plot(df["n_patients"], df["plain_mean_ms"], "x:", label="NumPy: mean", color="green")
    ax.plot(df["n_patients"], df["plain_variance_ms"], "+:", label="NumPy: variance", color="darkgreen")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Liczba pacjentow N")
    ax.set_ylabel("Czas [ms]")
    ax.set_title("Skalowanie czasu obliczen: HE vs NumPy")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"  -> {out_path}")


def plot_he_vs_plain_bars(timing_csv: Path, out_path: Path) -> None:
    df = pd.read_csv(timing_csv)
    # Bierzemy największe N
    row = df.iloc[-1]
    n = int(row["n_patients"])

    labels = ["mean", "variance", "histogram"]
    he = [row["he_mean_ms"], row["he_variance_ms"], row["he_hist_eval_ms"]]
    plain = [row["plain_mean_ms"], row["plain_variance_ms"], row["plain_median_ms"]]

    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    bars1 = ax.bar(x - width / 2, he, width, label="HE (CKKS)", color="tab:blue")
    bars2 = ax.bar(x + width / 2, plain, width, label="Plaintext (NumPy)", color="tab:green")

    for bars in (bars1, bars2):
        for b in bars:
            h = b.get_height()
            ax.annotate(
                f"{h:.2f} ms",
                xy=(b.get_x() + b.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Czas [ms] (log)")
    ax.set_title(f"Czas obliczen HE vs NumPy ({n} pacjentow)")
    ax.legend()
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"  -> {out_path}")


def plot_correctness_box(correctness_csv: Path, out_path: Path) -> None:
    df = pd.read_csv(correctness_csv)
    stats = sorted(df["stat"].unique())
    data = [df[df["stat"] == s]["rel_error"].to_numpy() for s in stats]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(data, labels=stats, showfliers=True)
    ax.set_yscale("log")
    ax.set_ylabel("Blad wzgledny |HE - NumPy| / |NumPy| (log)")
    ax.set_title("Poprawnosc: blad wzgledny HE vs plaintext")
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.axhline(1e-5, color="red", linestyle="--", linewidth=1, label="prog 10^-5")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"  -> {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wygeneruj wykresy z benchmarków.")
    parser.add_argument(
        "--timing",
        type=str,
        default="src/bench/results/timing.csv",
    )
    parser.add_argument(
        "--correctness",
        type=str,
        default="src/bench/results/correctness.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="src/bench/results",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timing = Path(args.timing)
    correctness = Path(args.correctness)

    if timing.exists():
        print("[plots] Wykres skalowania czasu:")
        plot_time_scaling(timing, out_dir / "time_scaling.png")
        print("[plots] Wykres porównawczy HE vs Plain:")
        plot_he_vs_plain_bars(timing, out_dir / "he_vs_plain.png")
    else:
        print(f"  Brak {timing} — uruchom najpierw: python -m src.bench.bench_time")

    if correctness.exists():
        print("[plots] Wykres poprawności (box):")
        plot_correctness_box(correctness, out_dir / "correctness.png")
    else:
        print(f"  Brak {correctness} — uruchom najpierw: python -m src.bench.bench_correctness")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
