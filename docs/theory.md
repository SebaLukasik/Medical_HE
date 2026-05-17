# Teoria szyfrowania homomorficznego — wersja dla naszej grupy

> Cel: każdy z trójki ma po przeczytaniu tego dokumentu rozumieć **dlaczego**
> używamy CKKS, **co to** jest „noise budget" i **dlaczego** mediana jest droga.
> Format: minimum matematyki konieczne do projektu, plus intuicja.

---

## 1. Homomorfizm — intuicja

Funkcja $\varphi: A \to B$ jest **homomorfizmem** struktur algebraicznych, jeśli
zachowuje operacje:

$$
\varphi(a + b) = \varphi(a) + \varphi(b), \qquad \varphi(a \cdot b) = \varphi(a) \cdot \varphi(b)
$$

(operacje po lewej i po prawej mogą być różne — ważne, że „komutują" z $\varphi$).

Szyfrowanie $\text{Enc}_k$ jest **homomorficzne**, jeżeli istnieją operacje
$\oplus$ i $\otimes$ na zbiorze szyfrogramów, takie że:

$$
\text{Dec}_k(\text{Enc}_k(a) \oplus \text{Enc}_k(b)) = a + b
$$

$$
\text{Dec}_k(\text{Enc}_k(a) \otimes \text{Enc}_k(b)) = a \cdot b
$$

Mając obie operacje, możemy policzyć **dowolny wielomian** na zaszyfrowanych
wejściach. A statystyki to wielomiany:

| Statystyka                       | Wielomian na danych              |
|----------------------------------|----------------------------------|
| Suma                             | $\sum_i x_i$                     |
| Średnia                          | $\frac{1}{N} \sum_i x_i$         |
| Wariancja (forma rozwinięta)     | $\frac{1}{N}\sum_i x_i^2 - \bar{x}^2$ |
| Korelacja Pearsona (licznik)     | $\sum_i (x_i \bar{y} + y_i \bar{x}) - N \bar{x}\bar{y}$ |

---

## 2. Krótka historia (5 minut, do prezentacji)

| Rok  | Co  | Dlaczego ważne |
|------|-----|----------------|
| 1978 | RSA jest „częściowo homomorficzny" (mnożenie) | Pierwszy znany schemat z homomorfizmem |
| 1985 | ElGamal — mnożenie | Lepsza losowość |
| 1999 | Paillier — dodawanie | Używany do dziś w głosowaniach elektronicznych |
| **2009** | **Gentry** — pierwszy schemat **FHE** (lattice + bootstrapping) | Otworzyło dziedzinę |
| 2011 | BGV (Brakerski-Gentry-Vaikuntanathan) | "Levelled" — bez bootstrappingu |
| 2012 | BFV (Brakerski/Fan-Vercauteren) | Liczby całkowite mod $t$ |
| **2017** | **CKKS** (Cheon-Kim-Kim-Song) | **Liczby rzeczywiste (przybliżone)** — to nasz wybór |
| 2016 | TFHE / FHEW | Operacje na bitach, szybkie porównania |

**Główne biblioteki:** Microsoft SEAL, HElib, OpenFHE (dawn. PALISADE), Lattigo
(Go), TFHE-rs (Zama, Rust). **TenSEAL** to wrapper Pythonowy na SEAL.

---

## 3. Klasyfikacja schematów

```text
         poufność
           ▲
   FHE ────┤ Gentry'09, CKKS, BFV, BGV, TFHE
   SHE ────┤ HE z ograniczoną głębokością mnożeń
   PHE ────┤ RSA (×), ElGamal (×), Paillier (+)
   AES ────┤ żadnej operacji na zaszyfrowanych
           └──────────────────────────────────►  użyteczność
```

- **PHE (Partially HE)** — tylko jedna operacja.
- **SHE / Levelled HE** — obie operacje, ograniczona głębokość mnożeń.
- **FHE (Fully HE)** — dowolna głębokość; możliwe dzięki **bootstrappingowi**
  (operacja „odświeżająca" szyfrogram).

W projekcie nie potrzebujemy bootstrappingu. **Wystarczy levelled HE** dla
naszych statystyk (głębokość mnożeń ≤ 3 dla wariancji, ≤ 5 dla std z aproksymacją sqrt).

---

## 4. CKKS w pigułce

CKKS = **C**heon-**K**im-**K**im-**S**ong, 2017. Operuje na **wektorach liczb
zespolonych** w pierścieniu kwocientowym:

$$
R_q = \mathbb{Z}_q[X] / (X^N + 1)
$$

gdzie $N$ jest potęgą dwójki (zwykle $2^{13}$ lub $2^{14}$), a $q$ jest dużą
liczbą — produktem małych pierwszych.

### Co musimy wiedzieć praktycznie:

1. **Plaintext jest wektorem!** Pojedynczy szyfrogram nie szyfruje jednej
   wartości, tylko **wektor długości $N/2$** liczb rzeczywistych. To nazywa się
   **batching** lub **packing**. Operacja na ciphertekście to operacja
   **element-wise** na wektorze (SIMD).

   Przykład: zamiast szyfrować 8000 wartości BMI osobno, pakujemy je w jeden
   wektor i szyfrujemy raz. Suma 8000 wartości to ~kilkanaście rotacji + suma.

2. **Liczby są przybliżone.** CKKS koduje liczby przez przeskalowanie razy
   `scale` (zwykle $2^{40}$) i zaokrąglenie do liczb całkowitych. Po
   odszyfrowaniu dostaniecie wartość z błędem $\approx 10^{-6}$ (zależnie od
   `scale`). Dlatego CKKS to *Approximate Number Theoretic Transform*.

3. **„Noise budget" / poziomy.** Każde mnożenie powiększa szum w
   szyfrogramie i obniża „poziom" (`level`). Mając kontekst z N poziomami,
   możecie wykonać N mnożeń sekwencyjnie. Po wyczerpaniu — szyfrogram jest
   bezużyteczny (bez bootstrappingu).

4. **Klucze, których będziemy używać:**
   - `secret_key` — TYLKO klient. Nigdy nie opuszcza szpitala.
   - `public_key` — do szyfrowania. Wysyłany do serwera (i każdego, kto chce
     wnieść dane).
   - `relinearization_key` — po mnożeniu szyfrogram „rośnie" (ma 3 komponenty
     zamiast 2). Relinearyzacja sprowadza go z powrotem do 2. Serwer
     potrzebuje tego klucza.
   - `galois_keys` — do operacji rotacji wektora wewnątrz szyfrogramu
     (potrzebne np. do sumy elementów wektora). Serwer też ich potrzebuje.

   **Wszystkie klucze poza `secret_key` to klucze publiczne ewaluacji** — nie
   da się z nich odzyskać `secret_key`, ale pozwalają na operacje.

---

## 5. Parametry CKKS, które wybieramy

W TenSEAL kontekst tworzymy tak:

```python
import tenseal as ts

ctx = ts.context(
    scheme=ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2**40
ctx.generate_galois_keys()
ctx.generate_relin_keys()
```

| Parametr | Co znaczy | Nasz wybór |
|---------|-----------|-----------|
| `poly_modulus_degree` ($N$) | rozmiar pierścienia | **8192** — bezpieczeństwo 128-bit, slot count = 4096 |
| `coeff_mod_bit_sizes` | bity modułów na każdy „poziom" | `[60, 40, 40, 60]` → **2 poziomy mnożeń** |
| `global_scale` | precyzja kodowania | $2^{40}$ — błąd ≈ $2^{-40} \approx 10^{-12}$ |
| `generate_galois_keys` | klucze do rotacji | tak (potrzebne do `vec.sum()`) |
| `generate_relin_keys` | klucze relinearyzacji | tak (potrzebne po każdym `*`) |

**Dlaczego `[60, 40, 40, 60]`?** Pierwszy i ostatni element to „specjalne
moduły" (większe), środkowe to budżet mnożeń. Tu mamy 2 środkowe, czyli 2
mnożenia w głąb. Dla wariancji wystarczy (`x^2` to 1 mnożenie). Dla std z
aproksymacją sqrt rzędu 2 trzeba 3 — dodajemy `[60, 40, 40, 40, 60]`.

**Bezpieczeństwo.** Dla $N = 8192$ i powyższej polityki modułów: ≥ 128-bit
zgodnie z [Homomorphic Encryption Standard](https://homomorphicencryption.org).

---

## 6. Co da się policzyć i jak

### 6.1 Suma wektora (potrzebne do średniej)

CKKS pakuje wektor $[x_1, x_2, ..., x_n, 0, 0, ..., 0]$ w jeden szyfrogram.
Aby zsumować elementy, używamy trick z rotacjami:

```text
v        = [x1, x2, x3, x4, 0, 0, 0, 0]
v + rot1 = [x1+x2, x2+x3, x3+x4, x4, ...]   (rotacja o 1)
+ rot2   = [x1+x2+x3+x4, ..., ...]          (rotacja o 2)
...
```

Po $\log_2 n$ rotacjach pierwszy slot zawiera sumę wszystkich elementów.
W TenSEAL: `enc.sum()`.

### 6.2 Średnia

$$\bar{x} = \frac{1}{N} \sum x_i$$

`N` jest publiczne → `enc.sum() * (1/N)` (mnożenie szyfrogramu przez plaintext).

### 6.3 Wariancja

$$\sigma^2 = \frac{1}{N} \sum (x_i - \bar{x})^2 = \frac{1}{N}\sum x_i^2 - \bar{x}^2$$

W HE forma rozwinięta jest tańsza (jedno globalne mnożenie):

```text
enc_x2 = enc * enc            # element-wise x_i^2
sum_x2 = enc_x2.sum()
mean_x2 = sum_x2 * (1/N)
var = mean_x2 - mean^2        # mean^2 też wymaga mnożenia
```

Głębokość: 1 mnożenie (między ciphertextami) → wymaga 1 poziomu.

### 6.4 Odchylenie standardowe — pierwiastek

**Tutaj wchodzi pierwsze ograniczenie HE.** `sqrt` nie jest wielomianem!
Trzeba ją **aproksymować wielomianem**. Dwie opcje:

**A) Iteracja Newtona–Raphsona:**
$$y_{k+1} = 0.5 \cdot y_k \cdot (3 - x \cdot y_k^2)$$
gdzie $y_k \to 1/\sqrt{x}$. Po 3–4 iteracjach jest dokładnie. **Każda iteracja
to 2 mnożenia → potrzebujemy poziomów.**

**B) Aproksymacja wielomianowa (Chebyshev) w określonym zakresie** $[a, b]$:
$$\sqrt{x} \approx c_0 + c_1 x + c_2 x^2 + ...$$
Tania, ale wymaga znajomości zakresu wariancji a priori.

