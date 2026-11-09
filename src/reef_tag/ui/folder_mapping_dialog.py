"""Modal, user-confirmed recovery of missing image directories."""

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reef_tag.folder_mapping import FolderCandidate, discover_missing_folders, validate_replacement
from reef_tag.preferences import Preferences
from reef_tag.repositories import Repository

LOGGER = logging.getLogger(__name__)


class MappingStatus(Enum):
    """An individual candidate's progress within the current dialog session."""

    UNRESOLVED = auto()
    SKIPPED = auto()
    CONFIRMED = auto()


@dataclass
class MappingSelection:
    """Retain a candidate's input and confirmed destination while navigating."""

    candidate: FolderCandidate
    selection: str
    status: MappingStatus = MappingStatus.UNRESOLVED


class FolderMappingDialog(QDialog):
    """Present missing folders one at a time, saving replacements when selected."""

    def __init__(
        self,
        repository: Repository,
        candidates: tuple[FolderCandidate, ...],
        parent: QWidget | None = None,
        preferences: Preferences | None = None,
    ) -> None:
        """Build the wireframe layout without validating or applying any mapping.

        :param repository: Database used for atomic path updates.
        :param candidates: Non-empty, ordered list discovered for this session.
        :param parent: Owning application window, or None during startup.
        :raises ValueError: If there are no candidates to display.
        """
        if not candidates:
            raise ValueError("Folder Mapping requires at least one missing folder.")
        super().__init__(parent)
        self.repository = repository
        self.preferences = preferences if preferences is not None else Preferences()
        self.selections = [MappingSelection(item, str(item.directory)) for item in candidates]
        self.index = 0
        self.changed = False
        self._confirming = False
        self.setWindowTitle("Folder Mapping")
        self.setModal(True)
        self.resize(760, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(QLabel("The following folder can no longer be found:"))
        self.original_path = QLabel()
        self.original_path.setTextFormat(Qt.TextFormat.PlainText)
        self.original_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.original_path.setWordWrap(True)
        layout.addWidget(self.original_path)
        path_controls = QHBoxLayout()
        self.replacement = QLineEdit()
        self.replacement.setAccessibleName("Replacement folder")
        self.replacement.editingFinished.connect(self.save_selection)
        self.browse = QPushButton("...")
        self.browse.setAccessibleName("Browse for replacement folder")
        self.browse.setFixedWidth(44)
        self.browse.clicked.connect(self.browse_folder)
        path_controls.addWidget(self.replacement, 1)
        path_controls.addWidget(self.browse)
        layout.addLayout(path_controls)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.back = QPushButton("<< Back")
        self.skip = QPushButton("Skip")
        self.done_button = QPushButton("Done")
        self.next = QPushButton("Next >>")
        self.back.clicked.connect(self.go_back)
        self.skip.clicked.connect(self.skip_folder)
        self.done_button.clicked.connect(self.accept)
        self.next.clicked.connect(self.go_next)
        buttons.addStretch()
        for button in (self.back, self.next, self.skip, self.done_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.show_candidate()

    def show_candidate(self) -> None:
        """Display retained input while keeping the original missing path visible."""
        state = self.selections[self.index]
        self.original_path.setText(str(state.candidate.directory))
        self.replacement.setText(state.selection)
        # A confirmed mapping is final for this session; Back never applies it again.
        confirmed = state.status is MappingStatus.CONFIRMED
        self.replacement.setReadOnly(confirmed)
        self.browse.setEnabled(not confirmed)
        self.skip.setEnabled(not confirmed)
        count = len(state.candidate.images)
        images = "image" if count == 1 else "images"
        if confirmed:
            self.explanation.setText(f"The paths for {count} {images} were updated to this folder.")
        else:
            self.explanation.setText(
                f"It contains {count} {images} referenced by ReefTag. "
                "Please select its new location, or skip this folder for now."
            )
        self.back.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(self.selections) - 1)

    def remember_selection(self) -> None:
        """Retain edits before moving to another candidate without applying them."""
        self.selections[self.index].selection = self.replacement.text()

    def browse_folder(self) -> None:
        """Choose a replacement with the platform's standard directory picker."""
        selection = QFileDialog.getExistingDirectory(
            self, "Select replacement image folder", self.replacement.text()
        )
        if selection:
            self.replacement.setText(selection)
            self.save_selection()

    def go_back(self) -> None:
        """Return to the previous candidate, preserving edits and committed mappings."""
        if self.index == 0:
            return
        self.remember_selection()
        self.index -= 1
        self.show_candidate()

    def advance(self) -> None:
        """Continue in order, closing after the final candidate."""
        if self.index == len(self.selections) - 1:
            self.accept()
            return
        self.index += 1
        self.show_candidate()

    def go_next(self) -> None:
        """Retain edits and navigate forward without validating or saving a mapping."""
        if self.index == len(self.selections) - 1:
            return
        self.remember_selection()
        self.index += 1
        self.show_candidate()

    def skip_folder(self) -> None:
        """Leave database paths unchanged and retain input for an explicit Back visit."""
        self.remember_selection()
        state = self.selections[self.index]
        if state.status is not MappingStatus.CONFIRMED:
            state.status = MappingStatus.SKIPPED
        self.advance()

    def save_selection(self) -> None:
        """Save completed text edits or a browsed folder without recursive focus callbacks."""
        if self._confirming:
            return
        self._confirming = True
        try:
            self.confirm_folder()
        finally:
            self._confirming = False

    def confirm_folder(self) -> None:
        """Validate and atomically confirm a replacement, keeping errors on this candidate."""
        self.remember_selection()
        state = self.selections[self.index]
        if state.status is MappingStatus.CONFIRMED or state.selection == str(
            state.candidate.directory
        ):
            return
        try:
            replacement = validate_replacement(state.candidate, state.selection)
            if replacement.matched < replacement.total:
                answer = QMessageBox.question(
                    self,
                    "Some images were not found",
                    f"The selected folder contains {replacement.matched} of the "
                    f"{replacement.total} expected images.\n\n"
                    f"{replacement.total - replacement.matched} images could not be found.\n\n"
                    f"Update the paths for all {replacement.total} images, including those "
                    "still missing?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self.repository.update_image_paths(replacement.changes)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self, "Cannot map folder", f"{state.candidate.directory}\n\n{error}"
            )
            return
        except sqlite3.Error as error:
            LOGGER.exception("Cannot map image folder %s", state.candidate.directory)
            QMessageBox.critical(
                self,
                "Cannot map folder",
                f"No paths were updated for {state.candidate.directory}.\n\n"
                f"The replacement may already contain recorded images, or the database "
                f"could not be updated.\n\n{error}",
            )
            return
        state.status = MappingStatus.CONFIRMED
        state.selection = str(replacement.directory)
        self.changed = True
        self.show_candidate()


def check_image_paths(
    repository: Repository,
    parent: QWidget | None = None,
    *,
    manual: bool = False,
    preferences: Preferences | None = None,
) -> bool:
    """Run the shared startup/manual check without making recovery failures fatal.

    :param repository: Source of stored paths and destination of confirmed updates.
    :param parent: Parent for modal messages and the mapping dialog.
    :param manual: Show a success message only when explicitly requested from Tools.
    :return: Whether at least one mapping was committed, including before Done or window closure.
    """
    try:
        result = discover_missing_folders(repository)
    except sqlite3.Error as error:
        LOGGER.exception("Cannot check image paths")
        QMessageBox.critical(parent, "Cannot check image paths", str(error))
        return False
    if result.issues:
        for issue in result.issues:
            LOGGER.warning("%s", issue)
        QMessageBox.warning(
            parent,
            "Some image paths could not be checked",
            "These paths were left unchanged:\n\n" + "\n".join(result.issues),
        )
    if not result.candidates:
        if manual and not result.issues:
            QMessageBox.information(
                parent, "Check Image Paths", "All image folders referenced by ReefTag were found."
            )
        return False
    dialog = FolderMappingDialog(repository, result.candidates, parent, preferences)
    dialog.exec()
    return dialog.changed
