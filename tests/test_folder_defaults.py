"""Database folder defaults, normalised image identities and lossless upgrades."""

import shutil
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from yoyo import get_backend, read_migrations

from reef_tag import db
from reef_tag.models import ImagePathChange
from reef_tag.repositories import Repository


def test_populated_upgrade_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the lowest image ID's date and preserve annotations through both directions."""
    migrations = db.MIGRATIONS_PATH
    legacy = tmp_path / "migrations"
    legacy.mkdir()
    for source in migrations.glob("*.sql"):
        if source.name[:4] < "0005":
            shutil.copy(source, legacy)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy)
    path = tmp_path / "upgrade.db"
    connection = db.connect(path)
    images = [
        (9, "/photos/a.png", "2026-10-13", 1),
        (2, "/photos/b.png", "2026-10-11", 0),
        (3, "/other/a.png", "2026-10-12", 0),
        (4, "/root.png", "2026-10-10", 0),
        (5, "legacy.png", "2026-10-09", 0),
        (6, r"C:\photos\fish.png", "2026-10-08", 0),
    ]
    connection.executemany("INSERT INTO IMAGE VALUES (?, ?, ?, ?)", images)
    connection.execute("INSERT INTO SPECIES VALUES (1, 'A', 'Alpha', NULL)")
    connection.execute("INSERT INTO IDENTIFICATION VALUES (1, 9, 1, 1, 10, 20)")
    connection.execute("INSERT INTO PENDING_IDENTIFICATION VALUES (1, 9, 30, 40)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migrations)
    connection = db.connect(path)
    assert dict(connection.execute("SELECT Path, Date FROM FOLDER")) == {
        "/photos": "2026-10-11",
        "/other": "2026-10-12",
        "/": "2026-10-10",
        "": "2026-10-09",
        r"C:\photos": "2026-10-08",
    }
    assert dict(connection.execute("SELECT id, Name FROM IMAGE")) == {
        9: "a.png",
        2: "b.png",
        3: "a.png",
        4: "root.png",
        5: "legacy.png",
        6: "fish.png",
    }
    assert Repository(connection).image_paths() == {row[0]: row[1] for row in images}
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE IMAGE SET FolderId=999 WHERE id=9")
    connection.rollback()
    connection.close()
    with get_backend("sqlite:///" + quote(str(path), safe="/")) as backend:
        backend.connection.execute("PRAGMA foreign_keys=ON")
        with backend.lock():
            pending = backend.to_rollback(read_migrations(str(migrations)))
            backend.rollback_migrations([m for m in pending if m.id >= "0005_folder_defaults"])
        assert sorted(backend.connection.execute("SELECT * FROM IMAGE")) == sorted(images)
        assert backend.connection.execute("SELECT * FROM IDENTIFICATION").fetchall() == [
            (1, 9, 1, 1, 10, 20)
        ]
        assert backend.connection.execute("SELECT * FROM PENDING_IDENTIFICATION").fetchall() == [
            (1, 9, 30, 40)
        ]
        assert backend.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    db.connect(path).close()


def test_defaults_persist_and_mapping_preserves_destination_default(tmp_path: Path) -> None:
    """Store defaults independently of images and retain a mapped destination's date."""
    path = tmp_path / "folders.db"
    old, new, empty = (tmp_path / name for name in ("old", "new", "empty"))
    first, second = date(2026, 10, 13), date(2026, 10, 14)
    connection = db.connect(path)
    repository = Repository(connection)
    repository.save_folder_date(empty, second)
    repository.create_pending(old / "a.png", first, 1, 2)
    repository.save_folder_date(old, second)
    assert repository.image_date(old / "a.png") == first
    repository.save_folder_date(new, first)
    image_id = next(iter(repository.image_paths()))
    repository.update_image_paths(
        (ImagePathChange(image_id, str(old / "a.png"), str(new / "a.png")),)
    )
    assert repository.folder_date(old) is None
    assert repository.folder_date(new) == first
    assert len(repository.pending_identifications(new / "a.png")) == 1
    connection.close()
    connection = db.connect(path)
    assert Repository(connection).folder_date(empty) == second
    assert Repository(connection).image_date(new / "a.png") == first
    connection.close()
