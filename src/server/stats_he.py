"""Statystyki na zaszyfrowanych kolumnach (HE).

Wszystkie funkcje **nie wymagają ``secret_key``** — działają na ciphertekstach
i kluczach ewaluacji (relin, galois). Tak właśnie pracuje serwer.

Wynikiem jest ``ts.CKKSVector`` (ciphertext) — wartość w slocie 0, którą
klient potem odszyfruje.

Co tu jest:

- ``he_sum``         — suma elementów (rotacje Galois + agregacja chunków).
- ``he_mean``        — średnia (``sum * 1/N``).
- ``he_variance``    — wariancja populacyjna (``E[X²] - E[X]²``).
- ``he_histogram``   — histogram z one-hot wektorów (do mediany).
- ``he_correlation_components`` — komponenty korelacji Pearsona.

Czego tu **nie** ma:

- ``he_std`` — pierwiastek z wariancji wymagałby aproksymacji wielomianowej
  (Newton). Klient liczy ``sqrt`` na odszyfrowanej wariancji — to jest
  bezpieczne (klient i tak widzi wariancję jako wynik).

OWNER: Osoba 3 ("Serwer & benchmark").
"""

from __future__ import annotations

import tenseal as ts

from ..crypto.codec import EncryptedColumn


def he_sum(column: EncryptedColumn) -> ts.CKKSVector:
    """Suma wszystkich wartości w kolumnie.

    Strategia:
        Dla każdego chunku liczymy ``chunk.sum()`` (rotacje Galois log₂(slots)
        razy → wynik w slocie 0). Sumujemy ciphertexty (operacja element-wise
        — wartość w slocie 0 sumuje się jak suma sum chunków).
    """
    if not column.chunks:
        raise ValueError("Pusta kolumna")
    total = column.chunks[0].sum()
    for ct in column.chunks[1:]:
        total = total + ct.sum()
    return total


def he_mean(column: EncryptedColumn) -> ts.CKKSVector:
    """Średnia: ``sum / N``.

    ``N`` jest publicznym metadata (klient i serwer go znają — to nie jest
    "tajne"). Mnożymy ciphertext przez plaintext-skalar ``1/N`` (operacja
    tania, nie konsumuje poziomu).
    """
    n = column.n_samples
    if n <= 0:
        raise ValueError("n_samples musi być > 0")
    return he_sum(column) * (1.0 / n)


def he_sum_of_squares(column: EncryptedColumn) -> ts.CKKSVector:
    """Suma kwadratów: ``Σ xᵢ²``.

    Wewnętrznie używana w wariancji. Wykonuje **mnożenie ciphertext × ciphertext**
    dla każdego chunku — to konsumuje 1 poziom z budżetu mnożeń.
    """
    if not column.chunks:
        raise ValueError("Pusta kolumna")
    # Najpierw kwadraty per chunk (element-wise self-mult)
    squared_sums: list[ts.CKKSVector] = []
    for ct in column.chunks:
        squared = ct * ct  # element-wise, konsumuje 1 poziom
        squared_sums.append(squared.sum())
    total = squared_sums[0]
    for s in squared_sums[1:]:
        total = total + s
    return total


def he_variance(column: EncryptedColumn) -> ts.CKKSVector:
    """Wariancja populacyjna w formie rozwiniętej.

    .. math::
        \\sigma^2 = \\frac{1}{N} \\sum_i x_i^2 - \\bar{x}^2

    Głębokość mnożeń:
        - ``x * x`` w sumie kwadratów → poziom 1
        - ``mean * mean`` → poziom 2

    Łącznie 2 poziomy — mieści się w domyślnym kontekście ``[60,40,40,60]``.
    """
    n = column.n_samples
    mean_sq = he_sum_of_squares(column) * (1.0 / n)
    mean_x = he_mean(column)
    return mean_sq - (mean_x * mean_x)


def he_histogram(
    one_hot_columns: list[EncryptedColumn],
) -> list[ts.CKKSVector]:
    """Histogram: dla każdego bucketu k zwraca **zaszyfrowaną liczność**.

    Argument:
        ``one_hot_columns[k]`` to ``EncryptedColumn`` długości N, w którym
        i-ty wpis to 1.0 jeśli i-ty pacjent jest w bucketcie k, w przeciwnym
        razie 0.0. Klient prepuje to **w plaintekście** przed wysłaniem.

    Wynik:
        Lista K ciphertextów, każdy ze skalarem (count_k) w slocie 0.

    Złożoność po stronie serwera: tylko **dodawania** + ``sum()`` (rotacje).
    Brak mnożeń ciphertext × ciphertext → 0 zużycia poziomów.
    """
    return [he_sum(col) for col in one_hot_columns]


def he_correlation_components(
    x: EncryptedColumn,
    y: EncryptedColumn,
) -> dict[str, ts.CKKSVector]:
    """Komponenty potrzebne do korelacji Pearsona.

    Pełen wzór ($N \\bar{x}\\bar{y}$ etc.) wymagałby dzielenia w HE (kosztowne).
    Zamiast tego serwer zwraca składowe:

    - sum_x, sum_y, sum_x2, sum_y2, sum_xy

    Klient odszyfrowuje, sam liczy korelację w plaintekście. To realistyczny
    wzorzec: HE dostarcza składowe, klient finalizuje.

    Głębokość: 1 poziom (``x*y``, ``x*x``, ``y*y``).
    """
    if x.n_samples != y.n_samples:
        raise ValueError("Kolumny muszą mieć tę samą długość")
    if x.n_chunks() != y.n_chunks():
        raise ValueError("Kolumny muszą mieć tę samą liczbę chunków")

    # sum_xy: suma elementarnych iloczynów
    sum_xy_chunks: list[ts.CKKSVector] = []
    for xc, yc in zip(x.chunks, y.chunks):
        sum_xy_chunks.append((xc * yc).sum())
    sum_xy = sum_xy_chunks[0]
    for s in sum_xy_chunks[1:]:
        sum_xy = sum_xy + s

    return {
        "sum_x": he_sum(x),
        "sum_y": he_sum(y),
        "sum_x2": he_sum_of_squares(x),
        "sum_y2": he_sum_of_squares(y),
        "sum_xy": sum_xy,
        # n nie jest tajne — klient zna z metadanych
    }


__all__ = [
    "he_sum",
    "he_mean",
    "he_sum_of_squares",
    "he_variance",
    "he_histogram",
    "he_correlation_components",
]
