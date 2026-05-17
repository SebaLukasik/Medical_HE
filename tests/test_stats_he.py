"""Testy parametryczne: statystyki HE vs plaintext.

Sprawdzają, że dla różnych rozkładów i rozmiarów N błąd względny między HE a
NumPy jest poniżej zadanych progów.

Uruchomienie:
    uv run pytest tests/test_stats_he.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from src.crypto.codec import decrypt_scalar, encrypt_column
from src.crypto.context import make_context
from src.plaintext import stats_plain as P
from src.server import stats_he as H


# Tworzymy kontekst raz na cały moduł (keygen ~500ms — drogo na test)
@pytest.fixture(scope="module")
def context():
    return make_context()


@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(seed=42)


# ──────────────────────────────────────────────────────────────────────────────
# mean / sum
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n, mean, std",
    [
        (100, 25.0, 4.0),       # BMI
        (1000, 120.0, 15.0),    # ciśnienie skurczowe
        (5000, 95.0, 18.0),     # glukoza
        (10000, 195.0, 35.0),   # cholesterol
    ],
)
def test_mean_matches_numpy(context, rng, n, mean, std):
    values = rng.normal(mean, std, n)
    enc = encrypt_column(values, context)
    he = decrypt_scalar(H.he_mean(enc))
    np_val = P.mean(values)
    rel = abs(he - np_val) / abs(np_val)
    assert rel < 1e-5, f"rel_err={rel:.2e}, HE={he}, NumPy={np_val}"


def test_sum_matches_numpy(context, rng):
    values = rng.normal(100, 20, 4096)  # dokładnie 1 chunk
    enc = encrypt_column(values, context)
    he = decrypt_scalar(H.he_sum(enc))
    np_val = float(values.sum())
    rel = abs(he - np_val) / abs(np_val)
    assert rel < 1e-5


def test_sum_across_chunks(context, rng):
    """Suma działa poprawnie, gdy N wymusza > 1 chunk."""
    values = rng.normal(100, 20, 10000)  # 3 chunks (4096*3 = 12288)
    enc = encrypt_column(values, context)
    assert enc.n_chunks() >= 2
    he = decrypt_scalar(H.he_sum(enc))
    np_val = float(values.sum())
    rel = abs(he - np_val) / abs(np_val)
    assert rel < 1e-5


# ──────────────────────────────────────────────────────────────────────────────
# variance / std
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [100, 1000, 5000])
def test_variance_matches_numpy(context, rng, n):
    values = rng.normal(50, 10, n)
    enc = encrypt_column(values, context)
    he = decrypt_scalar(H.he_variance(enc))
    np_val = P.variance(values)
    rel = abs(he - np_val) / abs(np_val)
    assert rel < 1e-4, f"rel_err={rel:.2e}"


def test_std_via_sqrt_after_decrypt(context, rng):
    """Std liczone jako sqrt(variance) na kliencie po deszyfracji."""
    values = rng.normal(120, 15, 1000)
    enc = encrypt_column(values, context)
    he_var = decrypt_scalar(H.he_variance(enc))
    he_std = float(np.sqrt(max(he_var, 0.0)))
    np_std = P.std(values)
    rel = abs(he_std - np_std) / abs(np_std)
    assert rel < 1e-4


# ──────────────────────────────────────────────────────────────────────────────
# histogram → mediana
# ──────────────────────────────────────────────────────────────────────────────


def test_histogram_exact_counts(context, rng):
    """Histogram zliczeń jest praktycznie idealny (po zaokrągleniu do int)."""
    values = rng.normal(120, 15, 1000)
    edges = np.linspace(values.min() - 0.1, values.max() + 0.1, 21)  # 20 bucketów
    oh = P.make_one_hot(values, edges)

    bucket_cols = [encrypt_column(oh[:, k], context) for k in range(oh.shape[1])]
    he_counts_ct = H.he_histogram(bucket_cols)
    he_counts = np.round([decrypt_scalar(c) for c in he_counts_ct]).astype(np.int64)
    np_counts = oh.sum(axis=0).astype(np.int64)
    assert np.array_equal(he_counts, np_counts)


def test_median_from_histogram_close_to_numpy(context, rng):
    """Mediana z histogramu (HE) leży blisko mediany dokładnej (NumPy).

    Granica: 5% kontekstu (szerokość bucketu). Dla rozkładu N(120, 15) i 30
    bucketów rozpiętość ~10 std → szerokość bucketu ~5. Mediana powinna być
    w obrębie tego.
    """
    values = rng.normal(120, 15, 2000)
    edges = np.linspace(values.min() - 0.1, values.max() + 0.1, 31)
    oh = P.make_one_hot(values, edges)
    bucket_cols = [encrypt_column(oh[:, k], context) for k in range(oh.shape[1])]
    he_counts_ct = H.he_histogram(bucket_cols)
    he_counts = np.round([decrypt_scalar(c) for c in he_counts_ct]).astype(np.int64)
    hist = P.Histogram(edges=edges, counts=he_counts)
    he_med = P.median_from_histogram(hist)
    np_med = P.median(values)
    bucket_width = float(edges[1] - edges[0])
    assert abs(he_med - np_med) < bucket_width, (
        f"HE_median={he_med}, NumPy={np_med}, bucket_width={bucket_width}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# korelacja Pearsona
# ──────────────────────────────────────────────────────────────────────────────


def test_correlation_pearson(context, rng):
    """Korelacja Pearsona z komponentów HE."""
    n = 2000
    x = rng.normal(25, 4, n)
    # y silnie skorelowane z x
    y = 70 + 2.5 * (x - 25) + rng.normal(0, 5, n)

    enc_x = encrypt_column(x, context)
    enc_y = encrypt_column(y, context)
    comps = H.he_correlation_components(enc_x, enc_y)

    sx = decrypt_scalar(comps["sum_x"])
    sy = decrypt_scalar(comps["sum_y"])
    sx2 = decrypt_scalar(comps["sum_x2"])
    sy2 = decrypt_scalar(comps["sum_y2"])
    sxy = decrypt_scalar(comps["sum_xy"])

    num = n * sxy - sx * sy
    den = float(np.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy)))
    he_corr = num / den
    np_corr = P.correlation_pearson(x, y)
    assert abs(he_corr - np_corr) < 1e-4


# ──────────────────────────────────────────────────────────────────────────────
# edge cases
# ──────────────────────────────────────────────────────────────────────────────


def test_empty_column_raises(context):
    enc = encrypt_column([], context)
    enc.chunks = []  # symuluj pusty case (encrypt_column normalnie nie produkuje)
    with pytest.raises(ValueError):
        H.he_sum(enc)


def test_single_chunk_smaller_than_slot_count(context, rng):
    """Małe N (np. 50) — działa poprawnie z padowaniem zerami."""
    values = rng.normal(100, 10, 50)
    enc = encrypt_column(values, context)
    assert enc.n_chunks() == 1
    he_sum = decrypt_scalar(H.he_sum(enc))
    np_sum = float(values.sum())
    rel = abs(he_sum - np_sum) / abs(np_sum)
    assert rel < 1e-6


def test_uniform_distribution(context, rng):
    """Niech rozkład nie będzie normalny — sprawdza brak ukrytych założeń."""
    values = rng.uniform(low=0.0, high=200.0, size=1000)
    enc = encrypt_column(values, context)
    he_mean = decrypt_scalar(H.he_mean(enc))
    np_mean = P.mean(values)
    assert abs(he_mean - np_mean) / abs(np_mean) < 1e-5
