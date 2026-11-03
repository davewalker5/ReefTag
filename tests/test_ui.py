"""Offscreen Qt integration checks for selection, markers and cancellation."""

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from reef_tag.db import connect
from reef_tag.repositories import Repository
from reef_tag.ui.main_window import MainWindow
from reef_tag.ui.species_dialog import SpeciesDialog


@pytest.fixture(scope="session")
def application():
    """Keep a Qt application alive for all widget tests."""
    return QApplication.instance() or QApplication([])


def test_workspace(application: QApplication, tmp_path: Path) -> None:
    """Load persisted markers, hit-test in screen pixels and retain pending dates."""
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    first, second = tmp_path / "a.PNG", tmp_path / "b.jpg"
    image.save(str(first))
    image.save(str(second))
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    repository.create(first, date(2026, 10, 13), 200, 100, "A", "Alpha")
    window = MainWindow(repository)
    window.show()
    window.folder = tmp_path
    window.refresh_folder()
    window.files.selectRow(0)
    application.processEvents()
    assert window.current.rowCount() == 1
    assert window.catalogue.rowCount() == 1
    assert window.footage_date.date().day() == 13
    mapping = window.preview.geometry_map()
    x, y = mapping.to_preview(200, 100)
    window.preview.marker_clicked.disconnect(window.edit_identification)
    marker_spy = QSignalSpy(window.preview.marker_clicked)
    click_spy = QSignalSpy(window.preview.clicked)
    window.preview.clicked.disconnect(window.create_identification)
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=QPoint(int(x + 8), int(y)))
    assert marker_spy.count() == 1
    assert click_spy.count() == 0
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert click_spy.count() == 0
    window.files.selectRow(1)
    window.footage_date.setDate(window.footage_date.date().addDays(2))
    pending = window.footage_date.date()
    window.files.selectRow(0)
    window.files.selectRow(1)
    assert window.footage_date.date() == pending
    assert repository.image_date(second) is None
    dialog = SpeciesDialog(repository.species(), None, window)
    dialog.common.setText("Unsaved")
    dialog.scientific.setText("Unsaved species")
    dialog.reject()
    assert len(repository.species()) == 1
    window.refresh_folder()
    assert window.current_path == second
    window.grab().save("/tmp/reeftag-workspace.png")
    window.close()
    connection.close()


