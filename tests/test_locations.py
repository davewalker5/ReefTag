"""Location persistence, validation, migration and dialog coverage."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from reef_tag import db
from reef_tag.repositories import Repository
from reef_tag.ui.location_dialog import LocationEditorDialog, LocationsDialog


@pytest.fixture
def repository(tmp_path: Path):
    """Provide a migrated repository with a connection owned by the fixture."""
    connection = db.connect(tmp_path / "locations.db")
    yield Repository(connection)
    connection.close()


def test_location_persistence(repository: Repository) -> None:
    """Create, edit, trim and clear optional coordinates without changing IDs."""
    repository.save_location(" Reef ", " Atoll ", " Maldives ", 3.88549, 72.72746)
    original = repository.locations()[0]
    assert (original.name, original.region, original.country) == ("Reef", "Atoll", "Maldives")
    assert original.latitude == 3.88549
    assert original.longitude == 72.72746
    repository.save_location("Updated", "Region", "Country", None, 0, original.id)
    updated = repository.locations()[0]
    assert updated.id == original.id
    assert updated.latitude is None
    assert updated.longitude == 0
    with pytest.raises(ValueError, match="no longer exists"):
        repository.save_location("A", "B", "C", location_id=999)
    assert repository.locations() == [updated]


@pytest.mark.parametrize(
    "values",
    [
        (" ", "B", "C", None, None),
        ("A", "", "C", None, None),
        ("A", "B", "\t", None, None),
        ("A", "B", "C", 90.01, 0),
        ("A", "B", "C", -90.01, 0),
        ("A", "B", "C", 0, 180.01),
        ("A", "B", "C", 0, -180.01),
        ("A", "B", "C", float("nan"), 0),
        ("A", "B", "C", 0, float("inf")),
    ],
)
def test_invalid_location_is_not_saved(repository: Repository, values: tuple) -> None:
    """Reject missing text, out-of-range coordinates and nonfinite values atomically."""
    repository.save_location("Original", "Region", "Country", -90, 180)
    original = repository.locations()[0]
    with pytest.raises(ValueError):
        repository.save_location(*values, location_id=original.id)
    assert repository.locations() == [original]


def test_location_dialogs(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Save valid edits, retain invalid input, and discard cancelled changes."""
    application = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    editor = LocationEditorDialog(repository, None)
    editor.accept()
    assert warnings and repository.locations() == []
    editor.name.setText("Reef")
    editor.region.setText("Atoll")
    editor.country.setText("Maldives")
    editor.latitude.setText("invalid")
    editor.accept()
    assert "Latitude" in warnings[-1]
    assert repository.locations() == []
    editor.latitude.setText("0")
    editor.accept()
    assert editor.result() == QDialog.DialogCode.Accepted
    location = repository.locations()[0]
    cancelled = LocationEditorDialog(repository, location)
    cancelled.name.setText("Discard this")
    cancelled.reject()
    assert repository.locations() == [location]
    maintenance = LocationsDialog(repository)
    assert maintenance.table.item(0, 0).text() == "Reef"
    assert maintenance.table.item(0, 4).text() == ""
    monkeypatch.setattr(LocationEditorDialog, "exec", lambda self: self.accept() or self.result())
    maintenance.edit_location(0, 2)
    assert repository.locations() == [location]
    maintenance.close()
    application.processEvents()


def test_location_upgrade_preserves_existing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Upgrade phase-zero data and retain saved locations after reopening."""
    migrations = db.MIGRATIONS_PATH
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for source in migrations.glob("*.sql"):
        if source.name[:4] < "0006":
            shutil.copy(source, legacy)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy)
    path = tmp_path / "upgrade.db"
    connection = db.connect(path)
    connection.executescript("INSERT INTO FOLDER (Path, Date) VALUES ('reef', '2026-11-09');")
    original = tuple(connection.execute("SELECT * FROM FOLDER").fetchone())
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migrations)
    connection = db.connect(path)
    assert tuple(connection.execute("SELECT * FROM FOLDER").fetchone()) == original
    Repository(connection).save_location("Reef", "Region", "Country")
    connection.close()
    connection = db.connect(path)
    assert Repository(connection).locations()[0].name == "Reef"
    connection.close()


def test_location_menu_opens_maintenance(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    """Route the always-available Tools action to location maintenance."""
    from reef_tag.ui.main_window import MainWindow

    application = QApplication.instance() or QApplication([])
    opened = []
    monkeypatch.setattr(LocationsDialog, "exec", lambda self: opened.append(self.repository) or 0)
    window = MainWindow(repository)
    assert window.manage_locations_action.isEnabled()
    window.manage_locations_action.trigger()
    assert opened == [repository]
    window.close()
    application.processEvents()
