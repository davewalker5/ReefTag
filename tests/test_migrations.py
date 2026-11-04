"""Versioned schema creation, upgrades and failure handling."""

import shutil
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from yoyo import get_backend, read_migrations

from reef_tag import db
from reef_tag.repositories import Repository


def test_initial_migration_and_repeat_startup(tmp_path: Path) -> None:
    """Track initial creation once, including paths with SQLite URI reserved characters."""
    path = tmp_path / "reef ?#% stills.sqlite3"
    connection = db.connect(path)
    repository = Repository(connection)
    repository.create(tmp_path / "fish.png", date(2026, 10, 13), 10, 20, "A", "Alpha")
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert {row[0] for row in connection.execute("SELECT migration_id FROM _yoyo_migration")} == {
        "0001_initial_schema",
        "0002_further_examination",
    }
    connection.close()
    connection = db.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM _yoyo_migration").fetchone()[0] == 2
    assert len(Repository(connection).identifications(tmp_path / "fish.png")) == 1
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()
    assert list(tmp_path.iterdir()) == [path]


def test_initial_rollback_and_reapply(tmp_path: Path) -> None:
    """Reverse the initial migration cleanly, then recreate it on next startup."""
    path = tmp_path / "reef.sqlite3"
    db.connect(path).close()
    migrations = read_migrations(str(db.MIGRATIONS_PATH))
    with get_backend("sqlite:///" + quote(str(path), safe="/")) as backend:
        backend.connection.execute("PRAGMA foreign_keys = ON")
        with backend.lock():
            backend.rollback_migrations(backend.to_rollback(migrations))
        tables = {
            row[0]
            for row in backend.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert not tables.intersection({"IMAGE", "SPECIES", "IDENTIFICATION"})
    connection = db.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM IDENTIFICATION").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM _yoyo_migration").fetchone()[0] == 2
    connection.close()


def test_pending_upgrade_and_failed_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply future dependent migrations once and atomically undo failed schema changes."""
    migration_path = tmp_path / "migrations"
    shutil.copytree(db.MIGRATIONS_PATH, migration_path)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migration_path)
    path = tmp_path / "reef.sqlite3"
    connection = db.connect(path)
    Repository(connection).create(tmp_path / "fish.png", date(2026, 10, 13), 0, 0, "A", "Alpha")
    connection.close()
    (migration_path / "0003_test_upgrade.sql").write_text(
        "-- depends: 0002_further_examination\nALTER TABLE IMAGE ADD COLUMN Notes TEXT;\n"
    )
    connection = db.connect(path)
    assert connection.execute("SELECT Notes FROM IMAGE").fetchone()[0] is None
    assert connection.execute("SELECT COUNT(*) FROM _yoyo_migration").fetchone()[0] == 3
    connection.close()
    (migration_path / "0004_test_failure.sql").write_text(
        "-- depends: 0003_test_upgrade\nCREATE TABLE partial_change (id INTEGER);\n"
        "INSERT INTO absent_table VALUES (1);\n"
    )
    with pytest.raises(db.MigrationError, match="Cannot apply ReefTag database migrations"):
        db.connect(path)
    connection = sqlite3.connect(path)
    assert (
        connection.execute("SELECT name FROM sqlite_master WHERE name='partial_change'").fetchone()
        is None
    )
    assert connection.execute("SELECT COUNT(*) FROM _yoyo_migration").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM IDENTIFICATION").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM yoyo_lock").fetchone()[0] == 0
    connection.close()


def test_unversioned_database_requires_fresh_file(tmp_path: Path) -> None:
    """Report an incompatible test schema without silently marking it as migrated."""
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE IMAGE (legacy TEXT)")
    connection.close()
    with pytest.raises(db.MigrationError, match="use a fresh database file"):
        db.connect(path)
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM _yoyo_migration").fetchone()[0] == 0
    assert connection.execute("PRAGMA table_info(IMAGE)").fetchone()[1] == "legacy"
    connection.close()


def test_missing_migration_assets_fail_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never start the application with an empty schema if bundled assets are missing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", empty)
    with pytest.raises(db.MigrationError, match="No bundled database migrations"):
        db.connect(tmp_path / "reef.sqlite3")


def test_further_examination_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Upgrade a populated original database without changing its saved observations."""
    original_migrations = db.MIGRATIONS_PATH
    legacy_migrations = tmp_path / "legacy_migrations"
    legacy_migrations.mkdir()
    for source in original_migrations.glob("0001*.sql"):
        shutil.copy(source, legacy_migrations)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy_migrations)
    database = tmp_path / "reef.sqlite3"
    path = tmp_path / "fish.png"
    connection = db.connect(database)
    Repository(connection).create(path, date(2026, 10, 13), 10, 20, "A", "Alpha")
    observations = Repository(connection).identifications(path)
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", original_migrations)
    connection = db.connect(database)
    repository = Repository(connection)
    assert repository.identifications(path) == observations
    assert connection.execute("SELECT FurtherExamination FROM IMAGE").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE IMAGE SET FurtherExamination=2")
    connection.rollback()
    repository.set_further_examination(path, date.today(), True)
    assert repository.image_date(path) == date(2026, 10, 13)
    connection.close()
    connection = db.connect(database)
    assert Repository(connection).further_examination_images() == {"fish.png"}
    connection.close()
