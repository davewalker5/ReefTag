"""Folder management and shared startup/manual integrity checks."""

import logging
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reef_tag.folder_mapping import FolderCandidate, discover_missing_folders, validate_replacement
from reef_tag.preferences import Preferences
from reef_tag.repositories import Repository

LOGGER = logging.getLogger(__name__)


def pick_folder_date(parent: QWidget, folder: Path, initial: date) -> date | None:
    """Return a selected default date, or None when the picker is cancelled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Default Date — {folder}")
    layout = QVBoxLayout(dialog)
    picker = QDateEdit(QDate(initial.year, initial.month, initial.day))
    picker.setCalendarPopup(True)
    picker.setDisplayFormat("yyyy-MM-dd")
    layout.addWidget(picker)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return picker.date().toPython()
    return None


class FolderManagementDialog(QDialog):
    """Show all folder defaults and file availability, persisting each accepted edit."""

    def __init__(
        self,
        repository: Repository,
        parent: QWidget | None = None,
        current_folder: Path | None = None,
    ) -> None:
        """Build and validate the folder table, optionally marking the active directory."""
        super().__init__(parent)
        self.repository = repository
        self.current_folder = current_folder.resolve() if current_folder is not None else None
        self.changed = False
        self.setWindowTitle("Folder Management")
        self.setModal(True)
        self.resize(1100, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Path", "Date", "Images", "Missing", ""])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.edit_cell)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        """Reload every saved folder and check each directly referenced photograph."""
        self.folders = self.repository.folders()
        self.table.setRowCount(len(self.folders))
        for row, folder in enumerate(self.folders):
            exists = folder.path.is_absolute() and folder.path.is_dir()
            matched = sum(Path(path).is_file() for path in folder.images.values()) if exists else 0
            total = len(folder.images)
            if exists and matched == total:
                symbol, color, description = "✓", "#388e3c", "All images found"
            elif matched:
                symbol, color, description = "?", "#b58900", "Some images missing"
            else:
                symbol, color, description = "✱", "#d32f2f", "Folder or all images missing"
            values = [
                symbol,
                str(folder.path),
                folder.default_date.isoformat(),
                str(total),
                str(total - matched),
                "←" if folder.path == self.current_folder else "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 5):
                    item.setForeground(QColor(color if column == 0 else "#388e3c"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    font = item.font()
                    font.setPointSize(20)
                    item.setFont(font)
                item.setToolTip(description if column == 0 else value)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()

    def edit_cell(self, row: int, column: int) -> None:
        """Choose a replacement path or date, leaving cancelled or failed edits unchanged."""
        folder = self.folders[row]
        try:
            if column == 1:
                selection = QFileDialog.getExistingDirectory(
                    self, "Select replacement image folder", str(folder.path)
                )
                if not selection:
                    return
                # Empty folders have no filenames to match, but still require a real directory.
                if folder.images:
                    replacement = validate_replacement(
                        FolderCandidate(folder.path, folder.images), selection
                    )
                    destination = replacement.directory
                    if replacement.matched < replacement.total:
                        answer = QMessageBox.question(
                            self,
                            "Some images were not found",
                            f"The selected folder contains {replacement.matched} of the "
                            f"{replacement.total} expected images.\n\n"
                            f"Update the paths for all {replacement.total} images, including "
                            "those still missing?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                            QMessageBox.StandardButton.Cancel,
                        )
                        if answer != QMessageBox.StandardButton.Yes:
                            return
                else:
                    destination = Path(selection).expanduser().resolve(strict=True)
                    if not destination.is_dir():
                        raise ValueError("Select an existing replacement folder.")
                self.repository.relocate_folder(folder, destination)
                if folder.path == self.current_folder:
                    self.current_folder = destination
            elif column == 2:
                selected = pick_folder_date(self, folder.path, folder.default_date)
                if selected is None:
                    return
                self.repository.save_folder_date(folder.path, selected)
            else:
                return
            self.changed = True
            self.refresh()
        except (OSError, ValueError, sqlite3.Error) as error:
            LOGGER.warning("Cannot update folder %s: %s", folder.path, error)
            QMessageBox.warning(self, "Cannot update folder", str(error))


def check_image_paths(
    repository: Repository,
    parent: QWidget | None = None,
    *,
    manual: bool = False,
    preferences: Preferences | None = None,
    on_folder_changed: Callable[[Path], None] | None = None,
) -> bool:
    """Preserve directory integrity discovery and open management once for all folders.

    :return: Whether the user saved any changes before closing management.
    """
    try:
        result = discover_missing_folders(repository)
        missing = bool(result.candidates) or any(
            not folder.path.is_dir() for folder in repository.folders()
        )
        if result.issues:
            QMessageBox.warning(
                parent,
                "Some image paths could not be checked",
                "These paths were left unchanged:\n\n" + "\n".join(result.issues),
            )
        if not missing:
            if manual and not result.issues:
                QMessageBox.information(
                    parent,
                    "Check Image Paths",
                    "All image folders referenced by ReefTag were found.",
                )
            return False
        dialog = FolderManagementDialog(repository, parent, getattr(parent, "folder", None))
        dialog.exec()
        if dialog.changed and dialog.current_folder is not None and on_folder_changed is not None:
            on_folder_changed(dialog.current_folder)
        return dialog.changed
    except sqlite3.Error as error:
        LOGGER.exception("Cannot check image paths")
        QMessageBox.critical(parent, "Cannot check image paths", str(error))
        return False
