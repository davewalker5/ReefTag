"""Persistence acceptance and transaction regression tests."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from reef_tag.config import database_path
from reef_tag.db import connect
from reef_tag.repositories import Repository

DAY = date(2026, 10, 13)


@pytest.fixture
def repository(tmp_path: Path):
    """Provide a fresh database with enforced foreign keys."""
    connection = connect(tmp_path / "test.sqlite3")
    yield Repository(connection)
    connection.close()


def test_numbers_species_and_deletion(repository: Repository, tmp_path: Path) -> None:
    """Keep numbers stable and preserve shared records on deletion."""
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    for path in (first, first, second):
        repository.create(path, DAY, 10, 20, " Surgeonfish ", " Acanthurus leucosternon ")
    observations = repository.identifications(first)
    assert [a.number for a in observations] == [1, 2]
    assert repository.identifications(second)[0].number == 1
    assert len(repository.species()) == 1
    repository.delete(observations[0].id)
    repository.create(first, DAY, 30, 40, "Surgeonfish", "Acanthurus leucosternon")
    assert [a.number for a in repository.identifications(first)] == [2, 3]
    for observation in repository.identifications(first):
        repository.delete(observation.id)
    assert repository.image_date(first) == DAY
    assert len(repository.species()) == 1


def test_edit_is_local(repository: Repository, tmp_path: Path) -> None:
    """Changing one annotation's species leaves other annotations unchanged."""
    first, second = tmp_path / "a" / "frame.png", tmp_path / "b" / "other.png"
    for path in (first, second):
        repository.create(path, DAY, 0, 0, "A", "Alpha")
    original = repository.identifications(first)[0]
    repository.edit(original.id, "B", "Beta")
    edited = repository.identifications(first)[0]
    assert (edited.id, edited.number, edited.x, edited.y) == (original.id, 1, 0, 0)
    assert edited.species.common_name == "B"
    assert repository.identifications(second)[0].species.common_name == "A"


def test_image_identity_uses_full_path(repository: Repository, tmp_path: Path) -> None:
    """Keep same-named photographs in different folders independent."""
    original = tmp_path / "original" / "frame.PNG"
    relocated = tmp_path / "relocated" / "frame.PNG"
    repository.create(original, DAY, 10, 20, "A", "Alpha")
    assert repository.connection.execute("SELECT Name FROM IMAGE").fetchone()[0] == original.name
    assert repository.identifications(relocated) == []
    assert repository.image_date(relocated) is None
    repository.create(relocated, DAY, 30, 40, "A", "Alpha")
    repository.save_folder_date(relocated.parent, date(2026, 10, 14))
    assert repository.image_date(original) == DAY
    assert repository.image_date(relocated) == date(2026, 10, 14)
    assert repository.connection.execute("SELECT COUNT(*) FROM IMAGE").fetchone()[0] == 2
    assert [a.number for a in repository.identifications(original)] == [1]
    assert [a.number for a in repository.identifications(relocated)] == [1]
    assert repository.tagged_image_counts() == {str(original): 1, str(relocated): 1}


def test_relative_image_path_is_stored_as_absolute(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve relative paths consistently for writes and subsequent lookups."""
    monkeypatch.chdir(tmp_path)
    relative = Path("photos") / "frame.png"
    repository.create_pending(relative, DAY, 10, 20)
    absolute = tmp_path / relative
    assert repository.connection.execute("SELECT Name FROM IMAGE").fetchone()[0] == absolute.name
    assert repository.pending_identifications(absolute) == repository.pending_identifications(
        relative
    )
    assert repository.further_examination_images() == {str(absolute)}


def test_atomic_failure_and_foreign_keys(repository: Repository, tmp_path: Path) -> None:
    """Roll back newly inserted parents when the final annotation insert fails."""
    connection = repository.connection
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.execute("""CREATE TRIGGER reject_annotation BEFORE INSERT ON IDENTIFICATION
                          BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        repository.create(tmp_path / "frame.png", DAY, 1, 2, "A", "Alpha")
    assert repository.species() == []
    assert connection.execute("SELECT COUNT(*) FROM IMAGE").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO IDENTIFICATION (ImageId, SpeciesId, Number, X, Y) VALUES (999,999,1,0,0)"
        )
    connection.rollback()


