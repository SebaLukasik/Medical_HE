"""Kodek: szyfrowanie/odszyfrowanie wektorów wartości z chunkingiem.

Jeden ciphertext CKKS przy ``poly_modulus_degree=8192`` pomieści 4096 liczb.
Mamy do czynienia z 1000–100 000 pacjentów, więc dla większych N musimy
**dzielić kolumnę na fragmenty** ("chunks"). Klient szyfruje listę chunków,
serwer wykonuje operację na każdym i agreguje wyniki.

Konwencje:
- ``EncryptedColumn`` to lista ciphertextów (chunks) + metadane (n_samples).
- Wszystkie statystyki operują na ``EncryptedColumn``.

OWNER: Osoba 2 ("Krypto & klient").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import tenseal as ts

from .context import CKKSParams, DEFAULT_PARAMS


@dataclass
class EncryptedColumn:
    """Zaszyfrowana kolumna danych (np. ciśnienia skurczowego dla N pacjentów).

    Atrybuty:
        chunks: lista ciphertextów; każdy zawiera do ``slot_count`` wartości.
        n_samples: liczba prawdziwych wartości (ostatni chunk może być padowany).
        slot_count: ile slotów per chunk (= N/2 z kontekstu).
        name: opcjonalna nazwa kolumny (do logów / API).
    """

    chunks: list[ts.CKKSVector]
    n_samples: int
    slot_count: int
    name: str | None = None

    def __len__(self) -> int:
        return self.n_samples

    def n_chunks(self) -> int:
        return len(self.chunks)

    def total_bytes(self) -> int:
        """Łączna wielkość serializacji wszystkich chunków (do raportów)."""
        return sum(len(c.serialize()) for c in self.chunks)


def encrypt_column(
    values: Sequence[float] | np.ndarray,
    context: ts.Context,
    params: CKKSParams = DEFAULT_PARAMS,
    *,
    name: str | None = None,
) -> EncryptedColumn:
    """Zaszyfruj kolumnę wartości jako sekwencję chunków.

    Padowanie: ostatni chunk, jeśli krótszy niż ``slot_count``, jest dopełniany
    zerami. **To jest bezpieczne dla SUMY** (zera nie wpływają), ale uwaga przy
    operacjach niemonotonicznych — w naszych statystykach (sum, mean, var,
    histogram) wszystkie są bezpieczne.
    """
    values_arr = np.asarray(values, dtype=np.float64).reshape(-1)
    n = int(values_arr.size)
    slot = params.slot_count

    chunks: list[ts.CKKSVector] = []
    for start in range(0, n, slot):
        chunk_vals = values_arr[start : start + slot]
        if chunk_vals.size < slot:
            padded = np.zeros(slot, dtype=np.float64)
            padded[: chunk_vals.size] = chunk_vals
            chunk_vals = padded
        chunks.append(ts.ckks_vector(context, chunk_vals.tolist()))

    return EncryptedColumn(chunks=chunks, n_samples=n, slot_count=slot, name=name)


def decrypt_column(enc: EncryptedColumn) -> np.ndarray:
    """Odszyfruj kolumnę (przyda się tylko do debugowania / testów).

    UWAGA: w produkcji klient zwykle deszyfruje **wyniki statystyk**, nie całe
    kolumny. Ale do testów poprawności (round-trip) ta funkcja jest złotem.
    """
    parts = []
    remaining = enc.n_samples
    for ct in enc.chunks:
        decoded = np.asarray(ct.decrypt(), dtype=np.float64)
        take = min(remaining, decoded.size)
        parts.append(decoded[:take])
        remaining -= take
    return np.concatenate(parts) if parts else np.zeros(0)


def decrypt_scalar(ct: ts.CKKSVector) -> float:
    """Wyciągnij pojedynczą liczbę z ciphertextu, w którym jest ona w slot 0.

    Wynik wielu naszych operacji (sum, mean, variance) trafia do pierwszego
    slotu wyniku — to pomocnik, żeby nie powtarzać ``.decrypt()[0]`` w kółko.
    """
    return float(ct.decrypt()[0])


def serialize_column(enc: EncryptedColumn) -> list[bytes]:
    """Zaserializuj listę chunków do wysyłki (np. multipart)."""
    return [c.serialize() for c in enc.chunks]


def deserialize_column(
    blobs: Iterable[bytes],
    context: ts.Context,
    n_samples: int,
    slot_count: int,
    *,
    name: str | None = None,
) -> EncryptedColumn:
    """Odtwórz ``EncryptedColumn`` z bajtów + kontekstu."""
    chunks = [ts.ckks_vector_from(context, b) for b in blobs]
    return EncryptedColumn(chunks=chunks, n_samples=n_samples, slot_count=slot_count, name=name)
