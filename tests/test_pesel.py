"""Testy generatora i walidatora PESEL.

OWNER: Osoba 1 ("Dane & PESEL").

Uruchomienie:  pytest tests/test_pesel.py -v
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data.pesel import (
    Gender,
    age_from_pesel,
    generate_many,
    generate_pesel,
    is_valid_pesel,
    parse_pesel,
)


# ──────────────────────────────────────────────────────────────────────────────
# Znane wartości
# ──────────────────────────────────────────────────────────────────────────────


def test_manual_checksum_example():
    """Ręcznie policzony przykład cyfry kontrolnej.

    Pierwsze 10 cyfr: 4 4 0 5 1 4 0 1 3 5
    Wagi:             1 3 7 9 1 3 7 9 1 3
    Iloczyny:         4 12 0 45 1 12 0 9 3 15  →  suma = 101
    101 mod 10 = 1  →  (10 - 1) mod 10 = 9
    Czyli pełny PESEL: 44051401359, data 1944-05-14, ostatnia osobowa = 5
    (nieparzysta) → mężczyzna.
    """
    parsed = parse_pesel("44051401359")
    assert parsed.birth_date == date(1944, 5, 14)
    assert parsed.gender == Gender.MALE
    assert parsed.checksum == 9


def test_2000s_century_offset():
    # Dla 2003-01-05 mm_code = 1 + 20 = 21.
    # Sprawdzamy przez round-trip — dokładność algorytmu jest sprawdzana niżej.
    pesel = generate_pesel(date(2003, 1, 5), Gender.MALE, rng=random.Random(0))
    parsed = parse_pesel(pesel)
    assert parsed.birth_date == date(2003, 1, 5)
    assert parsed.gender == Gender.MALE
    assert pesel[2:4] == "21"


def test_invalid_length():
    with pytest.raises(ValueError):
        parse_pesel("123")


def test_invalid_chars():
    with pytest.raises(ValueError):
        parse_pesel("4405140135X")


def test_invalid_checksum():
    # Bierzemy poprawny PESEL z wygenerowanego (tym samym seedem) i psujemy
    # ostatnią cyfrę.
    good = generate_pesel(date(1990, 5, 1), Gender.MALE, rng=random.Random(0))
    assert is_valid_pesel(good)
    bad = good[:10] + str((int(good[-1]) + 1) % 10)
    assert not is_valid_pesel(bad)


def test_invalid_date():
    # 30 luty nie istnieje; PESEL ze "spreparowaną" datą musi się wywalić
    # Wybieramy: 02-30 (luty 30): pierwsze 6 cyfr = 000230, wybieramy serial 0000
    first_ten = "0002300000"
    from src.data.pesel import _compute_checksum  # type: ignore

    chk = _compute_checksum(first_ten)
    pesel = first_ten + str(chk)
    with pytest.raises(ValueError):
        parse_pesel(pesel)


# ──────────────────────────────────────────────────────────────────────────────
# Round-trip: każda data dająca się zakodować odzyskuje się 1:1.
# ──────────────────────────────────────────────────────────────────────────────


@given(
    year=st.integers(min_value=1900, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),  # 28 dla bezpieczeństwa
    gender=st.sampled_from([Gender.FEMALE, Gender.MALE]),
)
@settings(max_examples=200, deadline=None)
def test_roundtrip(year, month, day, gender):
    bd = date(year, month, day)
    pesel = generate_pesel(bd, gender, rng=random.Random(0))
    parsed = parse_pesel(pesel)
    assert parsed.birth_date == bd
    assert parsed.gender == gender


def test_century_encoding_1800s():
    pesel = generate_pesel(date(1850, 6, 15), Gender.FEMALE, rng=random.Random(0))
    # czerwiec dla 1800: 6 + 80 = 86
    assert pesel[2:4] == "86"


def test_serial_gender_mismatch_raises():
    with pytest.raises(ValueError):
        generate_pesel(date(1990, 1, 1), Gender.FEMALE, serial="0001")
    with pytest.raises(ValueError):
        generate_pesel(date(1990, 1, 1), Gender.MALE, serial="0000")


# ──────────────────────────────────────────────────────────────────────────────
# generate_many → wszystkie poprawne, unikalne, w zakresie.
# ──────────────────────────────────────────────────────────────────────────────


def test_generate_many_all_valid_and_unique():
    n = 200
    out = generate_many(n, min_year=1950, max_year=2005, seed=123)
    assert len(out) == n
    assert len(set(out)) == n
    for p in out:
        assert is_valid_pesel(p), p
        year = parse_pesel(p).birth_date.year
        assert 1950 <= year <= 2005


# ──────────────────────────────────────────────────────────────────────────────
# Wiek
# ──────────────────────────────────────────────────────────────────────────────


def test_age_basic():
    pesel = generate_pesel(date(2000, 5, 1), Gender.MALE, rng=random.Random(0))
    assert age_from_pesel(pesel, reference=date(2025, 5, 1)) == 25
    assert age_from_pesel(pesel, reference=date(2025, 4, 30)) == 24
