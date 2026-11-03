"""Nonrecursive supported-image discovery."""

from pathlib import Path

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg"}


def discover_images(folder: Path) -> list[tuple[Path, float]]:
    """Return sorted supported files and their sizes in MiB; propagate access errors."""
    return [
        (path, path.stat().st_size / (1024 * 1024))
        for path in sorted(folder.iterdir(), key=lambda path: (path.name.casefold(), path.name))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