**Realistyczna opcja w projekcie:** zwracamy szyfrowaną wariancję, a klient po
odszyfrowaniu liczy `sqrt` w plaintekście. Jest to **w pełni dopuszczalne** w
modelu zagrożeń (klient i tak widzi wariancję — informacja agregatowa).
Komentujemy to w raporcie.

### 6.5 Mediana — i dlaczego boli

Mediana wymaga **sortowania**. Sortowanie wymaga **porównań**. Porównanie
$x < y$ w HE wymaga aproksymacji funkcji znaku albo sigmoidy:

$$\text{sign}(x) \approx \tanh(k \cdot x) \approx P_d(x)$$

Wielomian $P_d$ stopnia $d \geq 7$, plus sieci sortujące (Batcher, Ajtai-Komlós-Szemerédi)
o złożoności $\Theta(N \log^2 N)$ porównań. Dla $N = 1000$ pacjentów to dziesiątki
tysięcy mnożeń → potrzebujemy bootstrappingu albo godzin czasu.

**Nasze rozwiązanie: mediana z histogramu.**

1. Klient ustala **publiczne brzegi przedziałów** $[b_0, b_1, ..., b_K]$ (np.
   100–250 mmHg co 5 mmHg → 30 koszyków dla ciśnienia skurczowego).
