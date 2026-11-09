"""Folder location associations, atomic editing and schema upgrade coverage."""

import shutil
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from yoyo import get_backend, read_migrations

from reef_tag import db
from reef_tag.models import ImagePathChange
from reef_tag.repositories import Repository
from reef_tag.ui.folder_editor_dialog import FolderEditorDialog
from reef_tag.ui.folder_mapping_dialog import FolderManagementDialog

DAY = date(2026, 11, 9)


@pytest.fixture(scope="session")
def application() -> QApplication:
    """Keep a single application alive for the editor and management windows."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[Repository]:
    """Provide a migrated database with a located folder and one annotation."""
    connection = db.connect(tmp_path / "locations.db")
    repository = Repository(connection)
    repository.save_location("Reef", "Atoll", "Maldives")
    repository.create_pending(tmp_path / "old" / "fish.png", DAY, 10, 20)
    folder = repository.folders()[0]
    repository.save_folder(folder, folder.path, DAY, repository.locations()[0].id)
    yield repository
    connection.close()


def test_save_and_clear_folder_location(repository: Repository) -> None:
    """Save and clear a location, applying folder dates while preserving observations."""
    folder = repository.folders()[0]
    image = Path(next(iter(folder.images.values())))
    original = repository.pending_identifications(image)
    second = date(2026, 11, 10)
    repository.save_folder(folder, folder.path, second, None)
    updated = repository.folders()[0]
    assert updated.id == folder.id
    assert updated.location_id is None
    assert updated.default_date == second
    assert repository.image_date(image) == second
    assert repository.pending_identifications(image) == original
    repository.save_folder_date(folder.path, DAY)
    repository.save_folder(
        updated := repository.folders()[0], updated.path, DAY, folder.location_id
    )
    repository.save_folder_date(folder.path, second)
    assert repository.folders()[0].location_id == folder.location_id


def test_atomic_relocation_and_invalid_location(repository: Repository, tmp_path: Path) -> None:
    """Retain metadata through moves and roll back every field for an invalid reference."""
    folder = repository.folders()[0]
    destination = tmp_path / "new"
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_folder(folder, destination, date(2026, 11, 10), 999)
    assert repository.folders() == (folder,)
    repository.relocate_folder(folder, destination)
    moved = repository.folders()[0]
    assert moved.id == folder.id
    assert moved.location_id == folder.location_id
    assert moved.path == destination
    assert len(repository.pending_identifications(destination / "fish.png")) == 1
    with pytest.raises(ValueError, match="folder changed"):
        repository.save_folder(folder, folder.path, DAY, None)
    assert repository.folders() == (moved,)


def test_merge_collision_rolls_back_metadata(repository: Repository, tmp_path: Path) -> None:
    """Colliding filenames preserve both folders and their original metadata."""
    source = repository.folders()[0]
    destination = tmp_path / "new"
    repository.create_pending(destination / "fish.png", DAY, 30, 40)
    before = repository.folders()
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_folder(source, destination, date(2026, 11, 10), None)
    assert repository.folders() == before


def test_merge_applies_explicit_editor_values(repository: Repository, tmp_path: Path) -> None:
    """A successful merge saves the editor's chosen date and location with all images."""
    folder = repository.folders()[0]
    destination = tmp_path / "new"
    repository.create_pending(destination / "other.png", DAY, 30, 40)
    second = date(2026, 11, 10)
    repository.save_folder(folder, destination, second, folder.location_id)
    merged = repository.folders()[0]
    assert len(repository.folders()) == 1
    assert len(merged.images) == 2
    assert merged.location_id == folder.location_id
    assert merged.default_date == second


def test_image_path_mapping_preserves_location(repository: Repository, tmp_path: Path) -> None:
    """The existing path-mapping API carries location to a newly created destination."""
    folder = repository.folders()[0]
    image_id, original = next(iter(folder.images.items()))
    repository.update_image_paths(
        (ImagePathChange(image_id, original, str(tmp_path / "new" / "fish.png")),)
    )
    assert repository.folders()[0].location_id == folder.location_id


