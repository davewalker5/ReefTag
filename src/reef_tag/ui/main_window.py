"""Folder browsing, footage dates and annotation workflow coordination."""

import logging
import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reef_tag.files import discover_images
from reef_tag.models import Identification, PendingIdentification
from reef_tag.preferences import Preferences, PreviewSettings
from reef_tag.repositories import Repository, image_identity
from reef_tag.ui.category_dialog import CategoriesDialog, SpeciesMaintenanceDialog
from reef_tag.ui.folder_mapping_dialog import check_image_paths
from reef_tag.ui.image_view import MAX_BRIGHTNESS, MAX_ZOOM, MIN_BRIGHTNESS, MIN_ZOOM, ImageView
from reef_tag.ui.species_dialog import SpeciesDialog

LOGGER = logging.getLogger(__name__)
ICON_PATH = Path(__file__).parents[1] / "resources" / "reeftag.png"


def make_table(headers: list[str]) -> QTableWidget:
    """Create a read-only row-selection table with stretching name columns."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    if headers[0] == "Position":
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    if headers[-1] == "Size (MiB)":
        table.horizontalHeader().setSectionResizeMode(
            len(headers) - 1, QHeaderView.ResizeMode.ResizeToContents
        )
    return table


def fill_table(table: QTableWidget, rows: list[list[str]]) -> None:
    """Replace table contents while preserving supplied deterministic order."""
    table.setRowCount(len(rows))
    for row_number, row in enumerate(rows):
        for column, value in enumerate(row):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(row_number, column, item)


class MainWindow(QMainWindow):
    """Coordinate the manual image identification workflow."""

    def __init__(self, repository: Repository, preferences: Preferences | None = None) -> None:
        """Build the two-column workspace and load the shared catalogue."""
        super().__init__()
        self.repository = repository
        self.preferences = preferences if preferences is not None else Preferences()
        self.folder: Path | None = None
        self.paths: list[Path] = []
        self.current_path: Path | None = None
        self.annotations: list[Identification] = []
        self.pending: list[PendingIdentification] = []
        self.filtered_species: set[int] = set()
        self.folder_default_date: date | None = None
        self.setWindowTitle(
            "ReefTag — Identify, annotate and catalogue fish in underwater photographs"
        )
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1250, 800)
        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction("Manage Categories").triggered.connect(self.edit_categories)
        self.set_default_date_action = tools_menu.addAction("Set Default Date")
        self.set_default_date_action.setEnabled(False)
        self.set_default_date_action.triggered.connect(self.set_default_date)
        check_paths = tools_menu.addAction("Check Image Paths")
        check_paths.triggered.connect(self.check_image_paths)
        splitter = QSplitter()
        self.setCentralWidget(splitter)
        left, right = QWidget(), QWidget()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([760, 490])
        workspace = QVBoxLayout(left)
        heading = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(
            QPixmap(str(ICON_PATH)).scaled(
                64,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        heading.addWidget(icon)
        title = QLabel(
            "<h1>ReefTag</h1>Identify, annotate and catalogue fish in underwater photographs"
        )
        heading.addWidget(title, 1)
        workspace.addLayout(heading)
        self.folder_text = QLineEdit()
        self.folder_text.setReadOnly(True)
        self.folder_text.setPlaceholderText("No folder selected")
        workspace.addWidget(self.folder_text)
        self.preview = ImageView()
        workspace.addWidget(self.preview, 1)
        self.brightness_controls = QWidget()
        preview_controls_layout = QHBoxLayout(self.brightness_controls)
        preview_controls_layout.setContentsMargins(0, 0, 0, 0)
        brightness_label = QLabel("Brightness")
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(MIN_BRIGHTNESS, MAX_BRIGHTNESS)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setAccessibleName("Preview brightness")
        self.brightness_slider.setToolTip("Adjust the preview only; original images are unchanged.")
        brightness_label.setBuddy(self.brightness_slider)
        self.brightness_value = QLabel("0")
        self.brightness_value.setMinimumWidth(36)
        self.brightness_reset = QPushButton("Reset")
        self.brightness_reset.clicked.connect(self.reset_preview)
        self.brightness_reset.setToolTip("Reset brightness, zoom and pan.")
        self.brightness_slider.valueChanged.connect(self.change_brightness)
        preview_controls_layout.addWidget(brightness_label)
        preview_controls_layout.addWidget(self.brightness_slider, 1)
        preview_controls_layout.addWidget(self.brightness_value)
        zoom_label = QLabel("Zoom")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(MIN_ZOOM, MAX_ZOOM)
        self.zoom_slider.setValue(MIN_ZOOM)
        self.zoom_slider.setAccessibleName("Preview zoom")
        self.zoom_slider.setToolTip("Zoom in from the fitted view. Right-click and drag to pan.")
        zoom_label.setBuddy(self.zoom_slider)
        self.zoom_value = QLabel("100%")
        self.zoom_slider.valueChanged.connect(self.change_zoom)
        preview_controls_layout.addWidget(zoom_label)
        preview_controls_layout.addWidget(self.zoom_slider, 1)
        preview_controls_layout.addWidget(self.zoom_value)
        preview_controls_layout.addWidget(self.brightness_reset)
        self.brightness_controls.setEnabled(False)
        workspace.addWidget(self.brightness_controls)
        controls = QHBoxLayout()
        choose = QPushButton("Choose Folder…")
        choose.clicked.connect(self.choose_folder)
        self.refresh = QPushButton("Refresh Folder")
        self.refresh.setEnabled(False)
        self.refresh.clicked.connect(self.refresh_folder)
        self.footage_date = QDateEdit(QDate.currentDate())
        self.footage_date.setCalendarPopup(True)
        self.footage_date.setDisplayFormat("dd/MM/yyyy")
        self.footage_date.setMinimumDate(QDate(1, 1, 1))
        self.footage_date.setSpecialValueText(" ")
        self.footage_date.setDate(self.footage_date.minimumDate())
        self.footage_date.setEnabled(False)
        self.footage_date.dateChanged.connect(self.change_date)
        footage_date_label = QLabel("Footage Date")
        footage_date_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for widget in (choose, self.refresh, footage_date_label, self.footage_date):
            controls.addWidget(widget)
        workspace.addLayout(controls)
        observations = QVBoxLayout(right)
        self.files = make_table(["", "", "Filename", "Size (MiB)"])
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.files.setColumnWidth(0, 28)
        self.files.horizontalHeaderItem(0).setToolTip("Images with saved fish identifications")
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.files.setColumnWidth(1, 28)
        self.files.horizontalHeaderItem(1).setToolTip("Click to toggle further examination")
        asterisk = QPixmap(20, 20)
        asterisk.fill(Qt.GlobalColor.transparent)
        painter = QPainter(asterisk)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("red"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # Fill the icon area instead of inheriting the small asterisk glyph's font margins.
        painter.drawLine(QPointF(10, 2), QPointF(10, 18))
        painter.drawLine(QPointF(3, 6), QPointF(17, 14))
        painter.drawLine(QPointF(3, 14), QPointF(17, 6))
        painter.end()
        self.examination_icon = QIcon(asterisk)
        self.files.cellClicked.connect(self.toggle_further_examination)
        self.tagged_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        self.files.itemSelectionChanged.connect(self.select_image)
        observations.addWidget(self.files, 1)
        self.tabs = QTabWidget()
        self.current = make_table(["Position", "Name", "Scientific Name"])
        self.catalogue = make_table(["Name", "Scientific Name", ""])
        self.catalogue.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.catalogue.setColumnWidth(2, 32)
        self.catalogue.horizontalHeaderItem(2).setToolTip(
            "Filter images by species; multiple filters match any selected species"
        )
        self.catalogue.cellClicked.connect(self.toggle_species_filter)
        self.catalogue.cellDoubleClicked.connect(self.edit_species)
        self.tabs.addTab(self.current, "Current Image")
        self.tabs.addTab(self.catalogue, "All Species")
        observations.addWidget(self.tabs, 1)
        self.current.cellDoubleClicked.connect(self.edit_row)
        self.preview.clicked.connect(self.create_identification)
        self.preview.marker_clicked.connect(self.edit_identification)
        self.preview.pending_clicked.connect(self.edit_pending)
        self.reload_catalogue()
        self.statusBar().showMessage("Choose a folder to begin.")
        self.restore_folder()

    def check_image_paths(self) -> None:
        """Repeat folder recovery and refresh displayed annotations after a confirmed mapping."""
        if not check_image_paths(self.repository, self, manual=True, preferences=self.preferences):
            return
        if self.folder is not None and self.folder.is_dir():
            self.refresh_folder()
        else:
            self.paths = []
            self.files.setRowCount(0)
            self.clear_image()
            self.statusBar().showMessage("Image paths updated. Choose a folder to continue.")

    def restore_folder(self) -> None:
        """Reopen the last folder if present; preference failures leave the app usable."""
        try:
            folder = self.preferences.last_folder()
            if folder is not None:
                self.open_folder(folder)
                image = self.preferences.last_image(folder)
                if image in self.paths:
                    preview_settings = self.preferences.preview_settings()
                    self.files.selectRow(self.paths.index(image))
                    if self.current_path == image:
                        self.brightness_slider.setValue(preview_settings.brightness)
                        self.zoom_slider.setValue(preview_settings.zoom)
        except OSError as error:
            LOGGER.warning("Cannot restore the last folder: %s", error, exc_info=True)
            self.statusBar().showMessage("Could not read preferences. Choose a folder to begin.")
            return

    def open_folder(self, folder: Path) -> None:
        """Display and scan a folder without selecting or modifying any image."""
        try:
            default_date = self.preferences.folder_date(folder)
            if default_date is None:
                default_date = self.prompt_default_date(folder, date.today())
                if default_date is None:
                    return
                self.preferences.save_folder_date(folder, default_date)
        except OSError as error:
            self.report_error(f"Cannot save or read the folder default date: {error}")
            return
        self.folder_default_date = default_date
        self.set_default_date_action.setEnabled(True)
        self.folder = folder
        self.folder_text.setText(str(folder))
        self.refresh.setEnabled(True)
        self.refresh_folder()

    def prompt_default_date(self, folder: Path, initial: date) -> date | None:
        """Ask for a folder default; cancellation leaves the selected folder unchanged."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Default Date")
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Default footage date for {folder}")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        picker = QDateEdit(QDate(initial.year, initial.month, initial.day))
        picker.setCalendarPopup(True)
        picker.setDisplayFormat("dd/MM/yyyy")
        layout.addWidget(picker)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return picker.date().toPython()

    def set_default_date(self) -> None:
        """Change the folder default without rewriting recorded image dates."""
        if self.folder is None:
            return
        selected = self.prompt_default_date(self.folder, self.folder_default_date or date.today())
        if selected is None:
            return
        try:
            self.preferences.save_folder_date(self.folder, selected)
        except OSError as error:
            self.report_error(f"Cannot save the folder default date: {error}")
            return
        self.folder_default_date = selected
        if self.current_path is None:
            self.show_footage_date(selected)
        else:
            try:
                self.show_footage_date(self.repository.image_date(self.current_path) or selected)
            except sqlite3.Error as error:
                self.report_error(f"Cannot read the image date: {error}")

    def show_footage_date(self, value: date | None) -> None:
        """Display a date or an empty field without triggering a database write."""
        self.footage_date.blockSignals(True)
        self.footage_date.setDate(
            QDate(value.year, value.month, value.day)
            if value is not None
            else self.footage_date.minimumDate()
        )
        self.footage_date.blockSignals(False)

    def report_error(self, message: str) -> None:
        """Log underlying failures and display an actionable modal alert."""
        LOGGER.exception(message)
        QMessageBox.critical(self, "ReefTag", message)

    def change_brightness(self, value: int) -> None:
        """Adjust preview brightness and remember it for the current image."""
        self.preview.set_brightness(value)
        self.brightness_value.setText(f"{value:+d}" if value else "0")
        self.save_preview_preferences()

    def change_zoom(self, percentage: int) -> None:
        """Update the preview magnification and its visible percentage."""
        self.preview.set_zoom(percentage)
        self.zoom_value.setText(f"{percentage}%")
        self.save_preview_preferences()

    def save_preview_preferences(self) -> None:
        """Save the current image and controls without making preference failures fatal."""
        if self.current_path is None:
            return
        try:
            self.preferences.save_last_image(
                self.current_path,
                PreviewSettings(self.brightness_slider.value(), self.zoom_slider.value()),
            )
        except OSError as error:
            LOGGER.warning("Cannot save preview preferences: %s", error, exc_info=True)
            self.statusBar().showMessage(
                "Image loaded, but preferences could not be saved for next startup."
            )

    def reset_preview(self) -> None:
        """Restore neutral brightness, fitted zoom and a centred preview."""
        self.brightness_slider.setValue(0)
        self.zoom_slider.setValue(MIN_ZOOM)
        self.preview.reset_pan()

    def reload_catalogue(self) -> None:
        """Refresh the independent shared species view."""
        species = self.repository.species()
        fill_table(self.catalogue, [[s.common_name, s.scientific_name, ""] for s in species])
        for row, item in enumerate(species):
            cell = self.catalogue.item(row, 2)
            cell.setData(Qt.ItemDataRole.UserRole, item.id)
            active = item.id in self.filtered_species
            cell.setIcon(self.species_filter_icon(active))
            description = (
                f"Clear image filter for {item.common_name}"
                if active
                else f"Filter images containing {item.common_name}"
            )
            cell.setToolTip(description)
            cell.setData(Qt.ItemDataRole.AccessibleTextRole, description)

    def edit_categories(self) -> None:
        """Open category maintenance."""
        CategoriesDialog(self.repository, self).exec()

    def edit_species(self, row: int, column: int) -> None:
        """Edit a catalogue entry and refresh all displayed observation names."""
        if column == 2:
            return
        species_id = self.catalogue.item(row, 2).data(Qt.ItemDataRole.UserRole)
        species = next(item for item in self.repository.species() if item.id == species_id)
        if (
            SpeciesMaintenanceDialog(self.repository, species, self).exec()
            == QDialog.DialogCode.Accepted
        ):
            self.reload_catalogue()
            if self.current_path is not None:
                self.annotations = self.repository.identifications(self.current_path)
                self.populate_current()

    def species_filter_icon(self, active: bool) -> QIcon:
        """Draw a funnel with a distinct colour when its species filter is active.

        :param active: Whether this species is included in the current filter.
        :return: Funnel icon for the catalogue action column.
        """
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor("#1684e8") if active else self.palette().text().color()
        painter.setPen(QPen(colour, 1.5))
        painter.setBrush(colour if active else Qt.BrushStyle.NoBrush)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(3, 3),
                    QPointF(17, 3),
                    QPointF(12, 10),
                    QPointF(12, 16),
                    QPointF(8, 18),
                    QPointF(8, 10),
                ]
            )
        )
        painter.end()
        return QIcon(pixmap)

    def toggle_species_filter(self, row: int, column: int) -> None:
        """Toggle a catalogue filter without persisting it between sessions.

        :param row: Clicked catalogue row.
        :param column: Clicked column; only the filter column changes filters.
        """
        if column != 2 or not 0 <= row < self.catalogue.rowCount():
            return
        species_id = self.catalogue.item(row, column).data(Qt.ItemDataRole.UserRole)
        if species_id in self.filtered_species:
            self.filtered_species.remove(species_id)
        else:
            self.filtered_species.add(species_id)
        try:
            self.apply_species_filters()
            self.reload_catalogue()
        except sqlite3.Error as error:
            self.report_error(f"Cannot filter images: {error}")

    def apply_species_filters(self) -> None:
        """Show images matching any active species, retaining a visible selected image."""
        species_images = self.repository.species_image_names() if self.filtered_species else {}
        matching = set().union(*(species_images.get(key, set()) for key in self.filtered_species))
        self.files.blockSignals(True)
        for row, path in enumerate(self.paths):
            hidden = bool(self.filtered_species) and image_identity(path) not in matching
            self.files.setRowHidden(row, hidden)
        if self.current_path in self.paths:
            row = self.paths.index(self.current_path)
            if self.files.isRowHidden(row):
                self.files.clearSelection()
                self.files.setCurrentItem(None)
                self.clear_image()
        self.files.blockSignals(False)

    def choose_folder(self) -> None:
        """Open the native chooser, preserving state on cancellation."""
        folder = QFileDialog.getExistingDirectory(
            self, "Choose image folder", str(self.folder or Path.home())
        )
        if folder:
            self.open_folder(Path(folder))
            if self.folder != Path(folder):
                return
            try:
                self.preferences.save_last_folder(Path(folder))
            except OSError as error:
                LOGGER.warning("Cannot save the last folder: %s", error, exc_info=True)
                self.statusBar().showMessage(
                    "Folder opened, but preferences could not be saved for next startup."
                )

    def refresh_folder(self) -> None:
        """Rescan the selected directory and reload any surviving selected image."""
        if self.folder is None:
            return
        try:
            discovered = discover_images(self.folder)
            tagged_counts = self.repository.tagged_image_counts()
            examination_images = self.repository.further_examination_images()
        except (OSError, sqlite3.Error) as error:
            self.report_error(f"Cannot refresh the folder: {error}")
            return
        previous = self.current_path
        previous_settings = PreviewSettings(
            self.brightness_slider.value(), self.zoom_slider.value()
        )
        self.files.blockSignals(True)
        self.paths = [path for path, _ in discovered]
        fill_table(self.files, [["", "", path.name, f"{size:.1f}"] for path, size in discovered])
        self.update_file_indicators(tagged_counts)
        for row, path in enumerate(self.paths):
            self.update_examination_indicator(row, image_identity(path) in examination_images)
        self.files.clearSelection()
        self.files.blockSignals(False)
        self.clear_image()
        if previous in self.paths:
            self.files.selectRow(self.paths.index(previous))
            if self.current_path == previous:
                self.brightness_slider.setValue(previous_settings.brightness)
                self.zoom_slider.setValue(previous_settings.zoom)
        self.apply_species_filters()
        self.statusBar().showMessage(
            f"{len(self.paths)} images found."
            if self.paths
            else "No supported images in this folder."
        )

    def update_examination_indicator(self, row: int, enabled: bool) -> None:
        """Show a red asterisk and an accessible description of the saved flag."""
        item = self.files.item(row, 1)
        item.setIcon(self.examination_icon if enabled else QIcon())
        item.setData(Qt.ItemDataRole.UserRole, enabled)
        description = (
            "Needs further examination; click to clear"
            if enabled
            else "Click to mark for further examination"
        )
        item.setToolTip(description)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, description)

    def toggle_further_examination(self, row: int, column: int) -> None:
        """Persist a clicked image's flag before changing its visible indicator."""
        if column != 1 or not 0 <= row < len(self.paths):
            return
        path = self.paths[row]
        enabled = not self.files.item(row, 1).data(Qt.ItemDataRole.UserRole)
        footage_date = self.folder_default_date or date.today()
        try:
            self.repository.set_further_examination(path, footage_date, enabled)
        except ValueError as error:
            self.statusBar().showMessage(str(error))
            return
        except sqlite3.Error as error:
            self.report_error(f"Cannot save the further examination flag: {error}")
            return
        self.update_examination_indicator(row, enabled)

    def update_file_indicators(self, tagged_counts: dict[str, int]) -> None:
        """Show a compact tick and accessible tag count for each annotated image."""
        for row, path in enumerate(self.paths):
            count = tagged_counts.get(image_identity(path), 0)
            item = self.files.item(row, 0)
            item.setIcon(self.tagged_icon if count else QIcon())
            description = f"{count} saved fish identification{'s' if count != 1 else ''}"
            item.setToolTip(description)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, description)

    def clear_image(self) -> None:
        """Disable image actions and discard stale preview state."""
        self.current_path = None
        self.annotations = []
        self.pending = []
        self.preview.pending = []
        self.preview.set_image(QPixmap(), [])
        self.brightness_controls.setEnabled(False)
        self.current.setRowCount(0)
        self.footage_date.setEnabled(False)
        self.show_footage_date(self.folder_default_date)

    def select_image(self) -> None:
        """Decode an image and show its recorded date or the selected folder default."""
        row = self.files.currentRow()
        self.clear_image()
        self.reset_preview()
        if row < 0 or row >= len(self.paths):
            return
        path = self.paths[row]
        try:
            reader = QImageReader(str(path))
            # Keep raw pixel orientation so saved coordinates match original image pixels.
            reader.setAutoTransform(False)
            image = reader.read()
            if image.isNull():
                raise ValueError(reader.errorString())
            saved_date = self.repository.image_date(path)
            annotations = self.repository.identifications(path)
            self.pending = self.repository.pending_identifications(path)
            self.current_path = path
            self.annotations = annotations
            self.show_footage_date(saved_date or self.folder_default_date)
            self.footage_date.setEnabled(True)
            self.preview.set_image(QPixmap.fromImage(image), annotations)
            self.brightness_controls.setEnabled(True)
            self.populate_current()
            self.tabs.setCurrentIndex(0)
            self.statusBar().showMessage(f"{path.name} — click a fish to identify it.")
        except (OSError, ValueError, sqlite3.Error) as error:
            self.clear_image()
            self.report_error(f"Cannot load {path.name}: {error}")
            return
        self.save_preview_preferences()

    def populate_current(self) -> None:
        """Show numbered observations and synchronise the overlay."""
        fill_table(
            self.current,
            [
                [str(a.number), a.species.common_name, a.species.scientific_name]
                for a in self.annotations
            ],
        )
        self.preview.pending = self.pending
        self.preview.annotations = self.annotations
        self.preview.update()

    def change_date(self, value: QDate) -> None:
        """Persist date edits immediately, including images without identifications."""
        if self.current_path is None:
            return
        footage_date = date(value.year(), value.month(), value.day())
        try:
            self.repository.update_date(self.current_path, footage_date)
        except sqlite3.Error as error:
            self.report_error(f"Cannot save the footage date: {error}")
            self.select_image()

    def create_identification(self, x: int, y: int) -> None:
        """Open an unsaved annotation at source coordinates."""
        self.identification_dialog(None, x, y)

    def edit_row(self, row: int, column: int) -> None:
        """Open the same editing workflow from a table row."""
        if 0 <= row < len(self.annotations):
            self.edit_identification(self.annotations[row].id)

    def edit_identification(self, identification_id: int) -> None:
        """Open an existing marker while retaining its number and coordinates."""
        annotation = next((a for a in self.annotations if a.id == identification_id), None)
        if annotation:
            self.identification_dialog(annotation, annotation.x, annotation.y)

    def edit_pending(self, pending_id: int) -> None:
        """Open an unknown marker without confusing its ID with identified observations."""
        annotation = next((item for item in self.pending if item.id == pending_id), None)
        if annotation:
            self.identification_dialog(annotation, annotation.x, annotation.y)

    def identification_dialog(
        self, annotation: Identification | PendingIdentification | None, x: int, y: int
    ) -> None:
        """Commit accepted changes and refresh views; cancellation performs no writes."""
        if self.current_path is None:
            return
        try:
            dialog = SpeciesDialog(
                self.repository.species(), annotation, self, self.repository.categories()
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            value = self.footage_date.date()
            footage_date = date(value.year(), value.month(), value.day())
            if isinstance(annotation, PendingIdentification):
                if dialog.deleted:
                    self.repository.delete_pending(annotation.id)
                elif not dialog.unknown:
                    self.repository.create(
                        self.current_path,
                        footage_date,
                        x,
                        y,
                        *dialog.names(),
                        pending_id=annotation.id,
                        category_id=dialog.category_id(),
                    )
            elif dialog.deleted and annotation:
                self.repository.delete(annotation.id)
            elif getattr(dialog, "unknown", False):
                self.repository.create_pending(self.current_path, footage_date, x, y)
            elif annotation:
                self.repository.edit(
                    annotation.id, *dialog.names(), category_id=dialog.category_id()
                )
            else:
                value = self.footage_date.date()
                footage_date = date(value.year(), value.month(), value.day())
                self.repository.create(
                    self.current_path,
                    footage_date,
                    x,
                    y,
                    *dialog.names(),
                    category_id=dialog.category_id(),
                )
            self.pending = self.repository.pending_identifications(self.current_path)
            self.annotations = self.repository.identifications(self.current_path)
            self.populate_current()
            self.reload_catalogue()
            self.update_file_indicators(self.repository.tagged_image_counts())
            examination_images = self.repository.further_examination_images()
            for row, path in enumerate(self.paths):
                self.update_examination_indicator(row, image_identity(path) in examination_images)
            self.apply_species_filters()
            self.statusBar().showMessage(
                "Identification saved." if not dialog.deleted else "Identification deleted."
            )
        except (ValueError, sqlite3.Error) as error:
            self.report_error(f"Cannot save the identification: {error}")