def test_dialog_workflow(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise dialog acceptance, local reassignment, cancellation and deletion."""
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    path = tmp_path / "frame.png"
    image.save(str(path))
    original_bytes = path.read_bytes()
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    window = MainWindow(repository)
    window.folder = tmp_path
    window.refresh_folder()
    window.files.selectRow(0)

    def accept_new(dialog: SpeciesDialog) -> int:
        """Supply a valid species pair as if entered and accepted by the user."""
        dialog.common.setText("Surgeonfish")
        dialog.scientific.setText("Acanthurus leucosternon")
        return dialog.DialogCode.Accepted

    assert window.files.item(0, 0).icon().isNull()
    monkeypatch.setattr(SpeciesDialog, "exec", accept_new)
    window.create_identification(200, 100)
    window.create_identification(210, 100)
    assert window.current.rowCount() == 2
    assert len(window.preview.annotations) == 2
    assert window.catalogue.rowCount() == 1
    assert not window.files.item(0, 0).icon().isNull()
    assert window.files.item(0, 0).toolTip() == "2 saved fish identifications"
    first = window.annotations[0]

    def accept_edit(dialog: SpeciesDialog) -> int:
        """Assign another species without changing the shared original entry."""
        dialog.common.setText("Butterflyfish")
        dialog.scientific.setText("Chaetodon auriga")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(SpeciesDialog, "exec", accept_edit)
    window.edit_identification(first.id)
    assert window.annotations[0].species.common_name == "Butterflyfish"
    assert window.annotations[1].species.common_name == "Surgeonfish"
    assert (window.annotations[0].id, window.annotations[0].x) == (first.id, first.x)
    monkeypatch.setattr(SpeciesDialog, "exec", lambda dialog: dialog.DialogCode.Rejected)
    window.create_identification(300, 100)
    assert len(repository.identifications(path)) == 2

    def accept_delete(dialog: SpeciesDialog) -> int:
        """Return a deletion already confirmed within the dialog."""
        dialog.deleted = True
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(SpeciesDialog, "exec", accept_delete)
    window.edit_identification(first.id)
    assert [a.number for a in window.annotations] == [2]
    assert window.current.rowCount() == 1
    assert not window.files.item(0, 0).icon().isNull()
    assert window.files.item(0, 0).toolTip() == "1 saved fish identification"
    assert len(repository.species()) == 2
    assert path.read_bytes() == original_bytes
    window.show()
    application.processEvents()
    window.grab().save("/tmp/reeftag-annotated.png")
    window.edit_identification(window.annotations[0].id)
    assert window.files.item(0, 0).icon().isNull()
    window.refresh_folder()
    assert window.files.item(0, 0).icon().isNull()
    window.close()
    connection.close()


def test_invalid_image_is_recoverable(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreadable images disable annotations, report the failure and write no rows."""
    (tmp_path / "broken.PNG").write_text("not an image")
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    window = MainWindow(repository)
    failures = []
    monkeypatch.setattr(window, "report_error", failures.append)
    window.folder = tmp_path
    window.refresh_folder()
    window.files.selectRow(0)
    assert failures and "Cannot load broken.PNG" in failures[0]
    assert window.current_path is None
    assert not window.footage_date.isEnabled()
    assert window.preview.pixmap.isNull()
    assert repository.species() == []
    assert connection.execute("SELECT COUNT(*) FROM IMAGE").fetchone()[0] == 0
    window.close()
    connection.close()


def test_preview_brightness(application: QApplication, tmp_path: Path) -> None:
    """Adjust rendered pixels while preserving source files, geometry, markers and data."""
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(40, 80, 120))
    path = tmp_path / "frame.png"
    image.save(str(path))
    original_bytes = path.read_bytes()
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    repository.create(path, date(2026, 10, 13), 200, 100, "A", "Alpha")
    original_annotations = repository.identifications(path)
    window = MainWindow(repository)
    assert not window.brightness_controls.isEnabled()
    assert window.brightness_slider.value() == 0
    window.folder = tmp_path
    window.refresh_folder()
    window.files.selectRow(0)
    window.show()
    application.processEvents()
    assert window.brightness_controls.isEnabled()
    mapping = window.preview.geometry_map()
    sample_x, sample_y = (int(value) for value in mapping.to_preview(50, 50))
    marker_x, marker_y = (int(value) for value in mapping.to_preview(200, 100))

    def rendered() -> QImage:
        """Capture logical preview pixels at the current display setting."""
        return window.preview.grab().toImage()

    neutral = rendered()
    window.brightness_slider.setValue(50)
    brighter = rendered()
    assert (
        brighter.pixelColor(sample_x, sample_y).red() > neutral.pixelColor(sample_x, sample_y).red()
    )
    assert window.brightness_value.text() == "+50"
    window.brightness_slider.setValue(-50)
    darker = rendered()
    assert (
        darker.pixelColor(sample_x, sample_y).red() < neutral.pixelColor(sample_x, sample_y).red()
    )
    for adjusted in (brighter, darker):
        assert adjusted.pixelColor(1, 1) == neutral.pixelColor(1, 1)
        assert adjusted.pixelColor(marker_x, marker_y) == neutral.pixelColor(marker_x, marker_y)
    assert window.preview.geometry_map() == mapping
    window.preview.marker_clicked.disconnect(window.edit_identification)
    marker_spy = QSignalSpy(window.preview.marker_clicked)
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=QPoint(marker_x, marker_y))
    assert marker_spy.count() == 1
    window.refresh_folder()
    assert window.brightness_slider.value() == -50
    assert window.preview.brightness == -50
    window.brightness_reset.click()
    assert window.brightness_slider.value() == 0
    assert window.brightness_value.text() == "0"
    assert rendered() == neutral
    assert window.preview.pixmap.toImage() == image
    assert path.read_bytes() == original_bytes
    assert repository.identifications(path) == original_annotations
    window.clear_image()
    assert not window.brightness_controls.isEnabled()
    window.close()
    connection.close()