def test_cancel_discards_all_staged_fields(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Choosing a valid path, date and location performs no writes before OK."""
    folder = repository.folders()[0]
    destination = tmp_path / "new"
    destination.mkdir()
    (destination / "fish.png").touch()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(destination))
    editor = FolderEditorDialog(repository, folder)
    assert editor.location.currentData() == folder.location_id
    editor.browse.click()
    editor.default_date.setDate(QDate(2026, 11, 10))
    editor.location.setCurrentIndex(0)
    assert editor.destination == destination
    assert repository.folders() == (folder,)
    editor.reject()
    assert repository.folders() == (folder,)
    editor = FolderEditorDialog(repository, folder)
    editor.location.setCurrentIndex(0)
    editor.default_date.setDate(QDate(2026, 11, 10))
    editor.accept()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert repository.folders()[0].location_id is None
    assert repository.folders()[0].default_date == date(2026, 11, 10)


def test_failed_save_keeps_editor_open(
    application: QApplication,
    repository: Repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report stale edits and keep their values available without committing them."""
    folder = repository.folders()[0]
    editor = FolderEditorDialog(repository, folder)
    repository.save_folder_date(folder.path, date(2026, 11, 10))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    editor.accept()
    assert editor.result() != QDialog.DialogCode.Accepted
    assert "folder changed" in warnings[0]
    assert repository.folders()[0].default_date == date(2026, 11, 10)


@pytest.mark.parametrize("column", range(7))
def test_every_column_opens_folder_editor(
    application: QApplication,
    repository: Repository,
    monkeypatch: pytest.MonkeyPatch,
    column: int,
) -> None:
    """Double-clicking any cell opens the same editor and refreshes the saved location."""
    opened = []

    def save(editor: FolderEditorDialog) -> int:
        """Clear the association through the actual folder editor."""
        opened.append(editor.folder.id)
        editor.location.setCurrentIndex(0)
        editor.accept()
        return editor.result()

    monkeypatch.setattr(FolderEditorDialog, "exec", save)
    management = FolderManagementDialog(repository)
    assert management.table.item(0, 2).text() == "Reef"
    management.table.cellDoubleClicked.emit(0, column)
    assert opened == [repository.folders()[0].id]
    assert management.changed
    assert management.table.item(0, 2).text() == ""
    management.close()


def test_folder_location_upgrade_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrade populated phase-one data with nullable locations and reverse losslessly."""
    migrations = db.MIGRATIONS_PATH
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for source in migrations.glob("*.sql"):
        if source.name[:4] < "0007":
            shutil.copy(source, legacy)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy)
    path = tmp_path / "upgrade.db"
    connection = db.connect(path)
    connection.execute(
        "INSERT INTO FOLDER (Id, Path, Date) VALUES (1, ?, ?)",
        (str(tmp_path / "old"), DAY.isoformat()),
    )
    connection.execute(
        "INSERT INTO IMAGE (id, FolderId, Name, Date) VALUES (1, 1, 'fish.png', ?)",
        (DAY.isoformat(),),
    )
    connection.execute("INSERT INTO PENDING_IDENTIFICATION VALUES (1, 1, 10, 20)")
    connection.commit()
    original = tuple(connection.execute("SELECT Id, Path, Date FROM FOLDER").fetchone())
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migrations)
    connection = db.connect(path)
    assert tuple(connection.execute("SELECT * FROM FOLDER").fetchone()) == (*original, None)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE FOLDER SET LocationId=999")
    connection.rollback()
    repository = Repository(connection)
    repository.save_location("Reef", "Atoll", "Maldives")
    folder = repository.folders()[0]
    repository.save_folder(folder, folder.path, DAY, repository.locations()[0].id)
    connection.close()
    connection = db.connect(path)
    assert Repository(connection).folders()[0].location_id is not None
    connection.close()
    with get_backend("sqlite:///" + quote(str(path), safe="/")) as backend:
        backend.connection.execute("PRAGMA foreign_keys=ON")
        with backend.lock():
            pending = backend.to_rollback(read_migrations(str(migrations)))
            backend.rollback_migrations([m for m in pending if m.id >= "0007_folder_locations"])
        assert (
            tuple(
                backend.connection.execute(
                    "SELECT Id, Path, CAST(Date AS TEXT) FROM FOLDER"
                ).fetchone()
            )
            == original
        )
        assert (
            backend.connection.execute("SELECT COUNT(*) FROM PENDING_IDENTIFICATION").fetchone()[0]
            == 1
        )
        assert backend.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection = db.connect(path)
    assert Repository(connection).folders()[0].location_id is None
    connection.close()
