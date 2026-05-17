# medical-he-stats — poufna agregacja statystyk medycznych (homomorphic encryption)

**Outsourcing obliczeń statystycznych na niezaufany serwer bez ujawniania wartości pomiarów.**  
Klient (szpital) szyfruje kolumny danych schematem **CKKS** (biblioteka **TenSEAL**), przesyła szyfrogramy przez **REST API** (**FastAPI**); serwer wykonuje obliczenia na zaszyfrowanych wektorach i zwraca wynik nadal zaszyfrowany — odszyfrowanie tylko po stronie posiadacza klucza prywatnego.

---

## W skrócie

| | |
|---|---|
| **Stos** | Python 3.11–3.12, TenSEAL (CKKS), FastAPI, NumPy / pandas, httpx, pytest |
| **Co robi system** | Statystyki na zaszyfrowanych seriach: suma, średnia, wariancja, histogram (zliczenia bucketów), korelacja Pearsona (komponenty HE → wartość końcowa po stronie klienta); mediana **przybliżona** przez histogram (świadomy kompromis kosztu HE — opisany w `docs/theory.md`). |
| **Jakość** | Testy automatyczne: zgodność HE vs „oracle” NumPy, scenariusze HTTP end-to-end (`tests/`). |
| **Wydajność** | Skrypty `src/bench/*` — czas szyfrowania / ewaluacji / plaintext, wykresy opcjonalnie w `src/bench/results/` (generowane lokalnie). |
| **Kod vs notebooki** | Logika jest w **`src/`** i **`tests/`**. Katalog **`notebooks/`** jest opcjonalny — patrz [`notebooks/README.md`](notebooks/README.md). |

---

## Spis treści

