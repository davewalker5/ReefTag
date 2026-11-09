"""Folder discovery, replacement validation and transactional path recovery."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from reef_tag.db import connect
from reef_tag.folder_mapping import discover_missing_folders, validate_replacement
from reef_tag.models import ImagePathChange
from reef_tag.repositories import Repository

DAY = date(2026, 10, 13)


@pytest.fixture
def repository(tmp_path: Path):
    """Provide a migrated database isolated from the user's observations."""
    connection = connect(tmp_path / "mapping.sqlite3")
    yield Repository(connection)
    connection.close()


def test_discovery_groups_and_sorts_only_missing_directories(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduplicate parents, ignore absent individual images and avoid directory scans."""
    present = tmp_path / "present"
    present.mkdir()
    for folder, filename in (("z", "one.png"), ("a", "one.png"), ("a", "two.png")):
        repository.create(tmp_path / folder / filename, DAY, 1, 2, "A", "Alpha")
    repository.create(present / "absent.png", DAY, 1, 2, "A", "Alpha")
    original_stat = Path.stat
    checked = []

    def directory_stat(path: Path, *args, **kwargs):
        """Reject per-image checks and count distinct directory lookups."""
        assert path.suffix != ".png"
        checked.append(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", directory_stat)
    result = discover_missing_folders(repository)
    assert [item.directory for item in result.candidates] == [tmp_path / "a", tmp_path / "z"]
    assert [len(item.images) for item in result.candidates] == [2, 1]
    assert len(checked) == 3
    assert result.issues == ()


def test_discovery_empty_database(repository: Repository) -> None:
    """An unused database has no recovery candidates or diagnostics."""
    result = discover_missing_folders(repository)
    assert result.candidates == result.issues == ()


@pytest.mark.parametrize("name", ["", "bad\0path", "/", "/a/../b.png", "/a/"])
def test_discovery_malformed_paths(repository: Repository, name: str) -> None:
    """Leave malformed and legacy filename-only records unchanged and report them."""
    repository.connection.execute(
        "INSERT INTO IMAGE (Name, Date, FolderId) VALUES (?, ?, ?)",
        (name, str(DAY), repository._folder_id(Path("/"), DAY)),
    )
    repository.connection.commit()
    result = discover_missing_folders(repository)
    assert result.candidates == ()
    assert len(result.issues) == 1
    assert list(repository.image_paths().values()) == ["/" + name]


def test_inaccessible_original_is_not_missing(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report access errors without proposing that an inaccessible directory has moved."""
    directory = tmp_path / "unavailable"
    repository.create(directory / "one.png", DAY, 1, 2, "A", "Alpha")
    original_stat = Path.stat

    def deny_folder(path: Path, *args, **kwargs):
        """Simulate a permissions failure independently of the test user's privileges."""
        if path == directory:
            raise PermissionError("Access denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deny_folder)
    result = discover_missing_folders(repository)
    assert result.candidates == ()
    assert len(result.issues) == 1
    assert str(directory) in result.issues[0]


def test_complete_mapping_preserves_metadata_and_exact_parent(
    repository: Repository, tmp_path: Path
) -> None:
    """Change paths only, retaining IDs, dates, flags, markers and prefix neighbours."""
    original = tmp_path / "dive01"
    neighbour = tmp_path / "dive010" / "one.png"
    destination = tmp_path / "archive"
    destination.mkdir()
    for name in ("one.png", "two.png"):
        repository.create(original / name, DAY, 10, 20, "A", "Alpha")
        (destination / name).touch()
    repository.create_pending(original / "two.png", DAY, 30, 40)
    repository.create(neighbour, DAY, 1, 2, "A", "Alpha")
    before_images = [
        tuple(row)
        for row in repository.connection.execute(
            "SELECT id, Date, FurtherExamination FROM IMAGE ORDER BY id"
        )
    ]
    before_identified = repository.identifications(original / "two.png")
    before_pending = repository.pending_identifications(original / "two.png")
    candidate = discover_missing_folders(repository).candidates[0]
    replacement = validate_replacement(candidate, str(destination))
    assert (replacement.matched, replacement.total) == (2, 2)
    assert all(
        str(original) in path for path in repository.image_paths().values() if "dive010" not in path
    )
    repository.update_image_paths(replacement.changes)
    assert [
        tuple(row)
        for row in repository.connection.execute(
            "SELECT id, Date, FurtherExamination FROM IMAGE ORDER BY id"
        )
    ] == before_images
    assert repository.identifications(destination / "two.png") == before_identified
    assert repository.pending_identifications(destination / "two.png") == before_pending
    assert str(neighbour) in repository.image_paths().values()
    assert repository.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_mapping_proposes_all_records(repository: Repository, tmp_path: Path) -> None:
    """Confirmation must relocate every path, including expected files still missing."""
    original, destination = tmp_path / "old", tmp_path / "new"
    destination.mkdir()
    for name in ("one.png", "two.png", "three.png"):
        repository.create(original / name, DAY, 1, 2, "A", "Alpha")
    (destination / "one.png").touch()
    (destination / "two.png").mkdir()  # A directory with the expected name is not an image.
    nested = destination / "nested"
    nested.mkdir()
    (nested / "three.png").touch()  # No recursive search.
    candidate = discover_missing_folders(repository).candidates[0]
    replacement = validate_replacement(candidate, str(destination))
    assert (replacement.matched, replacement.total) == (1, 3)
    assert len(replacement.changes) == 3
    repository.update_image_paths(replacement.changes)
    assert {Path(name).parent for name in repository.image_paths().values()} == {destination}


@pytest.mark.parametrize("kind", ["empty", "nul", "missing", "file", "no_match"])
def test_invalid_replacement_is_rejected(repository: Repository, tmp_path: Path, kind: str) -> None:
    """Invalid destinations never write paths, including folders without direct matches."""
    repository.create(tmp_path / "old" / "one.png", DAY, 1, 2, "A", "Alpha")
    candidate = discover_missing_folders(repository).candidates[0]
    target = tmp_path / "target"
    if kind == "file":
        target.touch()
    elif kind == "no_match":
        target.mkdir()
    selection = "" if kind == "empty" else "bad\0path" if kind == "nul" else str(target)
    before = repository.image_paths()
    with pytest.raises((ValueError, OSError)):
        validate_replacement(candidate, selection)
    assert repository.image_paths() == before


def test_inaccessible_replacement_is_rejected(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A readable parent entry alone is insufficient to accept an inaccessible folder."""
    import reef_tag.folder_mapping as mapping

    repository.create(tmp_path / "old" / "one.png", DAY, 1, 2, "A", "Alpha")
    candidate = discover_missing_folders(repository).candidates[0]
    destination = tmp_path / "new"
    destination.mkdir()

    def deny_listing(path):
        """Simulate an unreadable destination directory."""
        raise PermissionError("Cannot list directory")

    monkeypatch.setattr(mapping.os, "scandir", deny_listing)
    with pytest.raises(PermissionError):
        validate_replacement(candidate, str(destination))


@pytest.mark.parametrize("failure", ["conflict", "trigger", "stale"])
def test_mapping_failure_rolls_back_entire_directory(
    repository: Repository, tmp_path: Path, failure: str
) -> None:
    """Never leave the first path changed when the second update cannot complete."""
    old, new = tmp_path / "old", tmp_path / "new"
    for name in ("one.png", "two.png"):
        repository.create(old / name, DAY, 1, 2, "A", "Alpha")
    if failure == "conflict":
        repository.create(new / "two.png", DAY, 1, 2, "A", "Alpha")
    if failure == "trigger":
        repository.connection.execute("""
            CREATE TRIGGER reject_mapping BEFORE UPDATE OF Name ON IMAGE
            WHEN NEW.Name LIKE '%two.png'
            BEGIN SELECT RAISE(ABORT, 'simulated mapping failure'); END
        """)
        repository.connection.commit()
    before = repository.image_paths()
    changes = tuple(
        ImagePathChange(image_id, path, str(new / Path(path).name))
        for image_id, path in before.items()
        if Path(path).parent == old
    )
    if failure == "stale":
        change = changes[1]
        changes = (changes[0], ImagePathChange(change.image_id, "stale", change.replacement))
    with pytest.raises((sqlite3.Error, ValueError)):
        repository.update_image_paths(changes)
    assert repository.image_paths() == before
    assert not repository.connection.in_transaction
