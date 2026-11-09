"""Read-only, database-wide species search using the shared image preview."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reef_tag.models import SpeciesImage
from reef_tag.repositories import Repository
from reef_tag.ui.image_view import MAX_BRIGHTNESS, MAX_ZOOM, MIN_BRIGHTNESS, MIN_ZOOM, ImageView


class SpeciesSearchDialog(QDialog):
    """Keep search, selection and sorting intact while images open externally."""

    def __init__(self, repository: Repository, parent: QWidget) -> None:
        """Build a searchable selector, results and an annotation-only preview."""
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("Species Search")
        self.resize(1200, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Species"))
        self.selector = QComboBox()
        self.selector.setEditable(True)
        self.selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.selector.addItem("Select a species…", None)
        for species in repository.identified_species():
            self.selector.addItem(f"{species.common_name} — {species.scientific_name}", species.id)
        completer = self.selector.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        layout.addWidget(self.selector)
        self.summary = QLabel(
            "Select a species to find images."
            if self.selector.count() > 1
            else "No species with recorded identifications."
        )
        layout.addWidget(self.summary)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(["Image", "Date", "Count"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setAlternatingRowColors(True)
        self.results.verticalHeader().hide()
        header = self.results.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        self.results.setSortingEnabled(True)
        splitter.addWidget(self.results)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        self.preview = ImageView()
        self.preview.empty_message = "Select a search result"
        preview_layout.addWidget(self.preview, 1)
        self.preview_status = QLabel("Select a search result")
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        preview_layout.addWidget(QLabel("Zoom"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(MIN_ZOOM, MAX_ZOOM)
        self.zoom.setValue(MIN_ZOOM)
        self.zoom.valueChanged.connect(self.preview.set_zoom)
        preview_layout.addWidget(self.zoom)
        preview_layout.addWidget(QLabel("Brightness"))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(MIN_BRIGHTNESS, MAX_BRIGHTNESS)
        self.brightness.setValue(0)
        self.brightness.valueChanged.connect(self.preview.set_brightness)
        preview_layout.addWidget(self.brightness)
        splitter.addWidget(preview_panel)
        splitter.setSizes([600, 600])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.selector.currentIndexChanged.connect(self.search)
        self.results.itemSelectionChanged.connect(self.show_image)
        self.results.cellDoubleClicked.connect(self.open_image)

    def search(self) -> None:
        """Replace results for the selected ID while retaining the active sort order."""
        self.results.setRowCount(0)
        self.clear_preview()
        species_id = self.selector.currentData()
        if species_id is None:
            self.summary.setText("Select a species to find images.")
            return
        try:
            images = self.repository.images_for_species(species_id)
        except sqlite3.Error as error:
            self.summary.setText(f"Could not search images: {error}")
            return
        self.results.setSortingEnabled(False)
        self.results.setRowCount(len(images))
        for row, image in enumerate(images):
            name = QTableWidgetItem(Path(image.path).name)
            name.setData(Qt.ItemDataRole.UserRole, image)
            name.setToolTip(image.path)
            self.results.setItem(row, 0, name)
            self.results.setItem(row, 1, QTableWidgetItem(image.footage_date))
            count = QTableWidgetItem()
            count.setData(Qt.ItemDataRole.DisplayRole, image.count)
            self.results.setItem(row, 2, count)
        self.results.setSortingEnabled(True)
        self.summary.setText(
            f"{len(images)} image{'s' if len(images) != 1 else ''} found"
            if images
            else "No matching images found."
        )

    def selected_image(self) -> SpeciesImage | None:
        """Return the selected stored record, independent of table sorting."""
        rows = self.results.selectionModel().selectedRows()
        return self.results.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def clear_preview(self) -> None:
        """Remove stale markers and image content after selection changes."""
        self.preview.pending = []
        self.preview.set_image(QPixmap(), [])
        self.preview_status.setText("Select a search result")

    def show_image(self) -> None:
        """Preview only the selected species' markers; handle unavailable files inline."""
        self.clear_preview()
        image = self.selected_image()
        if image is None:
            return
        pixmap = QPixmap(image.path)
        if pixmap.isNull():
            self.preview_status.setText(f"Image missing or unreadable: {image.path}")
            return
        try:
            annotations = [
                annotation
                for annotation in self.repository.identifications(Path(image.path))
                if annotation.species.id == self.selector.currentData()
            ]
        except sqlite3.Error as error:
            self.preview_status.setText(f"Could not load identifications: {error}")
            return
        self.preview.set_image(pixmap, annotations)
        self.preview_status.setText(image.path)

    def open_image(self, row: int, column: int) -> None:
        """Open the original source in its registered viewer without losing search state."""
        image = self.results.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not Path(image.path).is_file():
            QMessageBox.warning(self, "Image unavailable", f"Image file not found: {image.path}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(image.path)):
            QMessageBox.warning(
                self, "Image unavailable", "Could not open the native image viewer."
            )
