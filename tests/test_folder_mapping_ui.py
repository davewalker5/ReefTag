"""Dialog navigation and automatic/manual folder recovery integration."""

import os
import sqlite3
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from reef_tag.db import connect
from reef_tag.folder_mapping import discover_missing_folders
from reef_tag.repositories import Repository
from reef_tag.ui.folder_mapping_dialog import FolderMappingDialog, MappingStatus, check_image_paths
from reef_tag.ui.main_window import MainWindow

DAY = date(2026, 10, 13)


@pytest.fixture(scope="session")
def application():
    """Use the shared offscreen Qt application for recovery dialogs."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repository(tmp_path: Path):
    """Keep all mapping actions in a fresh temporary database."""
    connection = connect(tmp_path / "mapping.sqlite3")
    yield Repository(connection)
    connection.close()


def add_image(repository: Repository, directory: Path, filename: str = "one.png") -> None:
    """Record an observation without requiring its source photograph to exist."""
    repository.create(directory / filename, DAY, 1, 2, "A", "Alpha")


def destination(tmp_path: Path, name: str, filenames: tuple[str, ...] = ("one.png",)) -> Path:
    """Create a directly matching destination for a test mapping."""
    directory = tmp_path / name
    directory.mkdir()
    for filename in filenames:
        (directory / filename).touch()
    return directory


@pytest.mark.parametrize("with_image", [False, True])
def test_no_dialog_for_healthy_startup_and_manual_success(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_image: bool,
) -> None:
    """Startup is silent; an explicit check reports success without checking individual files."""
    if with_image:
        add_image(repository, tmp_path)
    messages = []

    def unexpected_dialog(dialog):
        """Fail if a healthy database prompts for a replacement."""
        pytest.fail("Unexpected mapping dialog")

    monkeypatch.setattr(FolderMappingDialog, "exec", unexpected_dialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    assert not check_image_paths(repository)
    assert messages == []
    assert not check_image_paths(repository, manual=True)
    assert messages == ["All image folders referenced by ReefTag were found."]


def test_navigation_retains_edits_without_saving(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back and Next only navigate, retaining edits and respecting the end boundaries."""
    for name in ("a", "b", "c"):
        add_image(repository, tmp_path / name)
    before = repository.image_paths()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    application.processEvents()
    assert not dialog.back.isEnabled()
    assert dialog.next.isEnabled()
    assert dialog.next.text() == "Next >>"
    assert dialog.done_button.text() == "Done"
    buttons = (dialog.back, dialog.next, dialog.skip, dialog.done_button)
    assert [button.x() for button in buttons] == sorted(button.x() for button in buttons)
    assert (
        dialog.done_button.geometry().right()
        == dialog.width() - dialog.layout().contentsMargins().right() - 1
    )
    assert dialog.back.x() > dialog.layout().contentsMargins().left()
    dialog.replacement.setText("retained first selection")
    dialog.next.click()
    assert dialog.index == 1
    assert dialog.back.isEnabled() and dialog.next.isEnabled()
    dialog.replacement.setText("retained second selection")
    dialog.back.click()
    assert dialog.replacement.text() == "retained first selection"
    assert not dialog.back.isEnabled()
    dialog.next.click()
    assert dialog.replacement.text() == "retained second selection"
    dialog.next.click()
    assert dialog.index == 2
    assert not dialog.next.isEnabled()
    assert dialog.next.text() == "Next >>"
    dialog.go_next()
    assert dialog.index == 2
    assert repository.image_paths() == before
    assert not dialog.changed
    assert errors == []
    dialog.close()


def test_single_candidate_disables_both_navigation_buttons(
    application: QApplication, repository: Repository, tmp_path: Path
) -> None:
    """A single folder keeps Next's label and leaves Skip and Done available."""
    add_image(repository, tmp_path / "old")
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    assert not dialog.back.isEnabled()
    assert not dialog.next.isEnabled()
    assert dialog.next.text() == "Next >>"
    assert dialog.skip.isEnabled() and dialog.done_button.isEnabled()
    dialog.close()


