"""Explicit database configuration."""

import os
from pathlib import Path


def database_path() -> Path:
    """Return the configured absolute database file path, or raise ValueError."""
    value = os.environ.get("REEFTAG_DB_PATH", "").strip()
    if not value or not Path(value).is_absolute():
        raise ValueError(
            "Set REEFTAG_DB_PATH to an absolute SQLite file path before starting ReefTag."
        )
    path = Path(value)
    if not path.parent.is_dir() or path.is_dir():
        raise ValueError("REEFTAG_DB_PATH must name a file in an existing writable directory.")
    return path