def test_marker_click_preserves_large_integer_id(application: QApplication) -> None:
    """Keep SQLite's 64-bit integer IDs intact when emitting a marker click."""
    from PySide6.QtGui import QPixmap

    from reef_tag.models import Identification, Species
    from reef_tag.ui.image_view import ImageView

    view = ImageView()
    image = QPixmap(400, 200)
    image.fill(QColor("teal"))
    identification_id = 2**40
    view.set_image(
        image, [Identification(identification_id, 1, 200, 100, Species(1, "A", "Alpha"))]
    )
    view.show()
    application.processEvents()
    x, y = view.geometry_map().to_preview(200, 100)
    spy = QSignalSpy(view.marker_clicked)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(x), int(y)))
    assert spy.count() == 1
    assert spy.at(0)[0] == identification_id
    view.close()


def test_zoom_right_drag_and_reset(application: QApplication, tmp_path: Path) -> None:
    """Zoom and pan without writes, preserve source coordinates, and reset both controls."""
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    path = tmp_path / "frame.png"
    image.save(str(path))
    original_bytes = path.read_bytes()
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    repository.create(path, date(2026, 10, 13), 200, 100, "A", "Alpha")
    window = MainWindow(repository)
    window.folder = tmp_path
    window.refresh_folder()
    window.files.selectRow(0)
    window.show()
    application.processEvents()
    view = window.preview
    window.zoom_slider.setValue(300)
    assert view.zoom == 3
    assert window.zoom_value.text() == "300%"
    window.zoom_slider.setValue(0)
    assert view.zoom == 1  # The slider never permits zooming below the fitted view.
    window.zoom_slider.setValue(300)
    view.clicked.disconnect(window.create_identification)
    view.marker_clicked.disconnect(window.edit_identification)
    click_spy, marker_spy = QSignalSpy(view.clicked), QSignalSpy(view.marker_clicked)
    centre = QPoint(view.width() // 2, view.height() // 2)
    QTest.mousePress(view, Qt.MouseButton.RightButton, pos=centre)
    QTest.mouseMove(view, centre + QPoint(50, 30))
    QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=centre + QPoint(50, 30))
    assert view.geometry_map().bounded_pan == (50, 30)
    assert click_spy.count() == marker_spy.count() == 0
    mapping = view.geometry_map()
    x, y = mapping.to_preview(200, 100)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(x), int(y)))
    assert marker_spy.count() == 1
    click_point = centre - QPoint(100, 50)
    expected_source = mapping.to_source(click_point.x(), click_point.y())
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click_point)
    assert click_spy.count() == 1
    assert tuple(click_spy.at(0)) == expected_source
    QTest.mousePress(view, Qt.MouseButton.RightButton, pos=centre)
    QTest.mouseMove(view, centre + QPoint(10000, 10000))
    QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=centre + QPoint(10000, 10000))
    assert view.geometry_map().offset == (0, 0)
    window.resize(1400, 900)
    application.processEvents()
    mapping = view.geometry_map()
    left, top = mapping.offset
    assert left <= 0 and left + image.width() * mapping.scale >= view.width()
    assert top <= 0 and top + image.height() * mapping.scale >= view.height()
    window.brightness_slider.setValue(40)
    window.brightness_reset.click()
    assert view.zoom == 1
    assert view.brightness == 0
    assert view.geometry_map().bounded_pan == (0, 0)
    assert window.zoom_slider.value() == 100
    assert path.read_bytes() == original_bytes
    assert len(repository.identifications(path)) == 1
    window.grab().save("/tmp/reeftag-zoom-controls.png")
    window.close()
    connection.close()


