# Notebooki (opcjonalne)

Materiał uzupełniający: przejście po CKKS, demo end-to-end na pliku CSV oraz
regeneracja wykresów benchmarków. **Implementacja i testy mieszczą się w `src/`**
— Jupyter nie jest wymagany do uruchomienia API ani klienta.

| Notebook | Zawartość |
|----------|-----------|
| `01_intro_HE_CKKS.ipynb` | Kontekst CKKS, ciphertext, średnia; parametry (m.in. noise budget, batching). |
| `02_stats_demo.ipynb` | Statystyki HE na `patients.csv` z porównaniem do plaintext. |
| `03_benchmarks.ipynb` | Odtwarzanie plików CSV i wykresów w `src/bench/results/`. |

Do uruchomienia całego systemu wystarczy główne `README.md` w korzeniu repozytorium
oraz `docs/architecture.md`. Notebooki są pomocne przy ręcznym, krokowym
przejściu po zachowaniu HE.

```powershell
# z katalogu głównego repozytorium (folder nadrzędny względem notebooks/)
uv run jupyter lab
```
