"""Generator i walidator polskiego numeru PESEL.

PESEL = Powszechny Elektroniczny System Ewidencji Ludności. 11 cyfr:

    [RRMMDDPPPPK]
     |  |  |  |  └── cyfra kontrolna
     |  |  |  └───── 4 cyfry osobowe (ostatnia = parzysta dla kobiet,
     |  |  |          nieparzysta dla mężczyzn)
     |  |  └──────── dzień (01..31)
     |  └─────────── miesiąc *z kodem wieku* (patrz tabela)
     └────────────── 2 ostatnie cyfry roku

Kod miesiąca koduje wiek:

  ┌────────────┬────────────────┐
  │ stulecie   │ +offset do mm  │
  ├────────────┼────────────────┤
  │ 1800–1899  │ +80            │
  │ 1900–1999  │ +0             │
  │ 2000–2099  │ +20            │
  │ 2100–2199  │ +40            │
  │ 2200–2299  │ +60            │
  └────────────┴────────────────┘

Cyfra kontrolna: suma ważona pierwszych 10 cyfr × [1,3,7,9,1,3,7,9,1,3] mod 10,
potem (10 - wynik) mod 10.

UWAGA edukacyjna: ten generator nie sprawdza, czy wygenerowany PESEL już
istnieje w realnym rejestrze państwowym. Używamy do testów i syntetycznych
zbiorów danych, nigdy do podszywania się.

OWNER: Osoba 1 ("Dane & PESEL")
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Iterable, Optional


# Wagi z algorytmu cyfry kontrolnej (znana stała, zob. ustawa o ewidencji).
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


class Gender(str, Enum):
    """Płeć kodowana w 10. cyfrze PESEL.

    UWAGA: PESEL koduje płeć binarnie; w danych medycznych można mieć szerszą
    klasyfikację, ale rejestr państwowy używa tylko M/F.
    """

    MALE = "M"
    FEMALE = "F"


@dataclass(frozen=True)
class ParsedPesel:
    """Dane wyciągnięte z PESEL-a."""

    birth_date: date
    gender: Gender
    serial: str  # 4 cyfry osobowe (PPPP)
    checksum: int
    raw: str


# ──────────────────────────────────────────────────────────────────────────────
# Walidacja i parsowanie
# ──────────────────────────────────────────────────────────────────────────────


def _compute_checksum(first_ten: str) -> int:
    """Cyfra kontrolna z pierwszych 10 cyfr PESEL.

    >>> _compute_checksum("4405140135")  # historyczny przykład z ustawy
    8
    """
    if len(first_ten) != 10 or not first_ten.isdigit():
        raise ValueError("Oczekuję 10 cyfr.")
    s = sum(int(d) * w for d, w in zip(first_ten, _PESEL_WEIGHTS))
    return (10 - s % 10) % 10


def _decode_month(mm_code: int) -> tuple[int, int]:
    """Z miesiąca z kodem wieku zwraca (rok_pełny_offset_stulecia, miesiąc).

    Zwracana wartość to (offset_stulecia, miesiąc_1_12).
    """
    if 1 <= mm_code <= 12:
        return 1900, mm_code
    if 21 <= mm_code <= 32:
        return 2000, mm_code - 20
    if 41 <= mm_code <= 52:
        return 2100, mm_code - 40
    if 61 <= mm_code <= 72:
        return 2200, mm_code - 60
    if 81 <= mm_code <= 92:
        return 1800, mm_code - 80
    raise ValueError(f"Nieprawidłowy kod miesiąca w PESEL: {mm_code}")


def _encode_month(year: int, month: int) -> int:
    """Zakoduj miesiąc + stulecie w polu MM."""
    if not 1 <= month <= 12:
        raise ValueError("Miesiąc 1..12")
    if 1800 <= year <= 1899:
        return month + 80
    if 1900 <= year <= 1999:
        return month
    if 2000 <= year <= 2099:
        return month + 20
    if 2100 <= year <= 2199:
        return month + 40
    if 2200 <= year <= 2299:
        return month + 60
    raise ValueError(f"PESEL nie obsługuje roku {year}")


def is_valid_pesel(pesel: str) -> bool:
    """Czy PESEL ma poprawny format, datę i cyfrę kontrolną."""
    try:
        parse_pesel(pesel)
        return True
    except ValueError:
        return False


def parse_pesel(pesel: str) -> ParsedPesel:
    """Zdekoduj PESEL na datę urodzenia, płeć i cyfrę kontrolną.

    Rzuca ValueError, jeśli format, data lub checksum są błędne.
    """
    if not isinstance(pesel, str):
        raise ValueError("PESEL musi być stringiem.")
    if len(pesel) != 11 or not pesel.isdigit():
        raise ValueError("PESEL musi mieć dokładnie 11 cyfr.")

    yy = int(pesel[0:2])
    mm_code = int(pesel[2:4])
    dd = int(pesel[4:6])
    serial = pesel[6:10]
    chk = int(pesel[10])

    century_offset, mm = _decode_month(mm_code)
    year = century_offset + yy
    try:
        birth = date(year, mm, dd)
    except ValueError as e:
        raise ValueError(f"Nieprawidłowa data {year}-{mm:02d}-{dd:02d}: {e}") from e

    expected_chk = _compute_checksum(pesel[:10])
    if chk != expected_chk:
        raise ValueError(
            f"Cyfra kontrolna {chk} ≠ oczekiwana {expected_chk}."
        )

    # 10. cyfra: parzysta = kobieta, nieparzysta = mężczyzna
    gender = Gender.FEMALE if int(serial[-1]) % 2 == 0 else Gender.MALE

    return ParsedPesel(
        birth_date=birth,
        gender=gender,
        serial=serial,
        checksum=chk,
        raw=pesel,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generowanie
# ──────────────────────────────────────────────────────────────────────────────


def generate_pesel(
    birth_date: date,
    gender: Gender,
    serial: Optional[str] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Wygeneruj poprawny syntaktycznie PESEL.

    Parameters
    ----------
    birth_date : date
        Data urodzenia. PESEL obsługuje lata 1800–2299.
    gender : Gender
        Wymusza parzystość ostatniej cyfry pola serial.
    serial : str | None
        Opcjonalnie konkretne 4 cyfry osobowe; ostatnia musi pasować do płci.
        Jeśli None — losowane.
    rng : random.Random | None
        Generator losowy; przekażcie zalegowanego, aby testy były
        deterministyczne (`random.Random(seed)`).
    """
    rng = rng or random.Random()
    yy = birth_date.year % 100
    mm_code = _encode_month(birth_date.year, birth_date.month)
    dd = birth_date.day

    if serial is None:
        # 4 cyfry; ostatnia musi mieć właściwą parzystość
        first3 = f"{rng.randint(0, 999):03d}"
        last_pool = range(0, 10, 2) if gender == Gender.FEMALE else range(1, 10, 2)
        last = rng.choice(list(last_pool))
        serial = first3 + str(last)
    else:
        if len(serial) != 4 or not serial.isdigit():
            raise ValueError("serial musi być 4-cyfrowym stringiem")
        last = int(serial[-1])
        if gender == Gender.FEMALE and last % 2 != 0:
            raise ValueError("Kobieta wymaga parzystej ostatniej cyfry serial.")
        if gender == Gender.MALE and last % 2 == 0:
            raise ValueError("Mężczyzna wymaga nieparzystej ostatniej cyfry serial.")

    first_ten = f"{yy:02d}{mm_code:02d}{dd:02d}{serial}"
    chk = _compute_checksum(first_ten)
    return first_ten + str(chk)


