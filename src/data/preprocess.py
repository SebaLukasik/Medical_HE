"""Preprocessing danych pacjentów do ``data/processed/patients.csv``.

Dwa tryby (z linii poleceń):

1. ``--fake N``         — wygeneruj N syntetycznych pacjentów (szybko, do
                          benchmarków).
2. ``--synthea-dir DIR`` — wczytaj CSV-ki z output Synthei (``patients.csv``,
                          ``observations.csv``) i sklej w jeden plik.

Synthea export do CSV ma sztywno określone kolumny — używamy najważniejszych:
- ``patients.csv``:      Id, BIRTHDATE, GENDER
- ``observations.csv``:  PATIENT, DESCRIPTION, VALUE (LOINC kody w innej kolumnie)

Dla każdego pacjenta bierzemy **ostatnią** obserwację każdego typu (latest).

Po stworzeniu — dorzucamy PESEL z naszego generatora (na podstawie BIRTHDATE +
GENDER), żeby dane "wyglądały polsko" w demo.

OWNER: Osoba 1 ("Dane & PESEL").
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .pesel import Gender, generate_pesel
from .synthetic import SyntheticConfig, generate_patients, save_patients_csv


# Mapowanie nazw obserwacji Synthei → nasze kolumny.
# Synthea używa opisów po angielsku. Lista najczęściej spotykanych:
SYNTHEA_OBSERVATION_MAP: dict[str, str] = {
    "Body Height": "height_cm",
    "Body Weight": "weight_kg",
    "Body Mass Index": "bmi",
    "Systolic Blood Pressure": "systolic_bp",
    "Diastolic Blood Pressure": "diastolic_bp",
    "Glucose": "glucose_mg_dl",
    "Total Cholesterol": "cholesterol_mg_dl",
    "Hemoglobin A1c/Hemoglobin.total in Blood": "hba1c_pct",
}


def load_synthea(synthea_dir: str | Path) -> pd.DataFrame:
    """Wczytaj output Synthei (CSV) i wyciągnij wskaźniki medyczne.

    Oczekuje:
        ``{synthea_dir}/patients.csv``
        ``{synthea_dir}/observations.csv``
    """
    synthea_dir = Path(synthea_dir)
    patients_csv = synthea_dir / "patients.csv"
    observations_csv = synthea_dir / "observations.csv"
    if not patients_csv.exists():
        raise FileNotFoundError(f"Nie znaleziono {patients_csv}")
    if not observations_csv.exists():
        raise FileNotFoundError(f"Nie znaleziono {observations_csv}")

    p = pd.read_csv(patients_csv)
    o = pd.read_csv(observations_csv)

    # Standardyzacja kolumn (Synthea ma WIELKIE litery, ale różne wersje
    # nazewnictwa — ostrożnie):
    p.columns = [c.lower() for c in p.columns]
    o.columns = [c.lower() for c in o.columns]

    needed_p = {"id", "birthdate", "gender"}
    if not needed_p.issubset(p.columns):
        raise ValueError(
            f"Brakuje wymaganych kolumn w patients.csv. Mam: {set(p.columns)}"
        )
    needed_o = {"patient", "description", "value"}
    if not needed_o.issubset(o.columns):
        raise ValueError(
            f"Brakuje wymaganych kolumn w observations.csv. Mam: {set(o.columns)}"
        )

    # Filtruj obserwacje do interesujących nas typów
    obs = o[o["description"].isin(SYNTHEA_OBSERVATION_MAP.keys())].copy()
    obs["our_col"] = obs["description"].map(SYNTHEA_OBSERVATION_MAP)
    # VALUE może być stringiem ("145.6") lub liczbą — wymuszamy float
    obs["value"] = pd.to_numeric(obs["value"], errors="coerce")
    obs = obs.dropna(subset=["value"])

    # Dla każdego pacjenta i każdego typu obserwacji bierzemy ostatnią (sortujemy po dacie jeśli jest)
    if "date" in obs.columns:
        obs = obs.sort_values("date")
    latest = obs.groupby(["patient", "our_col"], as_index=False).agg({"value": "last"})

    # Pivot do szerokiej tabeli
    wide = latest.pivot(index="patient", columns="our_col", values="value").reset_index()
    wide = wide.rename(columns={"patient": "id"})

    # Złącz z pacjentami
    merged = p.merge(wide, on="id", how="inner")
    merged["birthdate"] = pd.to_datetime(merged["birthdate"]).dt.date
    merged["gender"] = merged["gender"].str.upper().map(
        {"M": "M", "F": "F", "MALE": "M", "FEMALE": "F"}
    )

    # Dodaj PESEL
    import random as _r
    rng = _r.Random(42)
    pesels: list[str] = []
    seen: set[str] = set()
    for bd, g in zip(merged["birthdate"], merged["gender"]):
        gender = Gender.MALE if g == "M" else Gender.FEMALE
        while True:
            p_value = generate_pesel(bd, gender, rng=rng)
            if p_value not in seen:
                seen.add(p_value)
                pesels.append(p_value)
                break
    merged["pesel"] = pesels

    # Wiek (z dzisiaj — dobre wyniki dla demo)
    from datetime import date
    today = date(2026, 5, 17)
    merged["age"] = merged["birthdate"].apply(
        lambda d: today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    )

    # Uporządkuj kolumny
    cols = ["id", "pesel", "birthdate", "gender", "age"] + [
        c for c in SYNTHEA_OBSERVATION_MAP.values() if c in merged.columns
    ]
    merged = merged[cols].rename(columns={"id": "patient_id", "birthdate": "birth_date"})
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preprocess danych pacjentów do patients.csv."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--synthea-dir",
        type=str,
        help="Katalog z output CSV Synthei (patients.csv + observations.csv)",
    )
    src.add_argument(
        "--fake",
        type=int,
        metavar="N",
        help="Wygeneruj N syntetycznych pacjentów zamiast Synthei",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="data/processed/patients.csv",
        help="Plik wyjściowy (default: data/processed/patients.csv)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Seed dla generatora (--fake)"
    )
    args = parser.parse_args(argv)

    if args.synthea_dir:
        print(f"[preprocess] Ładuję Synthea z {args.synthea_dir}...")
        df = load_synthea(args.synthea_dir)
    else:
        print(f"[preprocess] Generuję {args.fake} syntetycznych pacjentów (seed={args.seed})...")
        df = generate_patients(SyntheticConfig(n_patients=args.fake, seed=args.seed))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_patients_csv(df, str(out_path))
    print(f"[preprocess] OK — zapisano {len(df)} pacjentów do {out_path}")
    print(f"             Kolumny: {list(df.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
