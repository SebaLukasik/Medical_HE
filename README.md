# Poufna analiza danych medycznych w szyfrowaniu homomorficznym

> Projekt z kryptografii, temat 4. System, w którym szpital zleca zewnętrznemu
> serwerowi obliczenie wskaźników statystycznych (średnia, wariancja, odchylenie
> standardowe, mediana z histogramu) na danych pacjentów — **bez ujawniania
> wartości**. Wykorzystujemy schemat **CKKS** (TenSEAL) i porównujemy poprawność
> oraz czas obliczeń względem wersji jawnej (NumPy).

---

## Spis treści

1. [Co tu robimy i dlaczego](#co-tu-robimy-i-dlaczego)
2. [Architektura w jednym obrazku](#architektura)
3. [Instalacja](#instalacja)
4. [Szybki start (demo end-to-end)](#szybki-start)
5. [Struktura repo](#struktura-repo)
6. [Co dalej w nauce](#co-dalej-w-nauce)
7. [Podział pracy w grupie](#podział-pracy-w-grupie)

---

## Co tu robimy i dlaczego

**Problem.** Szpital ma dane pacjentów (ciśnienie, glukoza, BMI…) i chce, żeby
zewnętrzna firma policzyła statystyki populacyjne. Ale dane są wrażliwe (RODO,
art. 9) — nie można ich wysłać w postaci jawnej.

**Tradycyjne podejście — szyfrowanie AES.** Serwer musi odszyfrować, żeby
policzyć → traci się sens outsourcingu.

**Nasze podejście — szyfrowanie homomorficzne (HE).** Serwer liczy
**bezpośrednio na szyfrogramach**. Otrzymuje wynik zaszyfrowany, odsyła go do
szpitala. Tylko szpital (posiadacz klucza prywatnego) może go odszyfrować.

```text
plaintext:    [120, 135, 128, ...]   ── mean ──►   127.6
ciphertext:   [c1,  c2,  c3,  ...]   ── mean ──►   c_mean   ──► dec ──► 127.6
                                                              (na kliencie)
```

Czyli operacja arytmetyczna „przechodzi przez szyfrowanie":

$$
\text{Dec}\big(\text{Enc}(a) + \text{Enc}(b)\big) = a + b
\qquad
\text{Dec}\big(\text{Enc}(a) \cdot \text{Enc}(b)\big) = a \cdot b
$$

Szczegóły teoretyczne (BFV / BGV / **CKKS** / TFHE, noise budget, batching,
bootstrapping): zob. [`docs/theory.md`](docs/theory.md).

---

## Architektura

```text
┌──────────────────────────┐                       ┌──────────────────────────┐
│  SZPITAL / LEKARZ        │                       │  SERWER OBLICZENIOWY     │
│  (klient zaufany)        │                       │  (niezaufany)            │
├──────────────────────────┤                       ├──────────────────────────┤
│ 1. Wczytaj dane          │                       │                          │
│ 2. Wygeneruj klucze CKKS │  public + eval keys   │                          │
│ 3. Zaszyfruj kolumny     │ ────────────────────► │ przechowuje tylko klucze │
│                          │                       │ publiczne                │
│                          │  ciphertexty          │                          │
│                          │ ────────────────────► │ 4. Oblicz w HE:          │
│                          │                       │    sum, mean, var, std,  │
│                          │                       │    histogram, mediana    │
│                          │  zaszyfrowany wynik   │                          │
│                          │ ◄──────────────────── │                          │
│ 5. Odszyfruj             │                       │                          │
│ 6. Porównaj z plaintext  │                       │                          │
└──────────────────────────┘                       └──────────────────────────┘
```

Pełny opis: [`docs/architecture.md`](docs/architecture.md).
Model zagrożeń (co serwer wie/nie wie): [`docs/threat_model.md`](docs/threat_model.md).

---

## Instalacja

Wymagane: **Python 3.11 lub 3.12** (patrz `requires-python` w `pyproject.toml`;
TenSEAL ≥0.3.16 ma wheels dla obu).
Używamy [uv](https://docs.astral.sh/uv/) jako menedżera pakietów (szybsze niż pip,
jeden plik konfiguracji `pyproject.toml`, lockfile).

```powershell
# Przejdź do projektu
cd C:\Users\Lenovo\projects\medical-he-stats

# Jednorazowo: zainstaluj uv jeśli nie masz
winget install --id astral-sh.uv

# Stwórz .venv w folderze i zainstaluj wszystko z pyproject.toml
uv sync
```

To wystarczy. `uv sync` zrobi:
1. Wykryje, że potrzebny jest Python 3.11 (i pobierze go, jeśli trzeba).
2. Utworzy `.venv/` w folderze projektu.
3. Zainstaluje zależności z `pyproject.toml` + grupę `dev`.
4. Zapisze dokładne wersje w `uv.lock`.

### Jak dodać/usunąć bibliotekę

```powershell
uv add scikit-learn               # nowa zależność
uv add --dev mypy                  # tylko do developmentu
uv remove scipy                    # usuń
uv sync                            # po edycji pyproject.toml ręcznie
```

### Jak uruchamiać skrypty z venv

Dwie równoważne opcje:

```powershell
# Opcja A: bez aktywacji venv (uv samo wskazuje na .venv)
uv run python -m src.client.doctor --help
uv run pytest -v
uv run uvicorn src.server.app:app --reload

# Opcja B: aktywuj venv (klasycznie)
.\.venv\Scripts\Activate.ps1
python -m src.client.doctor --help
```

### Test instalacji

```powershell
uv run python -c "import tenseal as ts; print('TenSEAL OK', ts.__version__)"
```

### VS Code / Cursor

W VS Code (lub Cursorze) wybierz interpreter: `Ctrl+Shift+P` → „Python: Select
Interpreter" → wskaż `.venv\Scripts\python.exe`. Od tego momentu testy, debug i
notebooki działają natywnie. W `.vscode/settings.json` i `.vscode/launch.json`
dorzucamy gotową konfigurację, więc po otwarciu folderu nie musisz nic robić.

---

## Szybki start

### 1) Wygeneruj/przygotuj dane

Próbka Synthei jest mała (~100 pacjentów). Skrypt poniżej zapyta o ścieżkę i
zbuduje `data/processed/patients.csv` z dodanym PESEL-em:

```powershell
uv run python -m src.data.preprocess --synthea-dir data\synthea_raw --out data\processed\patients.csv
```

(Jeśli nie masz Synthei: użyj `--fake N` aby wygenerować N syntetycznych
pacjentów z naszego generatora — przyda się do benchmarków na 100 000 osobach,
których Synthea by długo robiła.)

### 2) Uruchom serwer

```powershell
uv run uvicorn src.server.app:app --reload --port 8000
```

### 3) Uruchom klienta (lekarza)

W drugim terminalu:

```powershell
# Serwer musi działać (patrz wyżej). Bez --server = tryb lokalny (bez HTTP).
uv run python -m src.client.doctor --csv data\processed\patients.csv --column systolic_bp --server http://localhost:8000

# Korelacja Pearsona (dwie kolumny, wiersze z NaN są odrzucane parami):
uv run python -m src.client.doctor --csv data\processed\patients.csv --column systolic_bp --column2 diastolic_bp --stat correlation --local
```

Otrzymasz:

```
== Średnia ciśnienia skurczowego ==
  HE:        127.634218
  plaintext: 127.634215
  błąd rel.: 2.3e-08
  czas HE:   312.4 ms   (szyfr: 41ms, eval: 256ms, dec: 15ms)
  czas plain: 0.18 ms
```

### 4) Benchmarki

```powershell
uv run python -m src.bench.bench_correctness
uv run python -m src.bench.bench_time --sizes 100 1000 10000 100000
uv run python -m src.bench.plots
```

Wykresy i CSV trafiają do `src/bench/results/` (folder jest w `.gitignore` poza `.gitkeep`).

### 5) Demo w Jupyter (opcjonalnie)

```powershell
uv run jupyter lab
# np. notebooks/01_intro_HE_CKKS.ipynb
```

---

## Struktura repo

```
medical-he-stats/
├── README.md                       ← jesteś tu
├── pyproject.toml                  ← zależności (uv / pip)
├── uv.lock
├── data/
│   ├── synthea_raw/                ← surowe CSV z Synthei
│   └── processed/                  ← patients.csv z PESEL
├── src/
│   ├── data/
│   │   ├── pesel.py                ← generator PESEL z cyfrą kontrolną
│   │   ├── preprocess.py           ← Synthea → patients.csv
│   │   └── synthetic.py            ← własny generator (gdy brak Synthei)
│   ├── crypto/
│   │   ├── context.py              ← parametry CKKS, kontekst
│   │   ├── keys.py                 ← zapis/odczyt kluczy
│   │   └── codec.py                ← serializacja ciphertextów
│   ├── plaintext/
│   │   └── stats_plain.py          ← NumPy: oracle do porównań
│   ├── server/
│   │   ├── app.py                  ← FastAPI
│   │   └── stats_he.py             ← obliczenia w HE
│   ├── client/
│   │   └── doctor.py               ← klient szpitala (e2e)
│   └── bench/
│       ├── bench_correctness.py
│       ├── bench_time.py
│       └── plots.py
├── notebooks/
│   ├── 01_intro_HE_CKKS.ipynb      ← tutorial CKKS (Hello HE)
│   ├── 02_stats_demo.ipynb         ← demo end-to-end na danych
│   └── 03_benchmarks.ipynb        ← benchmarki czasu / poprawności + wykresy
├── tests/
│   ├── test_pesel.py
│   ├── test_stats_he.py
│   └── test_e2e.py
└── docs/
    ├── theory.md                   ← teoria HE/CKKS
    ├── architecture.md             ← architektura
    └── threat_model.md             ← model zagrożeń
```

---

## Co dalej w nauce

Kolejność, w której grupa powinna to czytać/robić:

1. [`docs/theory.md`](docs/theory.md) — przeczytajcie pierwszy raz przed
   jakimkolwiek kodem. Zwróćcie uwagę na sekcje: „dlaczego CKKS", „noise
   budget", „batching".
2. `notebooks/01_intro_HE_CKKS.ipynb` — odpalcie linijka po linijce, każdy z
   Was sam. To Wasz „Hello World" w HE.
3. `src/plaintext/stats_plain.py` — najprostszy plik. Zaczyna się od niego, żeby
   każda statystyka miała swój „oracle".
4. `src/crypto/context.py` + `src/server/stats_he.py` — serce projektu.
   Porównujcie linia w linię z odpowiednikiem plain — zobaczcie, ile rzeczy jest
   identycznych pojęciowo.
5. `notebooks/02_stats_demo.ipynb` — demo na `patients.csv`.
6. `notebooks/03_benchmarks.ipynb` — benchmarki i wykresy do slajdów.
7. `src/bench/*` — te same skrypty z linii poleceń.

---

## Podział pracy w grupie

W tym repo jest komentarzowy nagłówek `# OWNER:` przy plikach, które najlepiej
przypisać konkretnym osobom. Sugerowany podział (3 osoby):

- **Osoba 1 — „Dane & PESEL"**: `src/data/*`, część raportu o danych
  medycznych, generator PESEL, część testów.
- **Osoba 2 — „Krypto & klient"**: `src/crypto/*`, `src/client/doctor.py`,
  notebook 01 (intro do HE), część raportu o teorii HE.
- **Osoba 3 — „Serwer & benchmark"**: `src/server/*`, `src/bench/*`, notebook
  03, część raportu o wynikach i modelu zagrożeń.

Wspólnie: notebook 02 (demo), prezentacja, raport końcowy.

---

## Licencja i kontekst

Projekt edukacyjny (zaliczeniowy). Dane Synthei są w 100% syntetyczne. Nasz
generator PESEL nie używa danych żadnej żyjącej osoby — sprawdzane testami
poprawności algorytmu, **nie** unikalności w rejestrze państwowym.
