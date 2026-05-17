# Model zagrożeń

## Założenia

- **Atakujący**: serwer typu **honest-but-curious** (semi-uczciwy). Wykonuje
  protokół zgodnie z dokumentacją, ale podsłuchuje wszystko, co dostaje, i
  próbuje wyciągnąć z tego informacje o danych.
- **Bezpieczeństwo CKKS**: oparte na trudności problemu Ring Learning With
  Errors (RLWE). Parametry zgodne z Homomorphic Encryption Standard 2018:
  $N = 8192$, $\log_2 q \leq 218$ → **≥ 128 bitów bezpieczeństwa**.
- **Klient zaufany**: zakładamy, że szpital nie wycieka kluczy.

## Co chronimy

| Aktyw | Poziom poufności | Mechanizm |
|-------|-------------------|-----------|
| Wartości pomiarów (BMI, ciśnienie, glukoza…) | Wysoki (dane szczególne RODO art. 9) | **Szyfrowanie CKKS** |
| PESEL pacjenta | Bardzo wysoki | **Nigdy nie wychodzi z klienta** w plaintekście; opcjonalnie szyfrowany |
| Imię/nazwisko | Bardzo wysoki | Pseudonimizacja przed wysyłką |
| Wyniki statystyczne (mean, var…) | Średni — to jest **cel** obliczeń | Klient je widzi po deszyfracji |

## Co serwer **mimo HE** wie / może wnioskować

1. **Rozmiar danych**: liczba pacjentów $N$ (przekazana w `n_samples`).
2. **Schemat**: nazwy kolumn (`systolic_bp`, `bmi`, …). Można je zaobfuskować
   (np. `col_42`), ale w realnym wdrożeniu to często niepotrzebne.
3. **Wzorzec dostępu**: jakie statystyki zlecane, w jakiej kolejności, jak
   często.
4. **Czas obliczenia**: różne dane mogą dawać różne czasy (np. wartości
   skrajne mogą wpływać na propagację szumu — w praktyce nieistotne dla CKKS,
   ale teoretycznie kanał boczny).
5. **Brzegi histogramu**: gdy używamy mediany przez histogram, brzegi
   przedziałów są publiczne.

## Co serwer **nie wie**

- Konkretne wartości żadnego pacjenta.
- Wyniki obliczeń (są zwracane szyfrowane).
- Czy konkretny pacjent jest w danych (ale wie *ilu* jest).
- PESEL ani inne identyfikatory.

## Ataki, które rozważamy

### A1. Pasywne podsłuchiwanie ruchu

**Status**: nieistotne (TLS + HE).
**Mitigacja**: HTTPS przy realnym wdrożeniu; w demo używamy HTTP localhost.

### A2. Atak na klucze HE

**Status**: nieistotny przy poprawnych parametrach.
**Mitigacja**: parametry CKKS zgodne ze standardem HES.

### A3. Atak rekonstrukcyjny na statystyki

**Scenariusz**: serwer (lub odbiorca wyników) próbuje wnioskować o pojedynczych
pacjentach z wielokrotnych zapytań statystycznych ("differencing attack").
**Przykład**: lekarz pyta o średnie BMI dla $N$ pacjentów, potem dla $N-1$
(po wycofaniu Jana K.) → różnica daje BMI Jana K.

**Status**: realny, ale **poza zakresem ochrony HE**. HE chroni *poufność
obliczenia*, nie *poufność wyniku*. Mitigacja to **differential privacy** —
dodanie szumu do wyniku. To kolejny semestr.

W raporcie **wymieńcie** ten atak jako ograniczenie systemu.

### A4. Złośliwy serwer (active attacker)

**Scenariusz**: serwer modyfikuje wyniki (np. zwraca losowy szyfrogram zamiast
liczyć średnią) — klient dostanie błędną wartość, ale nie zauważy.

**Status**: poza zakresem (HE chroni poufność, nie integralność).
**Mitigacja**: **verifiable computation** (zk-SNARKs nad HE) — bardzo aktywne pole,
poza projektem. W demo zakładamy *honest-but-curious*.

### A5. Side channel: czasy operacji

**Status**: w CKKS minimalne (operacje są stałoczasowe na poziomie SEAL).
Wystarczające dla projektu.

### A6. Wyciek kluczy z klienta

**Status**: poza modelem (klient zaufany).
**Mitigacja realna**: HSM, szyfrowanie `secret_key` hasłem.

## Co jeszcze powinniście znać do prezentacji

- **MedCo** (EPFL/CHUV) — operacyjny system poufnej analizy klinicznej w
  Szwajcarii. Używa **lattigo** (Go) + multi-party HE. Lecz dla 2-3 osób w
  projekcie 7-tygodniowym single-party HE z TenSEAL to optymalny wybór.
- **Differential Privacy** komplementarne do HE — pierwsze chroni *obliczenie*,
  drugie chroni *wynik*.
- **Secure Multi-Party Computation (MPC)**: alternatywa dla HE; szybsze, ale
  wymaga wielu komunikujących się serwerów.

## Streszczenie modelu w jednym zdaniu

> Niezaufany serwer może obserwować wszystkie ciphertexty i zwrócone wyniki,
> zna metadane (rozmiar, schemat, kolejność zapytań), ale nie ma dostępu do
> wartości pomiarów ani PESEL-i — pod warunkiem, że poprawnie wykonuje
> protokół i nie próbuje aktywnego zafałszowania wyniku.