2. Dla każdego pacjenta $i$ klient liczy **w plaintekście** wektor one-hot
   $h_i \in \{0,1\}^K$: $h_i[k] = 1$ wtw. $v_i \in [b_k, b_{k+1})$.
3. Klient szyfruje $h_i$ (jako wektor) i wysyła do serwera.
4. Serwer sumuje po pacjentach: $H = \sum_i h_i$ → szyfrogram **histogramu**
   (każdy slot = liczba pacjentów w danym koszyku).
5. Klient odszyfrowuje $H$, wybiera koszyk, w którym leży $N/2$-ty pacjent →
   **mediana = środek koszyka** (lub interpolacja liniowa).

**Co serwer wie?** Tylko że to wektor one-hot długości $K$. Nie zna konkretnych
wartości pacjentów ani nawet ich uporządkowania. Nie zna histogramu (jest
zaszyfrowany aż do klienta).

**Czy to „prawdziwa HE mediana"?** Nie — to mediana z histogramu, formalnie
przybliżenie. Ale uczciwie pokazuje **typowy realny pattern w HE**: drogie
operacje (porównania) wykonujemy po stronie posiadacza danych w plaintekście,
a tanie (sumy) na serwerze w HE. Tak działają realne systemy klinicznych
agregacji (np. [MedCo](https://medco.epfl.ch)).

W raporcie omówcie alternatywę (pełna sieć sortująca w HE) i dlaczego ją
odrzuciliście — to ważny element edukacyjny.

---

## 7. Bezpieczeństwo i model zagrożeń (krótko)

Pełne omówienie: [`threat_model.md`](threat_model.md).

- **Atakujący**: serwer „honest-but-curious" (wykonuje protokół poprawnie, ale
  podsłuchuje wszystko, co dostaje).
- **Bezpieczeństwo CKKS**: oparte na trudności problemu **RLWE** (Ring Learning
  With Errors). Parametry $N = 8192$, $\log_2 q \leq 218$ → **≥ 128-bit
  bezpieczeństwa** (standard HES 2018).
- **PESEL**: nigdy nie wychodzi w plaintekście. Opcjonalnie szyfrujemy go
  (numerycznie zakodowany) razem z danymi medycznymi, ale nie liczymy na nim
  żadnych statystyk.
- **Co wycieka mimo HE**: rozmiar danych (liczba pacjentów), schemat (jakie
  kolumny), wzorzec dostępu, czas obliczenia. To tzw. **side channels**.

---

## 8. Co umieć po przeczytaniu (samosprawdzenie)

Po lekturze powinniście umieć odpowiedzieć:

1. Dlaczego AES nie wystarczy w naszym scenariuszu?
2. Czym różni się CKKS od BFV i kiedy używamy którego?
3. Co to jest „slot" w CKKS i ile ich jest dla $N = 8192$?
4. Po co serwerowi `relinearization_key` i `galois_keys`, ale nie
   `secret_key`?
5. Dlaczego wariancję w HE liczymy formułą rozwiniętą $E[X^2] - E[X]^2$, a nie
   bezpośrednio $\frac{1}{N}\sum (x_i - \bar{x})^2$?
6. Dlaczego mediana jest trudna i jak ją obchodzimy?
7. Czego nie chroni HE (lista 3 side channels)?

Jeśli tak — możemy siadać do kodu.

---

## 9. Dalsza lektura (po projekcie)

- Cheon, Kim, Kim, Song — *Homomorphic Encryption for Arithmetic of
  Approximate Numbers* (CKKS, 2017).
- Gentry's PhD thesis (2009) — historyczny pierwszy FHE.
- Microsoft SEAL manual — dla parametrów i intuicji.
- [Awesome HE](https://github.com/jonaschn/awesome-he) — lista zasobów.
