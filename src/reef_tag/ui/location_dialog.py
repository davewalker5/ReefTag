"""Geographical location maintenance and editing dialogs."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reef_tag.models import Location
from reef_tag.repositories import Repository


class LocationEditorDialog(QDialog):
    """Edit a location, saving only when OK passes validation."""

    def __init__(
        self, repository: Repository, location: Location | None, parent: QWidget | None = None
    ) -> None:
        """Build the form with existing values or blank fields for a new location."""
        super().__init__(parent)
        self.repository = repository
        self.location_id = location.id if location else None
        self.setWindowTitle("Location Editor")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name = QLineEdit(location.name if location else "")
        self.region = QLineEdit(location.region if location else "")
        self.country = QLineEdit(location.country if location else "")
        self.latitude = QLineEdit(
            str(location.latitude) if location and location.latitude is not None else ""
        )
        self.longitude = QLineEdit(
            str(location.longitude) if location and location.longitude is not None else ""
        )
        for label, field in (
            ("Name", self.name),
            ("Region", self.region),
            ("Country", self.country),
            ("Latitude", self.latitude),
            ("Longitude", self.longitude),
        ):
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def coordinate(field: QLineEdit, label: str) -> float | None:
        """Parse an optional coordinate, reporting nonnumeric input by field name."""
        value = field.text().strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a number in decimal degrees.") from error

    def accept(self) -> None:
        """Persist valid values immediately; leave errors open for correction."""
        try:
            self.repository.save_location(
                self.name.text(),
                self.region.text(),
                self.country.text(),
                self.coordinate(self.latitude, "Latitude"),
                self.coordinate(self.longitude, "Longitude"),
                self.location_id,
            )
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Cannot save location", str(error))
            return
        super().accept()


class LocationsDialog(QDialog):
    """List locations and open a separate editor on double-click."""

    def __init__(self, repository: Repository, parent: QWidget | None = None) -> None:
        """Build the location table and creation and close controls."""
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("Location Maintenance")
        self.resize(900, 400)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Region", "Country", "Latitude", "Longitude"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.edit_location)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        actions.addStretch()
        add = QPushButton("Add")
        add.clicked.connect(lambda: self.edit_location(-1, 0))
        actions.addWidget(add)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.reload()

    def reload(self) -> None:
        """Refresh all displayed location fields from persisted records."""
        self.locations = self.repository.locations()
        self.table.setRowCount(len(self.locations))
        for row, location in enumerate(self.locations):
            for column, value in enumerate(
                (
                    location.name,
                    location.region,
                    location.country,
                    location.latitude,
                    location.longitude,
                )
            ):
                self.table.setItem(
                    row, column, QTableWidgetItem("" if value is None else str(value))
                )

    def edit_location(self, row: int, column: int) -> None:
        """Open the selected location or a new record and refresh after saving."""
        location = self.locations[row] if row >= 0 else None
        if (
            LocationEditorDialog(self.repository, location, self).exec()
            == QDialog.DialogCode.Accepted
        ):
            try:
                self.reload()
            except sqlite3.Error as error:
                QMessageBox.warning(self, "Cannot reload locations", str(error))
