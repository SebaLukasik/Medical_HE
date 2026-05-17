"""Syntetyczny generator danych pacjentów (gdy nie używamy Synthei).

Cel: dostarczyć powtarzalny, deterministyczny zbiór do benchmarków o
dowolnej wielkości (100..1 000 000 pacjentów). Synthea jest droga do
wygenerowania dużej kohorty, a my chcemy wykres ``czas(N)`` do 100k.

Generujemy realistyczne zakresy dla wskaźników medycznych
(skala populacyjna polska, dorosli) — wartości nie są medycznie
"twardo poprawne" (nie są skorelowane z chorobami), ale rozkłady są
zbliżone do normalnych klinicznych.

OWNER: Osoba 1 ("Dane & PESEL").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .pesel import Gender, generate_pesel


# Realistyczne rozkłady (mean, std) dla dorosłej populacji.
# Wartości referencyjne: Polish guidelines / Synthea calibration.
_DISTRIBUTIONS = {
    # ciśnienie skurczowe i rozkurczowe [mmHg]
    "systolic_bp": (125.0, 18.0),
    "diastolic_bp": (78.0, 11.0),
    # masa, wzrost
    "weight_kg": (78.0, 16.0),
    "height_cm": (171.0, 9.5),
    # BMI – jest pochodną, ale generujemy też niezależnie dla ciekawej korelacji
    "bmi": (26.5, 4.8),
    # glukoza na czczo [mg/dL]
    "glucose_mg_dl": (95.0, 18.0),
    # cholesterol całkowity [mg/dL]
    "cholesterol_mg_dl": (195.0, 35.0),
    # HbA1c [%]
    "hba1c_pct": (5.4, 0.7),
}


@dataclass
class SyntheticConfig:
    n_patients: int = 1000
    seed: int = 42
    # Zakres wieku [lata]
    age_min: int = 18
    age_max: int = 95
    # Reference date dla obliczenia daty urodzenia z wieku
    reference_date: date = date(2026, 5, 17)


def generate_patients(cfg: SyntheticConfig | None = None) -> pd.DataFrame:
    """Wygeneruj DataFrame pacjentów z PESEL + wskaźnikami medycznymi.

    Zwraca DataFrame z kolumnami:

    - ``patient_id`` (UUID-like string, ``"P000001"`` etc.)
    - ``pesel`` (11 cyfr, poprawny algorytm)
    - ``birth_date`` (datetime.date)
    - ``gender`` ("M"/"F")
    - ``age`` (int) — zsynchronizowany z birth_date
    - ``systolic_bp`` (float)
    - ``diastolic_bp`` (float)
    - ``weight_kg`` (float)
    - ``height_cm`` (float)
    - ``bmi`` (float, spójny z weight/height)
    - ``glucose_mg_dl`` (float)
    - ``cholesterol_mg_dl`` (float)
    - ``hba1c_pct`` (float)
    """
    cfg = cfg or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_patients

    # Wiek z rozkładu trochę przesuniętego ku starszym (więcej "pacjentów")
    age = rng.beta(2.5, 2.5, n) * (cfg.age_max - cfg.age_min) + cfg.age_min
    age = age.astype(int)

    # Daty urodzeń (deterministycznie — od ref date)
    birth_dates = [
        cfg.reference_date - timedelta(days=int(a * 365.25 + rng.integers(0, 365)))
        for a in age
    ]

    # Płeć ~50/50 — używamy indeksów 0/1 i mapujemy, bo numpy.choice na
    # obiektach enum zachowuje się dziwnie w NumPy 2.x.
    gender_idx = rng.integers(0, 2, n)
    genders_arr = [Gender.MALE if i == 0 else Gender.FEMALE for i in gender_idx]

    # Wskaźniki medyczne (niezależne, dla uproszczenia)
    data: dict[str, np.ndarray] = {}
    for col, (mu, sigma) in _DISTRIBUTIONS.items():
        # truncate to physiological ranges (no negative BPs etc.)
        vals = rng.normal(mu, sigma, n)
        # Realistyczne klipy minimum, żeby uniknąć ujemnych
        clip_min = max(0.1, mu - 4.0 * sigma)
        clip_max = mu + 5.0 * sigma
        data[col] = np.clip(vals, clip_min, clip_max)

    # BMI rekalibruj do spójności z weight/height (gdy obie są)
    data["bmi"] = data["weight_kg"] / ((data["height_cm"] / 100.0) ** 2)

    # PESELe — pamiętając, że PESEL koduje datę urodzenia + płeć
    import random as _r
    py_rng = _r.Random(cfg.seed + 1)
    pesels: list[str] = []
    seen: set[str] = set()
    for bd, g in zip(birth_dates, genders_arr):
        # Próbujemy do skutku, by uniknąć duplikatów
        while True:
            p = generate_pesel(bd, g, rng=py_rng)
            if p not in seen:
                seen.add(p)
                pesels.append(p)
                break

    df = pd.DataFrame(
        {
            "patient_id": [f"P{i:06d}" for i in range(n)],
            "pesel": pesels,
            "birth_date": birth_dates,
            "gender": [g.value for g in genders_arr],
            "age": age,
            **{k: v for k, v in data.items()},
        }
    )
    return df


def save_patients_csv(df: pd.DataFrame, path: str) -> None:
    """Zapisz pacjentów do CSV (kolumna PESEL jako string, żeby Excel nie zżarł zer)."""
    df.to_csv(path, index=False, encoding="utf-8")


if __name__ == "__main__":
    df = generate_patients(SyntheticConfig(n_patients=10, seed=42))
    print(df.head())
    print(f"\nKolumny: {list(df.columns)}")