1. [Problem i podejście](#problem-i-podejście)
2. [Architektura](#architektura)
3. [Instalacja](#instalacja)
4. [Szybki start](#szybki-start)
5. [Struktura repozytorium](#struktura-repozytorium)
6. [Dokumentacja](#dokumentacja)

---

## Problem i podejście

Dane medyczne podlegają szczególnej ochronie (np. RODO art. 9). Klasyczne szyfrowanie symetryczne (AES) wymaga odszyfrowania przed obliczeniami — **serwer zobaczyłby plaintext**.

**Szyfrowanie homomorficzne (HE)** pozwala wykonywać wybrane operacje arytmetyczne **bezpośrednio na szyfrogramach**. W tym repozytorium używamy **CKKS** (przybliżone liczby rzeczywiste), co nadaje się do średniej, wariancji, sum kwadratów itd.

```text
plaintext:    [120, 135, 128, …]   ── mean ──►  127.6
ciphertext:   [c1,  c2,  c3,  …]   ── mean ──►  c_mean  ──► dec ──► 127.6
                                                            (tylko klient)
```

Formalnie: homomorfizm pozwala uzyskać złożone statystyki jako wyrażenia na zaszyfrowanych danych; szczegóły i ograniczenia (noise budget, mediana) → [`docs/theory.md`](docs/theory.md).

---

## Architektura

```text
┌──────────────────────────┐                       ┌──────────────────────────┐
│  Klient (zaufany)        │                       │  Serwer (niezaufany)     │
├──────────────────────────┤                       ├──────────────────────────┤
│  Dane, klucz prywatny    │  kontekst BEZ        │  Tylko klucze publiczne  │
│  szyfrowanie CKKS        │  secret_key          │  + eval (Galois, relin)  │
│  upload ciphertextów    │ ───────────────────► │  obliczenia na HE        │
│  odszyfrowanie wyników   │ ◄────────────────── │  brak dostępu do wartości│
└──────────────────────────┘                       └──────────────────────────┘
```

Szczegóły API i przepływu: [`docs/architecture.md`](docs/architecture.md).  
Co atakujący może i czego nie może wywnioskować: [`docs/threat_model.md`](docs/threat_model.md).

---

## Instalacja

**Python 3.11 lub 3.12**, menedżer **[uv](https://docs.astral.sh/uv/)** (lockfile `uv.lock`, `pyproject.toml`).

```powershell
cd C:\Users\Lenovo\projects\medical-he-stats

winget install --id astral-sh.uv
uv sync
```

Weryfikacja:

```powershell
uv run python -c "import tenseal as ts; print('TenSEAL', ts.__version__)"
```

**IDE:** interpreter z `.venv\Scripts\python.exe`. W repozytorium są ustawienia VS Code / Cursor (`.vscode/`).

### Dodatkowe komendy uv

```powershell
uv add pakiet
uv add --dev pakiet
uv remove pakiet
```

Uruchamianie modułów:

```powershell
uv run python -m src.client.doctor --help
uv run pytest -v
uv run uvicorn src.server.app:app --reload --port 8000
```

---

## Szybki start

### 1) Dane (`patients.csv`)

**Opcja A — eksport Synthea (CSV):**

```powershell
uv run python -m src.data.preprocess --synthea-dir data\synthea_raw --out data\processed\patients.csv
```

**Opcja B — syntetyczna kohorta (szybkie demo / duże N):**

```powershell
uv run python -m src.data.preprocess --fake 2000 --out data\processed\patients.csv
```

### 2) Serwer API

```powershell
uv run uvicorn src.server.app:app --reload --port 8000
```

### 3) Klient

```powershell
# HTTP (serwer z kroku 2)
uv run python -m src.client.doctor --csv data\processed\patients.csv --column systolic_bp --server http://127.0.0.1:8000

# Ten sam pipeline bez sieci (logika HE w procesie)
uv run python -m src.client.doctor --csv data\processed\patients.csv --column systolic_bp --local

# Dwie kolumny → korelacja Pearsona
uv run python -m src.client.doctor --csv data\processed\patients.csv --column systolic_bp --column2 diastolic_bp --stat correlation --local
```

### 4) Benchmarki (opcjonalnie)

```powershell
uv run python -m src.bench.bench_correctness
uv run python -m src.bench.bench_time --sizes 100 1000 10000
uv run python -m src.bench.plots
```

Wyniki domyślnie w `src/bench/results/` (katalog jest ignorowany przez git poza `.gitkeep`).

### 5) Notebooki (opcjonalnie)

Nie są wymagane do działania systemu — patrz [`notebooks/README.md`](notebooks/README.md).

```powershell
uv run jupyter lab
```

---

## Struktura repozytorium

```text
medical-he-stats/
├── README.md
├── pyproject.toml
├── uv.lock
├── data/                      # generowane lokalnie; .gitignore tam gdzie trzeba
├── src/
│   ├── data/                  # preprocess, PESEL, generator syntetyczny
│   ├── crypto/                # CKKS context, serializacja kolumn (chunking)
│   ├── plaintext/             # referencja NumPy (oracle)
│   ├── server/                # FastAPI + statystyki HE
│   ├── client/                # klient CLI
│   └── bench/                 # poprawność, czas, wykresy
├── notebooks/                 # opcjonalne narracyjne demo — README w środku
├── tests/
└── docs/                      # teoria, architektura, model zagrożeń
```

---

## Dokumentacja

| Plik | Zawartość |
|------|-----------|
| [`docs/theory.md`](docs/theory.md) | CKKS, parametry, batching, dlaczego mediana przez histogram |
| [`docs/architecture.md`](docs/architecture.md) | Endpointy, format przesyłki, kontekst bez `secret_key` |
| [`docs/threat_model.md`](docs/threat_model.md) | Zakres ochrony HE, side channels |

Sugerowana kolejność przy pierwszym czytaniu kodu: `plaintext/stats_plain.py` → `crypto/context.py` → `server/stats_he.py` → `server/app.py` → `client/doctor.py`.

---

## Dane i odpowiedzialność

W repozytorium **nie ma** realnych danych pacjentów. Obsługiwane są wyłącznie **zestawy syntetyczne** (własny generator lub pipeline Synthea). **PESEL** w CSV jest generowany algorytmicznie do celów demonstracyjnych — nie mapuje się na realne osoby.

Projekt traktuj jako **referencyjną implementację badawczo‑inżynierską** (proof of concept), nie jako gotowy produkt medyczny certyfikowany (brak m.in. pełnego hardeningu operacyjnego, HSM, SLA).
