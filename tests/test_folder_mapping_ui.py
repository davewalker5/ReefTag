"""Folder management status, immediate edits and startup/manual integration."""

import os
import sqlite3
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from reef_tag.db import connect
from reef_tag.repositories import Repository
from reef_tag.ui.folder_editor_dialog import FolderEditorDialog
from reef_tag.ui.folder_mapping_dialog import FolderManagementDialog, check_image_paths
from reef_tag.ui.main_window import MainWindow

DAY = date(2026, 10, 13)


@pytest.fixture(scope="session")
def application():
    """Share one offscreen Qt application."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repository(tmp_path: Path):
    """Keep edits in an isolated database."""
    connection = connect(tmp_path / "mapping.sqlite3")
    yield Repository(connection)
    connection.close()


def add_image(repository: Repository, directory: Path, filename: str = "one.png") -> None:
    """Record an image independently of its filesystem availability."""
    repository.create_pending(directory / filename, DAY, 1, 2)


def destination(tmp_path: Path, names: tuple[str, ...] = ("one.png",)) -> Path:
    """Make a replacement containing the requested filenames."""
    folder = tmp_path / "new"
    folder.mkdir()
    for name in names:
        (folder / name).touch()
    return folder


def choose_and_save(editor: FolderEditorDialog) -> int:
    """Choose a replacement and commit only a successfully staged path."""
    editor.choose_folder()
    if editor.destination != editor.folder.path:
        editor.accept()
    return editor.result()


def test_table_status_counts_and_current_folder(application, repository, tmp_path):
    """Include all saved folders and distinguish all, some and no matching images."""
    for name in ("all", "some", "none", "gone", "empty"):
        folder = tmp_path / name
        if name != "gone":
            folder.mkdir()
        repository.save_folder_date(folder, DAY)
        if name != "empty":
            for filename in ("one.png", "two.png"):
                add_image(repository, folder, filename)
                if name == "all" or (name == "some" and filename == "one.png"):
                    (folder / filename).touch()
    dialog = FolderManagementDialog(repository, current_folder=tmp_path / "some")
    rows = {
        folder.path.name: [dialog.table.item(row, col).text() for col in range(7)]
        for row, folder in enumerate(dialog.folders)
    }
    assert rows["all"][0] == rows["empty"][0] == "✓"
    assert rows["some"][0] == "?"
    assert rows["none"][0] == rows["gone"][0] == "✱"
    assert rows["some"][3:] == [DAY.isoformat(), "2", "1", "←"]
    assert rows["gone"][4:6] == ["2", "2"]
    dialog.close()


@pytest.mark.parametrize(
    "answer", [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes]
)
def test_partial_mapping_confirmation(application, repository, tmp_path, monkeypatch, answer):
    """Cancelled partial mappings preserve data; confirmed mappings move every image."""
    original = tmp_path / "old"
    add_image(repository, original)
    add_image(repository, original, "two.png")
    replacement = destination(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(replacement))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer)
    dialog = FolderManagementDialog(repository, current_folder=original)
    monkeypatch.setattr(FolderEditorDialog, "exec", choose_and_save)
    dialog.edit_cell(0, 1)
    confirmed = answer == QMessageBox.StandardButton.Yes
    assert dialog.changed == confirmed
    expected = replacement if confirmed else original
    assert {Path(path).parent for path in repository.image_paths().values()} == {expected}
    assert dialog.current_folder == expected
    assert repository.folder_date(expected) == DAY
    assert dialog.table.item(0, 5).text() == ("1" if confirmed else "2")
    dialog.close()


@pytest.mark.parametrize("selection", ["cancel", "invalid", "zero", "collision", "success"])
def test_mapping_outcomes(application, repository, tmp_path, monkeypatch, selection):
    """Only a validated, collision-free selection commits, preserving annotations."""
    old = tmp_path / "old"
    add_image(repository, old)
    replacement = destination(tmp_path, () if selection == "zero" else ("one.png",))
    if selection == "collision":
        add_image(repository, replacement)
    value = (
        ""
        if selection == "cancel"
        else str(tmp_path / "absent" if selection == "invalid" else replacement)
    )
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: value)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    before = repository.image_paths()
    dialog = FolderManagementDialog(repository)
    row = next(i for i, folder in enumerate(dialog.folders) if folder.path == old)
    monkeypatch.setattr(FolderEditorDialog, "exec", choose_and_save)
    dialog.edit_cell(row, 1)
    assert dialog.changed == (selection == "success")
    if selection == "success":
        assert repository.folder_date(old) is None
        assert len(repository.pending_identifications(replacement / "one.png")) == 1
    else:
        assert repository.image_paths() == before
        assert bool(errors) == (selection != "cancel")
    dialog.close()


def test_empty_folder_move_and_date_edit(application, repository, tmp_path, monkeypatch):
    """Folders with no images remain editable, and date writes persist immediately."""
    old = tmp_path / "old"
    repository.save_folder_date(old, DAY)
    replacement = destination(tmp_path, ())
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(replacement))
    dialog = FolderManagementDialog(repository)
    monkeypatch.setattr(FolderEditorDialog, "exec", choose_and_save)
    dialog.edit_cell(0, 1)
    assert repository.folder_date(old) is None
    second = date(2026, 11, 1)

    def save_date(editor):
        """Set the date and save through the real editor."""
        editor.default_date.setDate(QDate(second.year, second.month, second.day))
        editor.accept()
        return editor.result()

    monkeypatch.setattr(FolderEditorDialog, "exec", save_date)
    dialog.edit_cell(0, 3)
    assert repository.folder_date(replacement) == second
    monkeypatch.setattr(
        FolderEditorDialog, "exec", lambda editor: editor.reject() or editor.result()
    )
    dialog.edit_cell(0, 3)
    assert repository.folder_date(replacement) == second
    dialog.close()


def test_menu_and_active_default_refresh(application, repository, tmp_path, monkeypatch):
    """Management is always enabled and date changes reach the active footage default."""
    window = MainWindow(repository)
    tools = next(action.menu() for action in window.menuBar().actions() if action.text() == "Tools")
    assert [action.text() for action in tools.actions()] == [
        "Manage Categories",
        "Manage Folders",
        "Manage Locations",
        "",
        "Check Image Paths",
    ]
    assert tools.actions()[3].isSeparator()
    assert window.manage_folders_action.isEnabled()
    repository.save_folder_date(tmp_path, DAY)
    window.open_folder(tmp_path)
    second = date(2026, 11, 1)

    def save_date(editor):
        """Save the new default through the folder editor."""
        editor.default_date.setDate(QDate(second.year, second.month, second.day))
        editor.accept()
        return editor.result()

    monkeypatch.setattr(FolderEditorDialog, "exec", save_date)

    def edit(dialog):
        """Save a date through the actual table handler."""
        dialog.edit_cell(0, 2)
        return 0

    monkeypatch.setattr(FolderManagementDialog, "exec", edit)
    window.manage_folders_action.trigger()
    assert window.folder_default_date == second
    assert not hasattr(window, "footage_date")
    window.close()


@pytest.mark.parametrize("missing", [False, True])
def test_startup_check_and_manual_success(application, repository, tmp_path, monkeypatch, missing):
    """Keep healthy startup silent and show one management window for missing folders."""
    add_image(repository, tmp_path / "gone" if missing else tmp_path)
    dialogs, messages = [], []
    monkeypatch.setattr(FolderManagementDialog, "exec", lambda dialog: dialogs.append(dialog))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    assert not check_image_paths(repository)
    assert len(dialogs) == int(missing)
    assert not messages
    assert not check_image_paths(repository, manual=True)
    assert len(dialogs) == 2 * int(missing)
    assert bool(messages) != missing


def test_check_database_error_is_nonfatal(application, repository, monkeypatch):
    """Report discovery errors without blocking application startup."""

    def fail_read():
        """Simulate an unavailable database."""
        raise sqlite3.OperationalError("database unavailable")

    errors = []
    monkeypatch.setattr(repository, "image_paths", fail_read)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    assert not check_image_paths(repository)
    assert errors == ["database unavailable"]


def test_merge_preserves_destination_default_and_rejects_stale_snapshot(repository, tmp_path):
    """Folder merges preserve existing defaults and detect intervening image changes."""
    old, new = tmp_path / "old", tmp_path / "new"
    add_image(repository, old)
    other_day = date(2026, 10, 15)
    repository.save_folder_date(new, other_day)
    folder = next(folder for folder in repository.folders() if folder.path == old)
    add_image(repository, old, "two.png")
    before = repository.image_paths()
    with pytest.raises(ValueError, match="folder changed"):
        repository.relocate_folder(folder, new)
    assert repository.image_paths() == before
    folder = next(folder for folder in repository.folders() if folder.path == old)
    repository.relocate_folder(folder, new)
    assert repository.folder_date(new) == other_day
    assert repository.folder_date(old) is None
    assert len(repository.pending_identifications(new / "one.png")) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_startup_checks_before_main_window(application, tmp_path, monkeypatch, missing):
    """A missing directory opens management before normal session restoration."""
    import reef_tag.__main__ as startup

    database = tmp_path / "startup.sqlite3"
    connection = connect(database)
    folder = tmp_path / "old"
    if not missing:
        folder.mkdir()
    add_image(Repository(connection), folder)
    connection.close()
    events, windows = [], []

    def close_management(dialog):
        """Leave paths unresolved and let startup continue."""
        events.append("management")
        dialog.accept()
        return dialog.result()

    def main_window(repository):
        """Record when startup constructs the normal window."""
        events.append("window")
        window = MainWindow(repository)
        windows.append(window)
        return window

    monkeypatch.setattr(FolderManagementDialog, "exec", close_management)
    monkeypatch.setattr(startup, "QApplication", lambda args: application)
    monkeypatch.setattr(application, "exec", lambda: 0)
    monkeypatch.setattr(startup, "database_path", lambda: database)
    monkeypatch.setattr(startup, "MainWindow", main_window)
    assert startup.main() == 0
    assert events == (["management", "window"] if missing else ["window"])
    windows[0].close()