def generate_many(
    n: int,
    *,
    min_year: int = 1930,
    max_year: int = 2010,
    seed: Optional[int] = None,
) -> list[str]:
    """Wygeneruj listę unikalnych PESEL-i o losowych datach urodzeń.

    Używane do syntetycznych zbiorów benchmarkowych.
    """
    rng = random.Random(seed)
    out: set[str] = set()
    while len(out) < n:
        year = rng.randint(min_year, max_year)
        month = rng.randint(1, 12)
        # bezpieczny dzień
        max_day = 28
        day = rng.randint(1, max_day)
        gender = rng.choice([Gender.FEMALE, Gender.MALE])
        out.add(generate_pesel(date(year, month, day), gender, rng=rng))
    return list(out)


# ──────────────────────────────────────────────────────────────────────────────
# Pomocnicze
# ──────────────────────────────────────────────────────────────────────────────


def age_from_pesel(pesel: str, reference: Optional[date] = None) -> int:
    """Wiek (w latach pełnych) z PESEL-a względem `reference` (domyślnie dziś)."""
    parsed = parse_pesel(pesel)
    ref = reference or date.today()
    years = ref.year - parsed.birth_date.year
    if (ref.month, ref.day) < (parsed.birth_date.month, parsed.birth_date.day):
        years -= 1
    return years


if __name__ == "__main__":
    # Mała demonstracja.
    rng = random.Random(42)
    for _ in range(5):
        bd = date(rng.randint(1950, 2005), rng.randint(1, 12), rng.randint(1, 28))
        g = rng.choice([Gender.FEMALE, Gender.MALE])
        p = generate_pesel(bd, g, rng=rng)
        parsed = parse_pesel(p)
        print(f"{p}  ←  {bd}  {g.value}   (parsed: {parsed.birth_date} {parsed.gender.value})")
