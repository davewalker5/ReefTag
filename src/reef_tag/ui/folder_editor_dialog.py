"""Edit folder metadata and stage validated relocations until OK is selected."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reef_tag.folder_mapping import FolderCandidate, validate_replacement
from reef_tag.models import Folder
from reef_tag.repositories import Repository


class FolderEditorDialog(QDialog):
    """Edit path, location and default date as a single cancellable operation."""

    def __init__(
        self,
        repository: Repository,
        folder: Folder,
        parent: QWidget | None = None,
    ) -> None:
        """Populate the editor from a folder snapshot and the current location catalogue."""
        super().__init__(parent)
        self.repository = repository
        self.folder = folder
        self.destination = folder.path
        self.setWindowTitle("Folder Editor")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        form = QGridLayout()
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)
        self.path = QLineEdit(str(folder.path))
        self.path.setReadOnly(True)
        self.browse = QPushButton("...")
        self.browse.setToolTip("Select replacement image folder")
        self.browse.setAccessibleName("Select replacement image folder")
        self.browse.clicked.connect(self.choose_folder)
        form.addWidget(self.path, 0, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        form.addWidget(self.browse, 0, 2, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.location = QComboBox()
        self.location.addItem("No location", None)
        for location in repository.locations():
            self.location.addItem(location.name, location.id)
            self.location.setItemData(
                self.location.count() - 1,
                f"{location.region}, {location.country}",
                Qt.ItemDataRole.ToolTipRole,
            )
        self.location.setCurrentIndex(max(0, self.location.findData(folder.location_id)))
        form.addWidget(self.location, 1, 1, 1, 2, Qt.AlignmentFlag.AlignVCenter)
        value = folder.default_date
        self.default_date = QDateEdit(QDate(value.year, value.month, value.day))
        self.default_date.setCalendarPopup(True)
        self.default_date.setDisplayFormat("yyyy-MM-dd")
        form.addWidget(self.default_date, 2, 1, 1, 2, Qt.AlignmentFlag.AlignVCenter)
        # Equal row heights keep native button padding from enlarging only the path row.
        fields = (self.path, self.browse, self.location, self.default_date)
        for field in fields:
            field.ensurePolished()
        row_height = max(field.sizeHint().height() for field in fields)
        for row, title in enumerate(("Path", "Location", "Default Date")):
            form.addWidget(QLabel(title), row, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
            form.setRowMinimumHeight(row, row_height)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_folder(self) -> None:
        """Validate a selected folder and stage it without writing to the database."""
        selection = QFileDialog.getExistingDirectory(
            self, "Select replacement image folder", str(self.destination)
        )
        if not selection:
            return
        try:
            if self.folder.images:
                replacement = validate_replacement(
                    FolderCandidate(self.folder.path, self.folder.images), selection
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
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot update folder", str(error))
            return
        self.destination = destination
        self.path.setText(str(destination))

    def accept(self) -> None:
        """Save every staged change atomically, keeping failed edits open for correction."""
        try:
            self.repository.save_folder(
                self.folder,
                self.destination,
                self.default_date.date().toPython(),
                self.location.currentData(),
            )
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Cannot update folder", str(error))
            return
        super().accept()