@pytest.mark.parametrize("completion", ["enter", "focus"])
def test_typed_path_saves_on_completion_without_unexpected_navigation(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    completion: str,
) -> None:
    """Keyboard and focus completion save edits without advancing the folder twice."""
    first, second = tmp_path / "a", tmp_path / "b"
    add_image(repository, first)
    add_image(repository, second)
    replacement = destination(tmp_path, "new")
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    application.processEvents()
    dialog.replacement.setFocus()
    dialog.replacement.selectAll()
    QTest.keyClicks(dialog.replacement, str(replacement))
    if completion == "enter":
        QTest.keyClick(dialog.replacement, Qt.Key.Key_Return)
        assert dialog.index == 0
    else:
        QTest.mouseClick(dialog.next, Qt.MouseButton.LeftButton)
        assert dialog.index == 1
        dialog.back.click()
    assert dialog.isVisible() and dialog.changed
    assert dialog.replacement.isReadOnly()
    assert set(repository.image_paths().values()) == {
        str(replacement / "one.png"),
        str(second / "one.png"),
    }
    dialog.done_button.click()


@pytest.mark.parametrize("finish", ["skip", "done_button", "close"])
def test_skip_and_close_preserve_unresolved_paths(
    application: QApplication, repository: Repository, tmp_path: Path, finish: str
) -> None:
    """The only candidate can always be left unresolved without blocking normal operation."""
    add_image(repository, tmp_path / "old")
    before = repository.image_paths()
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    dialog.replacement.setText("uncommitted selection")
    assert not dialog.back.isEnabled()
    assert dialog.next.text() == "Next >>"
    if finish == "close":
        dialog.close()
    else:
        getattr(dialog, finish).click()
    assert not dialog.isVisible()
    assert repository.image_paths() == before
    assert not dialog.changed


