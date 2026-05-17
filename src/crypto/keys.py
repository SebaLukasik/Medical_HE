"""Zapis/odczyt kontekstów (kluczy) HE na dysk.

W realnym wdrożeniu ``secret_key`` powinien lądować w HSM lub być szyfrowany
hasłem. Tutaj — do projektu studenckiego — zapisujemy raw bajty. **NIE wrzucać
``keys/`` do repo** (jest w ``.gitignore``).

OWNER: Osoba 2 ("Krypto & klient").
"""

from __future__ import annotations

from pathlib import Path

import tenseal as ts

from .context import load_context, serialize_for_client, serialize_for_server


def save_context(ctx: ts.Context, directory: str | Path) -> dict[str, Path]:
    """Zapisz kontekst do dwóch plików: pełny (klient) i bez sekretnego (serwer).

    Zwraca słownik ze ścieżkami do plików — przyda się do logów.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    client_path = directory / "context_client.tenseal"
    server_path = directory / "context_server.tenseal"
    client_path.write_bytes(serialize_for_client(ctx))
    server_path.write_bytes(serialize_for_server(ctx))
    return {"client": client_path, "server": server_path}


def load_client_context(directory: str | Path) -> ts.Context:
    """Wczytaj pełny kontekst klienta (z secret_key)."""
    blob = (Path(directory) / "context_client.tenseal").read_bytes()
    return load_context(blob)


def load_server_context(directory: str | Path) -> ts.Context:
    """Wczytaj kontekst serwera (bez secret_key)."""
    blob = (Path(directory) / "context_server.tenseal").read_bytes()
    return load_context(blob)