def test_last_folder_restored_on_restart(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remember an accepted folder, leave cancellation unchanged and ignore a removed folder."""
    from PySide6.QtWidgets import QFileDialog

    from reef_tag.preferences import Preferences

    folder = tmp_path / "stills"
    folder.mkdir()
    (folder / "frame.png").touch()
    (folder / "ignore.txt").touch()
    preferences_path = tmp_path / "settings" / "preferences.ini"
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    window = MainWindow(repository, Preferences(preferences_path))
    assert window.folder is None
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    window.choose_folder()
    assert window.folder == folder
    assert window.paths == [folder / "frame.png"]
    saved_bytes = preferences_path.read_bytes()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")
    window.choose_folder()
    assert preferences_path.read_bytes() == saved_bytes
    window.close()
    restarted = MainWindow(repository, Preferences(preferences_path))
    assert restarted.folder == folder
    assert restarted.folder_text.text() == str(folder)
    assert restarted.refresh.isEnabled()
    assert restarted.paths == [folder / "frame.png"]
    assert restarted.current_path is None
    restarted.close()
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()
    missing = MainWindow(repository, Preferences(preferences_path))
    assert missing.folder is None
    assert missing.paths == []
    missing.close()
    connection.close()


def test_last_image_restored_on_restart(application: QApplication, tmp_path: Path) -> None:
    """Restore the selected row, photograph, date and annotations; tolerate its later removal."""
    from reef_tag.preferences import Preferences

    folder = tmp_path / "stills"
    folder.mkdir()
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    for filename in ("a.png", "b.png"):
        image.save(str(folder / filename))
    path = folder / "b.png"
    settings_path = tmp_path / "settings/preferences.ini"
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    repository.create(path, date(2026, 10, 13), 10, 20, "A", "Alpha")
    window = MainWindow(repository, Preferences(settings_path))
    window.open_folder(folder)
    window.files.selectRow(1)
    assert window.current_path == path
    window.close()
    restarted = MainWindow(repository, Preferences(settings_path))
    assert restarted.current_path == path
    assert restarted.files.currentRow() == 1
    assert restarted.files.item(0, 0).icon().isNull()
    assert not restarted.files.item(1, 0).icon().isNull()
    assert not restarted.preview.pixmap.isNull()
    assert restarted.current.rowCount() == 1
    assert restarted.footage_date.date().day() == 13
    restarted.close()
    path.unlink()
    missing = MainWindow(repository, Preferences(settings_path))
    assert missing.folder == folder
    assert missing.current_path is None
    assert missing.paths == [folder / "a.png"]
    missing.close()
    connection.close()


def test_preview_settings_restore_and_reset_for_new_image(
    application: QApplication, tmp_path: Path
) -> None:
    """Restore controls for the last image only, and save neutral controls on image switches."""
    from reef_tag.preferences import Preferences, PreviewSettings

    folder = tmp_path / "stills"
    folder.mkdir()
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    for name in ("a.png", "b.png"):
        image.save(str(folder / name))
    preferences_path = tmp_path / "preferences.ini"
    connection = connect(tmp_path / "db.sqlite3")
    repository = Repository(connection)
    window = MainWindow(repository, Preferences(preferences_path))
    window.open_folder(folder)
    window.files.selectRow(0)
    window.brightness_slider.setValue(35)
    window.zoom_slider.setValue(250)
    window.close()
    restored = MainWindow(repository, Preferences(preferences_path))
    assert restored.current_path == folder / "a.png"
    assert restored.preview.brightness == 35
    assert restored.preview.zoom == 2.5
    assert restored.brightness_slider.value() == 35
    assert restored.zoom_slider.value() == 250
    restored.files.selectRow(1)
    assert restored.preview.brightness == 0
    assert restored.preview.zoom == 1
    assert restored.preferences.preview_settings() == PreviewSettings()
    restored.files.selectRow(0)
    assert restored.preview.brightness == 0
    assert restored.preview.zoom == 1
    restored.brightness_slider.setValue(-20)
    restored.zoom_slider.setValue(200)
    restored.brightness_reset.click()
    assert restored.preferences.preview_settings() == PreviewSettings()
    restored.close()
    (folder / "a.png").unlink()
    missing = MainWindow(repository, Preferences(preferences_path))
    assert missing.current_path is None
    assert missing.preview.brightness == 0
    assert missing.preview.zoom == 1
    missing.close()
    connection.close()
