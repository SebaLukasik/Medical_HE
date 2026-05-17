"""Baseline NumPy: dokładnie ten sam zestaw statystyk, ale w plaintekście.

Cel: pełni rolę **oracle** w testach poprawności — wynik HE powinien
różnić się od tego o $\\leq 10^{-5}$ (zazwyczaj $10^{-7}$).

OWNER: Osoba 1 ("Dane & PESEL") lub Osoba 3, do uzgodnienia.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class Histogram:
    """Histogram: brzegi (K+1 wartości) + zliczenia (K wartości)."""

    edges: np.ndarray  # shape (K+1,)
    counts: np.ndarray  # shape (K,)

    @property
    def n(self) -> int:
        return int(self.counts.sum())

    @property
    def k(self) -> int:
        return int(self.counts.size)


def make_one_hot(
    values: Sequence[float] | np.ndarray,
    edges: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Zamień wektor wartości na macierz one-hot względem przedziałów ``edges``.

    Wartości spoza zakresu [edges[0], edges[-1]] są przypisywane odpowiednio
    do pierwszego lub ostatniego bucketu (clip).

    Returns
    -------
    np.ndarray
        Macierz shape (N, K), wartości w {0.0, 1.0}.
    """
    values = np.asarray(values, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.float64)
    k = edges.size - 1
    # np.digitize zwraca indeks bucketu (1..K dla wartości w zakresie)
    idx = np.clip(np.digitize(values, edges, right=False), 1, k) - 1
    one_hot = np.zeros((values.size, k), dtype=np.float64)
    one_hot[np.arange(values.size), idx] = 1.0
    return one_hot


def histogram_from_one_hot(one_hot: np.ndarray, edges: Sequence[float]) -> Histogram:
    """Złóż histogram z macierzy one-hot (suma po pacjentach)."""
    counts = one_hot.sum(axis=0).astype(np.int64)
    return Histogram(edges=np.asarray(edges, dtype=np.float64), counts=counts)


def median_from_histogram(h: Histogram) -> float:
    """Mediana z histogramu z interpolacją liniową wewnątrz bucketu.

    Klasyczne podejście (Tukey): w bucketcie, w którym leży N/2-ty pacjent,
    interpolujemy liniowo zakładając równomierne rozłożenie.
    """
    if h.n == 0:
        raise ValueError("Pusty histogram")
    target = h.n / 2.0
    cum = np.cumsum(h.counts)
    # Pierwszy bucket, gdzie cum >= target
    bucket = int(np.searchsorted(cum, target, side="left"))
    bucket = min(bucket, h.k - 1)
    prev_cum = float(cum[bucket - 1]) if bucket > 0 else 0.0
    in_bucket = float(h.counts[bucket])
    if in_bucket == 0:
        # zdegenerowany: pusty docelowy bucket — bierzemy lewy brzeg
        return float(h.edges[bucket])
    left = float(h.edges[bucket])
    right = float(h.edges[bucket + 1])
    width = right - left
    return left + width * (target - prev_cum) / in_bucket


def mean(values: Sequence[float] | np.ndarray) -> float:
    return float(np.mean(values))


def variance(values: Sequence[float] | np.ndarray, *, ddof: int = 0) -> float:
    """Wariancja populacyjna (ddof=0) — pasuje do naszego HE.

    Uwaga: w HE używamy ``E[X^2] - E[X]^2`` (forma populacyjna). Gdyby chcieć
    wariancję próbną (ddof=1), trzeba przeskalować na koniec o ``N/(N-1)``.
    """
    return float(np.var(values, ddof=ddof))


def std(values: Sequence[float] | np.ndarray, *, ddof: int = 0) -> float:
    return float(np.std(values, ddof=ddof))


def median(values: Sequence[float] | np.ndarray) -> float:
    """Dokładna mediana (NumPy) — do porównań z medianą histogramową."""
    return float(np.median(values))


def correlation_pearson(
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
) -> float:
    """Współczynnik korelacji Pearsona w plaintekście."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    return float(np.corrcoef(x, y)[0, 1])


def all_summary(values: Sequence[float] | np.ndarray, *, n_buckets: int = 30) -> dict[str, float]:
    """Komplet statystyk plaintext do tabelki porównawczej (mean, var, std, median).

    Mediana liczona przez histogram (dla zachowania spójności z HE) — w innym
    wywołaniu zobaczycie też ``np.median`` jako oracle dokładny.
    """
    values = np.asarray(values, dtype=np.float64)
    lo, hi = float(values.min()), float(values.max())
    # Lekkie rozszerzenie, żeby brzegi nie ucięły wartości skrajnych:
    pad = (hi - lo) * 0.001 if hi > lo else 1.0
    edges = np.linspace(lo - pad, hi + pad, n_buckets + 1)
    oh = make_one_hot(values, edges)
    hist = histogram_from_one_hot(oh, edges)
    return {
        "mean": mean(values),
        "variance": variance(values),
        "std": std(values),
        "median_exact": median(values),
        "median_from_histogram": median_from_histogram(hist),
        "n": int(values.size),
    }
