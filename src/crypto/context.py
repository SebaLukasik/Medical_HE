"""Fabryka kontekstów CKKS dla naszego systemu.

Centralne miejsce, w którym ustalamy parametry HE. Wszystkie inne moduły
proszą o kontekst stąd — dzięki temu klient i serwer używają identycznych
parametrów (klucze są zgodne).

Parametry wybrane do projektu:

- ``poly_modulus_degree = 8192``: bezpieczeństwo ≥ 128 bitów (HES 2018),
  4096 slotów na ciphertext.
- ``coeff_mod_bit_sizes = [60, 40, 40, 60]``: 2 poziomy mnożeń → wystarcza
  dla wariancji (1 mnożenie ``x*x`` + 1 mnożenie ``mean*mean``).
- ``global_scale = 2**40``: precyzja kodowania ~$10^{-12}$.

Jeśli zechcecie liczyć std-dev ze sqrt w HE (aproksymacja Newtonem 2 iter.),
zmieńcie na ``[60, 40, 40, 40, 40, 60]`` (4 poziomy mnożeń).

OWNER: Osoba 2 ("Krypto & klient").
"""

from __future__ import annotations

from dataclasses import dataclass

import tenseal as ts


@dataclass(frozen=True)
class CKKSParams:
    """Zestaw parametrów CKKS używanych w projekcie.

    Trzymamy je jako dataclass, żeby:
    - można było łatwo wygenerować różne konteksty do benchmarków,
    - można było zaserializować je do JSON-a (metadane wysyłki do serwera).
    """

    poly_modulus_degree: int = 8192
    coeff_mod_bit_sizes: tuple[int, ...] = (60, 40, 40, 60)
    scale_bits: int = 40

    @property
    def slot_count(self) -> int:
        """Liczba slotów per ciphertext (= N/2 dla CKKS)."""
        return self.poly_modulus_degree // 2

    @property
    def scale(self) -> float:
        return float(2**self.scale_bits)

    def mult_depth(self) -> int:
        """Ile mnożeń sekwencyjnych pozwala wykonać ten kontekst.

        Z grubsza: liczba środkowych modułów w ``coeff_mod_bit_sizes``.
        Pierwszy i ostatni to "specjalne moduły".
        """
        return max(0, len(self.coeff_mod_bit_sizes) - 2)


# Domyślny zestaw używany w całym projekcie.
DEFAULT_PARAMS = CKKSParams()


def make_context(
    params: CKKSParams = DEFAULT_PARAMS,
    *,
    generate_galois: bool = True,
    generate_relin: bool = True,
) -> ts.Context:
    """Stwórz kontekst CKKS z (sekretnym) kluczem prywatnym.

    Ten kontekst trafia do klienta. Do serwera wysyłamy jego okrojoną
    serializację bez ``secret_key`` (zob. :func:`serialize_for_server`).
    """
    ctx = ts.context(
        scheme=ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=params.poly_modulus_degree,
        coeff_mod_bit_sizes=list(params.coeff_mod_bit_sizes),
    )
    ctx.global_scale = params.scale
    if generate_galois:
        ctx.generate_galois_keys()
    if generate_relin:
        # W TenSEAL 0.3.x klucze relinearyzacyjne dla CKKS są generowane
        # przy tworzeniu kontekstu, ale eksplicitne wywołanie jest no-op.
        try:
            ctx.generate_relin_keys()
        except Exception:
            pass
    return ctx


def serialize_for_server(ctx: ts.Context) -> bytes:
    """Serializuj kontekst do wysyłki na serwer (bez ``secret_key``).

    Zawiera:
    - public_key (do szyfrowania, gdyby serwer też miał coś szyfrować — u nas nie),
    - galois_keys (do rotacji = sumowania wektorów),
    - relin_keys (do redukcji ciphertextu po mnożeniu).

    NIE zawiera: secret_key.
    """
    return ctx.serialize(save_secret_key=False)


def serialize_for_client(ctx: ts.Context) -> bytes:
    """Serializuj pełen kontekst do przechowywania lokalnie (z ``secret_key``)."""
    return ctx.serialize(
        save_public_key=True,
        save_secret_key=True,
        save_galois_keys=True,
        save_relin_keys=True,
    )


def load_context(blob: bytes) -> ts.Context:
    """Wczytaj kontekst CKKS z bajtów (po :func:`serialize_for_*`)."""
    return ts.context_from(blob)