def test_duplicates_dates_and_restart(tmp_path: Path) -> None:
    """Persist dates and reject conflicting names without partial records."""
    database = tmp_path / "test.sqlite3"
    connection = connect(database)
    repository = Repository(connection)
    path = tmp_path / "frame.png"
    repository.set_further_examination(path, DAY, False)
    assert repository.image_date(path) == DAY
    assert repository.identifications(path) == []
    repository.create(path, DAY, 0, 0, "A", "Alpha")
    with pytest.raises(ValueError):
        repository.create(tmp_path / "new.png", DAY, 0, 0, "A", "Beta")
    assert repository.image_date(tmp_path / "new.png") is None
    with pytest.raises(ValueError):
        repository.create(path, DAY, 0, 0, " ", "Alpha")
    repository.save_folder_date(path.parent, date(2026, 10, 14))
    connection.close()
    connection = connect(database)
    repository = Repository(connection)
    assert repository.image_date(path) == date(2026, 10, 14)
    assert len(repository.identifications(path)) == 1
    connection.close()


def test_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject absent, relative and directory database configuration."""
    for value in ("", "relative.sqlite3", str(tmp_path), str(tmp_path / "absent" / "db")):
        monkeypatch.setenv("REEFTAG_DB_PATH", value)
        with pytest.raises(ValueError):
            database_path()
    monkeypatch.setenv("REEFTAG_DB_PATH", str(tmp_path / "db.sqlite3"))
    assert database_path() == tmp_path / "db.sqlite3"


def test_integer_primary_and_foreign_keys(repository: Repository, tmp_path: Path) -> None:
    """Let SQLite allocate integer keys and use those keys for all relationships."""
    path = tmp_path / "frame.png"
    repository.create(path, DAY, 10, 20, "A", "Alpha")
    repository.create(path, DAY, 30, 40, "B", "Beta")
    connection = repository.connection
    for table in ("IMAGE", "SPECIES", "IDENTIFICATION"):
        columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}
        assert columns["id"][2] == "INTEGER"
        assert columns["id"][5] == 1
        assert all(
            row[0] == "integer" for row in connection.execute(f"SELECT typeof(id) FROM {table}")
        )
    assert all(
        tuple(row) == ("integer", "integer")
        for row in connection.execute(
            "SELECT typeof(ImageId), typeof(SpeciesId) FROM IDENTIFICATION"
        )
    )
    observations = repository.identifications(path)
    assert all(isinstance(a.id, int) and isinstance(a.species.id, int) for a in observations)
    assert len({a.id for a in observations}) == 2
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO IMAGE (id, Name, FolderId) VALUES (?, ?, ?)",
            ("old-guid", "invalid.png", repository.folders()[0].id),
        )
    connection.rollback()


def test_pending_lifecycle(tmp_path: Path) -> None:
    """Unknowns persist, require examination and convert atomically without consuming numbers."""
    from reef_tag.db import connect

    connection = connect(tmp_path / "unknown.sqlite3")
    repository = Repository(connection)
    path = tmp_path / "unknown.png"
    footage_date = date(2026, 10, 13)
    repository.create_pending(path, footage_date, 12, 34)
    repository.create_pending(path, footage_date, 56, 78)
    pending = repository.pending_identifications(path)
    assert [(item.x, item.y) for item in pending] == [(12, 34), (56, 78)]
    assert repository.further_examination_images() == {str(path)}
    with pytest.raises(ValueError, match="Resolve all unknown"):
        repository.set_further_examination(path, footage_date, False)
    with pytest.raises(ValueError):
        repository.create(path, footage_date, 0, 0, "", "", pending_id=pending[0].id)
    assert repository.pending_identifications(path) == pending
    repository.create(path, footage_date, 0, 0, "Fish", "Fish species", pending_id=pending[0].id)
    identified = repository.identifications(path)[0]
    assert (identified.number, identified.x, identified.y) == (1, 12, 34)
    connection.close()
    connection = connect(tmp_path / "unknown.sqlite3")
    repository = Repository(connection)
    assert repository.pending_identifications(path) == pending[1:]
    repository.delete_pending(pending[1].id)
    assert repository.further_examination_images() == {str(path)}
    repository.set_further_examination(path, footage_date, False)
    assert repository.further_examination_images() == set()
    connection.close()


def test_species_image_names(repository: Repository, tmp_path: Path) -> None:
    """Group distinct image paths by species, excluding unknowns and removed observations."""
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    for path in (first, first, second):
        repository.create(path, DAY, 1, 2, "A", "Alpha")
    repository.create(second, DAY, 1, 2, "B", "Beta")
    repository.create_pending(tmp_path / "unknown.png", DAY, 1, 2)
    species_a, species_b = repository.species()
    assert repository.species_image_names() == {
        species_a.id: {str(first), str(second)},
        species_b.id: {str(second)},
    }
    repository.delete(repository.identifications(second)[-1].id)
    assert repository.species_image_names() == {species_a.id: {str(first), str(second)}}
