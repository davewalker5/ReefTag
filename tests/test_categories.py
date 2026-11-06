"""Category persistence, migration and dialog regression coverage."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from reef_tag.db import connect
from reef_tag.repositories import Repository
from reef_tag.ui.category_dialog import CategoriesDialog, SpeciesMaintenanceDialog
from reef_tag.ui.species_dialog import SpeciesDialog


@pytest.fixture
def repository(tmp_path: Path):
    """Provide a migrated repository and close its connection after the test."""
    connection = connect(tmp_path / "categories.db")
    yield Repository(connection)
    connection.close()


def test_category_validation_and_usage(repository: Repository, tmp_path: Path) -> None:
    """Reject blank/duplicate names and protect used categories across edits."""
    for name in ("", "  ", "\t"):
        with pytest.raises(ValueError):
            repository.save_category(name)
    repository.save_category(" Fish ")
    category = repository.categories()[0]
    assert category.name == "Fish"
    with pytest.raises(ValueError, match="already exists"):
        repository.save_category("FISH")
    repository.create(
        tmp_path / "fish.png", date.today(), 1, 2, "A", "Alpha", category_id=category.id
    )
    species = repository.species()[0]
    assert repository.categories()[0].species_count == 1
    assert repository.identifications(tmp_path / "fish.png")[0].species == species
    with pytest.raises(ValueError, match="cannot be deleted"):
        repository.delete_category(category.id)
    repository.save_category("Fishes", category.id)
    repository.update_species(species.id, "B", "Beta", None)
    assert repository.categories()[0].species_count == 0
    assert repository.identifications(tmp_path / "fish.png")[0].species.common_name == "B"
    repository.delete_category(category.id)
    assert repository.categories() == []


def test_species_edit_is_atomic(repository: Repository, tmp_path: Path) -> None:
    """Reject duplicate names and invalid foreign keys without changing observations."""
    for common, scientific in [("A", "Alpha"), ("B", "Beta")]:
        repository.create(tmp_path / "fish.png", date.today(), 1, 2, common, scientific)
    original = repository.species()
    with pytest.raises(ValueError, match="already exists"):
        repository.update_species(original[0].id, "b", "Gamma", None)
    with pytest.raises(sqlite3.IntegrityError):
        repository.update_species(original[0].id, "C", "Gamma", 999)
    assert repository.species() == original


def test_category_dialogs(
    repository: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Select and clear categories, validate maintenance, and confirm deletion."""
    application = QApplication.instance() or QApplication([])
    parent = SpeciesDialog([], None, None)
    repository.save_category("Fish")
    repository.save_category("Unused")
    fish, unused = repository.categories()
    repository.create(tmp_path / "fish.png", date.today(), 1, 2, "A", "Alpha", category_id=fish.id)
    species = repository.species()[0]
    dialog = SpeciesDialog([species], None, parent, repository.categories())
    dialog.selector.setCurrentIndex(1)
    assert dialog.category_id() == fish.id
    dialog.selector.setCurrentIndex(0)
    assert dialog.category_id() is None
    maintenance = SpeciesMaintenanceDialog(repository, species, parent)
    maintenance.category.setCurrentIndex(0)
    maintenance.common.setText("Renamed")
    maintenance.accept()
    assert repository.species()[0].category_id is None
    assert repository.species()[0].common_name == "Renamed"
    categories = CategoriesDialog(repository, parent)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    categories.delete_category(unused.id)
    assert len(repository.categories()) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    categories.delete_category(unused.id)
    assert len(repository.categories()) == 1
    application.processEvents()
    parent.close()


def test_category_upgrade_preserves_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Upgrade a populated pre-category database with nullable associations."""
    import shutil

    from reef_tag import db

    migrations = db.MIGRATIONS_PATH
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for migration in migrations.glob("*.sql"):
        if not migration.name.startswith("0004"):
            shutil.copy(migration, legacy)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy)
    path = tmp_path / "upgrade.db"
    connection = db.connect(path)
    connection.executescript("""
        INSERT INTO IMAGE VALUES (1, 'image.png', '2026-11-06', 0);
        INSERT INTO SPECIES VALUES (1, 'A', 'Alpha');
        INSERT INTO IDENTIFICATION VALUES (1, 1, 1, 1, 20, 30);
    """)
    original = tuple(connection.execute("SELECT * FROM IDENTIFICATION").fetchone())
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migrations)
    connection = db.connect(path)
    assert tuple(connection.execute("SELECT * FROM IDENTIFICATION").fetchone()) == original
    assert Repository(connection).species()[0].category_id is None
    assert Repository(connection).categories() == []
    connection.close()
