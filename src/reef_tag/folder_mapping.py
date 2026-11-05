"""Discover unavailable image folders and validate explicit replacement locations."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from reef_tag.models import ImagePathChange
from reef_tag.repositories import Repository


@dataclass(frozen=True)
class FolderCandidate:
    """One missing directory and the exact stored image records that refer to it."""

    directory: Path
    images: dict[int, str]


@dataclass(frozen=True)
class FolderCheck:
    """Missing folders and diagnostics for paths that could not be checked safely."""

    candidates: tuple[FolderCandidate, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True)
class ReplacementFolder:
    """A validated destination with filename match counts and proposed path changes."""

    directory: Path
    matched: int
    total: int
    changes: tuple[ImagePathChange, ...]


def discover_missing_folders(repository: Repository) -> FolderCheck:
    """Check each distinct stored parent directory without scanning image files.

    :param repository: Source of IMAGE paths; no preferences or unrelated folders are used.
    :return: Alphabetically ordered missing folders and non-fatal access/path issues.
    :raises sqlite3.Error: If image paths cannot be read.
    """
    folders: dict[Path, dict[int, str]] = {}
    issues: list[str] = []
    for image_id, name in repository.image_paths().items():
        if not isinstance(name, str) or not name.strip() or "\0" in name:
            issues.append(f"Image {image_id} has an empty or invalid image path.")
            continue
        path = Path(name)
        if (
            not path.is_absolute()
            or not path.name
            or name.endswith(os.sep)
            or ".." in path.parts
            or path.name in {".", ".."}
        ):
            issues.append(f"Image {image_id} has no valid full image path: {name}")
            continue
        folders.setdefault(path.parent, {})[image_id] = name

    candidates: list[FolderCandidate] = []
    for directory, images in sorted(folders.items()):
        try:
            # Path.is_dir() suppresses access errors in Python 3.14; stat keeps them distinct.
            exists = stat.S_ISDIR(directory.stat().st_mode)
        except FileNotFoundError, NotADirectoryError:
            exists = False
        except OSError as error:
            issues.append(f"Cannot check folder {directory}: {error}")
            continue
        if not exists:
            candidates.append(FolderCandidate(directory, images))
    return FolderCheck(tuple(candidates), tuple(issues))


def validate_replacement(candidate: FolderCandidate, selection: str) -> ReplacementFolder:
    """Check a replacement directory and its directly contained expected filenames.

    :param candidate: Missing folder and image records to be mapped.
    :param selection: Replacement entered or browsed by the user.
    :return: Resolved directory, match counts and proposed changes, without any writes.
    :raises ValueError: If selection is empty, invalid or contains no expected files.
    :raises OSError: If the directory or an expected file cannot be accessed.
    """
    if not selection.strip() or "\0" in selection:
        raise ValueError("Select an existing replacement folder.")
    directory = Path(selection).expanduser().resolve(strict=True)
    if not stat.S_ISDIR(directory.stat().st_mode):
        raise ValueError(f"The selected path is not a folder: {directory}")
    # Opening the directory checks listing access without searching its contents.
    with os.scandir(directory):
        pass
    changes: list[ImagePathChange] = []
    matched = 0
    for image_id, original in candidate.images.items():
        replacement = directory / Path(original).name
        try:
            present = stat.S_ISREG(replacement.stat().st_mode)
        except FileNotFoundError, NotADirectoryError:
            present = False
        if present:
            matched += 1
        changes.append(ImagePathChange(image_id, original, str(replacement)))
    if not matched:
        raise ValueError(f"No expected images were found in the selected folder:\n{directory}")
    return ReplacementFolder(directory, matched, len(candidate.images), tuple(changes))
