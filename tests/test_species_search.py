"""Database-wide search, read-only previews and native viewer navigation."""

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from reef_tag.db import connect
from reef_tag.repositories import Repository
from reef_tag.ui.main_window import MainWindow
from reef_tag.ui.species_search_dialog import SpeciesSearchDialog


@pytest.fixture(scope="module")
def application() -> QApplication:
    """Keep a Qt application alive for the search dialog tests."""
    return QApplication.instance() or QApplication([])


def test_species_query(tmp_path: Path) -> None:
    """Group repeated identifications across folders and leave all records unchanged."""
    connection = connect(tmp_path / "search.sqlite3")
    repository = Repository(connection)
    first, second = tmp_path / "one/a.png", tmp_path / "two/a.png"
    repository.create(first, date(2026, 10, 13), 1, 1, "Idol", "Zanclus cornutus")
    repository.create(first, date(2026, 10, 13), 2, 2, "Idol", "Zanclus cornutus")
    repository.create(second, date(2026, 10, 14), 1, 1, "Idol", "Zanclus cornutus")
    repository.create(first, date(2026, 10, 13), 3, 3, "Shark", "Nebrius ferrugineus")
    repository.create_pending(second, date(2026, 10, 14), 4, 4)
    with connection:
        connection.execute(
            "INSERT INTO SPECIES (CommonName, ScientificName) VALUES ('Unused', 'Unused species')"
        )
    before = list(connection.iterdump())
    species = repository.identified_species()
    assert [entry.common_name for entry in species] == ["Idol", "Shark"]
    images = repository.images_for_species(species[0].id)
    assert [(image.path, image.footage_date, image.count) for image in images] == [
        (str(first), "2026-10-13", 2),
        (str(second), "2026-10-14", 1),
    ]
    assert len({image.id for image in images}) == 2
    assert repository.images_for_species(-1) == []
    assert repository.images_for_species("1 OR 1=1") == []
    assert list(connection.iterdump()) == before
    connection.close()


def test_search_preview_and_native_viewer(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sort numerically, filter markers and retain context after native navigation."""
    connection = connect(tmp_path / "search.sqlite3")
    repository = Repository(connection)
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    for path, count in ((first, 12), (second, 2)):
        image.save(str(path))
        for number in range(count):
            repository.create(path, date(2026, 10, 13), number, 10, "Idol", "Zanclus")
    repository.create(first, date(2026, 10, 13), 100, 100, "Shark", "Nebrius")
    repository.create_pending(first, date(2026, 10, 13), 150, 100)
    before = list(connection.iterdump())
    window = MainWindow(repository)
    assert window.find_species_action.text() == "Find Species"
    assert window.current_path is None
    dialog = SpeciesSearchDialog(repository, window)
    dialog.show()
    dialog.selector.completer().setCompletionPrefix("zan")
    assert dialog.selector.completer().completionCount() == 1
    dialog.selector.setCurrentIndex(1)
    assert dialog.results.rowCount() == 2
    dialog.results.sortItems(2, Qt.SortOrder.DescendingOrder)
    dialog.results.selectRow(0)
    application.processEvents()
    assert dialog.selected_image().path == str(first)
    assert len(dialog.preview.annotations) == 12
    dialog.zoom.setValue(200)
    dialog.brightness.setValue(20)
    assert dialog.preview.zoom == 2
    assert dialog.preview.brightness == 20
    dialog.grab().save("/tmp/reeftag-species-search.png")
    assert not dialog.preview.pending
    assert {item.species.id for item in dialog.preview.annotations} == {
        dialog.selector.currentData()
    }
    opened = []
    monkeypatch.setattr(
        "reef_tag.ui.species_search_dialog.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    dialog.open_image(0, 0)
    assert opened == [str(first)]
    assert dialog.selected_image().path == str(first)
    assert dialog.results.horizontalHeader().sortIndicatorSection() == 2
    dialog.results.selectRow(1)
    assert len(dialog.preview.annotations) == 2
    second.unlink()
    dialog.show_image()
    assert dialog.preview.pixmap.isNull()
    assert not dialog.preview.annotations
    assert "missing or unreadable" in dialog.preview_status.text()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog.open_image(1, 0)
    assert len(warnings) == 1
    assert opened == [str(first)]
    assert list(connection.iterdump()) == before
    assert window.current_path is None
    dialog.close()
    window.close()
    connection.close()


def test_empty_search(application: QApplication, tmp_path: Path) -> None:
    """Explain an empty catalogue and a species whose last occurrence was removed."""
    connection = connect(tmp_path / "search.sqlite3")
    repository = Repository(connection)
    parent = MainWindow(repository)
    empty = SpeciesSearchDialog(repository, parent)
    assert "No species" in empty.summary.text()
    empty.close()
    path = tmp_path / "missing.png"
    repository.create(path, date(2026, 10, 13), 1, 1, "Idol", "Zanclus")
    dialog = SpeciesSearchDialog(repository, parent)
    repository.delete(repository.identifications(path)[0].id)
    dialog.selector.setCurrentIndex(1)
    assert dialog.summary.text() == "No matching images found."
    assert dialog.results.rowCount() == 0
    assert dialog.preview.pixmap.isNull()
    dialog.close()
    parent.close()
    connection.close()