def test_completed_edit_keeps_invalid_replacement_open(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completed edits validate immediately, retaining input and data after rejection."""
    add_image(repository, tmp_path / "old")
    before = repository.image_paths()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    dialog.replacement.setText(str(tmp_path / "absent"))
    dialog.replacement.editingFinished.emit()
    assert errors
    assert dialog.isVisible()
    assert dialog.index == 0
    assert repository.image_paths() == before
    dialog.close()


def test_partial_confirmation_cancellation_and_all_path_updates(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial recovery requires consent and relocates both matched and missing paths."""
    original = tmp_path / "old"
    add_image(repository, original, "one.png")
    add_image(repository, original, "two.png")
    replacement = destination(tmp_path, "new")
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    dialog.replacement.setText(str(replacement))
    questions = []
    replies = iter((QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes))

    def answer(*args):
        """Capture the explanation and choose Cancel before explicitly confirming."""
        questions.append(args[2])
        dialog.replacement.editingFinished.emit()  # Do not re-enter saving on focus changes.
        assert args[4] == QMessageBox.StandardButton.Cancel
        return next(replies)

    monkeypatch.setattr(QMessageBox, "question", answer)
    before = repository.image_paths()
    dialog.replacement.editingFinished.emit()
    assert dialog.isVisible()
    assert not dialog.changed
    assert repository.image_paths() == before
    dialog.replacement.editingFinished.emit()
    assert dialog.isVisible()
    assert dialog.changed
    dialog.done_button.click()
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert "1 of the 2 expected images" in questions[0]
    assert "all 2 images, including those still missing" in questions[0]
    assert set(repository.image_paths().values()) == {
        str(replacement / "one.png"),
        str(replacement / "two.png"),
    }


def test_database_failure_keeps_current_candidate_and_paths(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed transaction leaves the dialog available for correction or skipping."""
    original = tmp_path / "old"
    for name in ("one.png", "two.png"):
        add_image(repository, original, name)
    replacement = destination(tmp_path, "new", ("one.png", "two.png"))
    add_image(repository, replacement, "two.png")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    before = repository.image_paths()
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    dialog.replacement.setText(str(replacement))
    dialog.replacement.editingFinished.emit()
    assert errors and "No paths were updated" in errors[0]
    assert dialog.isVisible()
    assert dialog.index == 0
    assert not dialog.changed
    assert repository.image_paths() == before
    dialog.skip.click()


def test_browse_saves_mapping_immediately_without_advancing(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling browse preserves data; selecting a matching folder saves it immediately."""
    add_image(repository, tmp_path / "a")
    add_image(repository, tmp_path / "b")
    replacement = destination(tmp_path, "new")
    dialog = FolderMappingDialog(repository, discover_missing_folders(repository).candidates)
    dialog.show()
    before = repository.image_paths()
    original_label = dialog.original_path.text()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")
    dialog.browse.click()
    assert repository.image_paths() == before
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(replacement))
    dialog.browse.click()
    assert dialog.replacement.text() == str(replacement)
    assert dialog.original_path.text() == original_label
    assert dialog.selections[0].status is MappingStatus.CONFIRMED
    assert not dialog.skip.isEnabled()
    assert dialog.index == 0 and dialog.isVisible()
    dialog.next.click()
    assert dialog.skip.isEnabled()
    dialog.back.click()
    assert not dialog.skip.isEnabled()
    assert dialog.replacement.isReadOnly()
    assert not dialog.browse.isEnabled()
    dialog.done_button.click()
    assert not dialog.isVisible() and dialog.changed
    assert set(repository.image_paths().values()) == {
        str(replacement / "one.png"),
        str(tmp_path / "b" / "one.png"),
    }


def test_tools_command_runs_fresh_check_and_refreshes_indicators(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual recovery makes saved tags, flags and species filters visible immediately."""
    original, replacement = tmp_path / "old", tmp_path / "new"
    replacement.mkdir()
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    image.save(str(replacement / "one.png"))
    add_image(repository, original)
    repository.create_pending(original / "one.png", DAY, 3, 4)
    window = MainWindow(repository)
    window.open_folder(replacement)
    window.filtered_species = {repository.species()[0].id}
    window.apply_species_filters()
    assert window.files.isRowHidden(0)
    dialogs = []

    def map_folder(dialog: FolderMappingDialog) -> int:
        """Confirm the selected destination as an interactive user would."""
        dialogs.append(dialog)
        dialog.replacement.setText(str(replacement))
        dialog.replacement.editingFinished.emit()
        dialog.done_button.click()
        return dialog.result()

    monkeypatch.setattr(FolderMappingDialog, "exec", map_folder)
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    tools = next(action.menu() for action in window.menuBar().actions() if action.text() == "Tools")
    action = next(action for action in tools.actions() if action.text() == "Check Image Paths")
    action.trigger()
    assert len(dialogs) == 1
    assert not window.files.isRowHidden(0)
    assert not window.files.item(0, 0).icon().isNull()
    assert not window.files.item(0, 1).icon().isNull()
    window.files.selectRow(0)
    assert len(window.annotations) == len(window.pending) == 1
    action.trigger()
    assert len(dialogs) == 1
    assert messages == ["All image folders referenced by ReefTag were found."]
    window.close()


def test_check_database_error_is_nonfatal(
    application: QApplication, repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report a discovery failure and return control to startup or the calling window."""

    def fail_read():
        """Simulate a database read failure."""
        raise sqlite3.OperationalError("database unavailable")

    errors = []
    monkeypatch.setattr(repository, "image_paths", fail_read)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    assert not check_image_paths(repository)
    assert errors == ["database unavailable"]


@pytest.mark.parametrize("missing", [False, True])
def test_startup_checks_before_normal_window_and_skipping_continues(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    """Run the real startup entry point, skipping recovery and entering normal operation."""
    import reef_tag.__main__ as startup

    database = tmp_path / "startup.sqlite3"
    connection = connect(database)
    old = tmp_path / "old"
    if not missing:
        old.mkdir()
    add_image(Repository(connection), old)
    connection.close()
    events = []
    windows = []

    def skip_mapping(dialog: FolderMappingDialog) -> int:
        """Leave the missing folder unresolved during automatic recovery."""
        events.append("mapping")
        dialog.done_button.click()
        return dialog.result()

    def normal_window(repository: Repository) -> MainWindow:
        """Verify recovery has already run before normal session restoration."""
        events.append("window")
        window = MainWindow(repository)
        windows.append(window)
        return window

    monkeypatch.setattr(FolderMappingDialog, "exec", skip_mapping)
    monkeypatch.setattr(startup, "QApplication", lambda args: application)
    monkeypatch.setattr(application, "exec", lambda: 0)
    monkeypatch.setattr(startup, "database_path", lambda: database)
    monkeypatch.setattr(startup, "MainWindow", normal_window)
    assert startup.main() == 0
    assert events == (["mapping", "window"] if missing else ["window"])
    windows[0].close()
    connection = connect(database)
    assert list(Repository(connection).image_paths().values()) == [str(old / "one.png")]
    connection.close()


def test_file_removed_after_listing_is_reported(
    application: QApplication,
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing photographs fail gracefully without losing their saved identifications."""
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    path = tmp_path / "one.png"
    image.save(str(path))
    add_image(repository, tmp_path)
    window = MainWindow(repository)
    window.open_folder(tmp_path)
    path.unlink()
    errors = []
    monkeypatch.setattr(window, "report_error", errors.append)
    window.files.selectRow(0)
    assert errors and "Cannot load one.png" in errors[0]
    assert window.current_path is None
    assert len(repository.identifications(path)) == 1
    window.close()
