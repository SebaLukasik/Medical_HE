# Architektura systemu

## Aktorzy

| Aktor | Zaufanie | Co posiada |
|-------|----------|-----------|
| **Szpital / Lekarz** (klient) | Zaufany | Surowe dane pacjentów, `secret_key` |
| **Serwer obliczeniowy** | Niezaufany ("honest-but-curious") | Ciphertexty + klucze publiczne ewaluacji |
| **Trzecia strona** (np. audytor) | Poza zakresem | — |

## Sekwencja interakcji

```text
Lekarz                                     Serwer
  │                                          │
  │ 1. wczytaj CSV z patients.csv            │
  │    (PESEL, BMI, ciśnienie, glukoza…)     │
  │                                          │
  │ 2. utwórz kontekst CKKS                  │
  │    poly_modulus_degree=8192              │
  │    coeff_mod=[60,40,40,60]               │
  │    scale=2**40                           │
  │                                          │
  │ 3. wygeneruj klucze:                     │
  │    secret_key, public_key,               │
  │    relin_key, galois_keys                │
  │                                          │
  │ 4. zaszyfruj kolumnę X jako wektor       │
  │    ct_X = enc(X)                         │
  │                                          │
  │ 5. POST /context  ───────────────────►   │
  │    (public + relin + galois, BEZ secret) │
  │                                          │
  │ 6. POST /upload   ───────────────────►   │
  │    body: ct_X (bytes)                    │
  │                            ◄─────────    │
  │                       token data_id      │
  │                                          │
  │ 7. POST /compute/mean?id=data_id  ───►   │
  │                                          │  ◄ stats_he.mean(ct_X, N)
  │                            ◄─────────    │
  │                          ct_mean         │
  │                                          │
  │ 8. dec(ct_mean) → ~127.6                 │
  │                                          │
  │ 9. porównaj z plaintext (oracle)         │
  │ 10. pomiar czasu                         │
```

## Diagram modułów

```text
                   ┌─────────────────────────────────────┐
                   │            src/client/              │
                   │            doctor.py                │
                   │   (orkiestracja end-to-end)         │
                   └──────────┬──────────────┬───────────┘
                              │              │
                  ┌───────────▼──┐      ┌────▼─────────┐
                  │ src/crypto/  │      │ src/data/    │
                  │  context.py  │      │  pesel.py    │
                  │  keys.py     │      │  preprocess  │
                  │  codec.py    │      │  synthetic   │
                  └──────────────┘      └──────────────┘
                              ▲              ▲
                              │              │
                              │   HTTP       │
                              │              │
                   ┌──────────┴──────────────┴───────────┐
                   │            src/server/              │
                   │              app.py                 │
                   │   (FastAPI: /context /upload        │
                   │     /compute/{stat})                │
                   └─────────────────┬───────────────────┘
                                     │
                              ┌──────▼──────┐
                              │ stats_he.py │
                              │ mean, var,  │
                              │ std-approx, │
                              │ histogram,  │
                              │ corr…       │
                              └─────────────┘
```

## Format protokołu

### `POST /context`

```
multipart/form-data
  file: <bytes>           # ts.Context.serialize() bez secret_key
→ 200 OK { "context_id": "<uuid>" }
```

### `POST /upload`

```
multipart/form-data
  context_id: "<uuid>"
  column:     "systolic_bp"
  file:       <bytes>     # ts.CKKSVector.serialize()
  n_samples:  1000        # publiczne!
→ 200 OK { "data_id": "<uuid>", "column": "...", "n_samples": 1000 }
```

### `POST /compute/{stat}`

Gdzie `stat` ∈ `mean` \| `sum` \| `variance` — JSON:

```json
{ "data_id": "<uuid>", "context_id": "<uuid>" }
```

→ `result_b64` (jeden ciphertext ze skalarem w slocie 0) + `eval_time_ms`.

### `POST /compute/correlation`

Dwie wcześniej wgrane kolumny (ten sam N, ta sama liczba chunków):

```json
{ "data_id_x": "<uuid>", "data_id_y": "<uuid>", "context_id": "<uuid>" }
```

→ JSON: `sum_x_b64`, `sum_y_b64`, `sum_x2_b64`, `sum_y2_b64`, `sum_xy_b64`, `n_samples`, `eval_time_ms`.  
Klient odszyfrowuje składowe i liczy współczynnik Pearsona w plaintekście.

### `POST /compute/histogram`

```json
{ "bucket_data_ids": ["<uuid>", ...], "context_id": "<uuid>" }
```

→ lista `result_chunks_b64` (jeden ciphertext na bucket).

## Punkty wydajności

1. **Batching.** Dla $N = 8192$ mamy 4096 slotów na ciphertekst. Suma wektora
   w jednym ciphertekście to $O(\log n)$ rotacji (≈ 12 rotacji dla 4096
   slotów).
2. **Wielowątkowość TenSEAL.** SEAL może używać wielu wątków; sprawdzimy w
   benchmarku.
3. **Serializacja.** Ciphertext dla $N=8192$ to ~256 KB. Dla 100k pacjentów →
   ~25 takich szyfrogramów (przy 4096 slotów/szyfrogram = 24 szyfrogramy).
   Razem ~6 MB. Akceptowalne dla HTTP.

## Lokalizacja kluczy

```text
src/client/  ────  trzyma secret_key   (NIGDY nie wysyła)
                   trzyma context full

src/server/  ────  dostaje context BEZ secret_key
                   (zawiera public, relin, galois — wystarczy do operacji)
```

W TenSEAL serializujemy kontekst dwa razy:

```python
ctx_for_server = ctx.serialize(save_secret_key=False)  # dla serwera
ctx_local      = ctx.serialize(save_secret_key=True)   # dla siebie
```
