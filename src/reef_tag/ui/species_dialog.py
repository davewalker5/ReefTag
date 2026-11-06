"""Species assignment without implicit global catalogue renames."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reef_tag.models import Category, Identification, PendingIdentification, Species


class SpeciesDialog(QDialog):
    """Collect an existing species or a new name pair; defer writes to the caller."""

    def __init__(
        self,
        catalogue: list[Species],
        annotation: Identification | PendingIdentification | None,
        parent: QWidget,
        categories: list[Category] | None = None,
    ) -> None:
        """Populate catalogue and optional edit context without persisting anything."""
        super().__init__(parent)
        self.setWindowTitle("Species Identification Details")
        self.deleted = False
        self.unknown = False
        self.catalogue = catalogue
        self.selector = QComboBox()
        self.selector.addItem("Enter a new species…")
        for species in catalogue:
            self.selector.addItem(f"{species.common_name} ({species.scientific_name})")
        self.category = QComboBox()
        self.category.addItem("", None)
        for category in categories or []:
            self.category.addItem(category.name, category.id)
        self.common = QLineEdit()
        self.scientific = QLineEdit()
        self.selector.currentIndexChanged.connect(self.select_species)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        if annotation:
            label = (
                f"Position {annotation.number}"
                if isinstance(annotation, Identification)
                else "Unknown"
            )
            layout.addWidget(QLabel(f"{label} · pixel ({annotation.x}, {annotation.y})"))
        form = self.form = QFormLayout()
        # Grow every field on macOS too, where the native form style can cap widths.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.addRow("Identified Species", self.selector)
        form.addRow("Common Name", self.common)
        form.addRow("Scientific Name", self.scientific)
        form.addRow("Category", self.category)
        layout.addLayout(form)
        self.hint = QLabel(
            "Names assign a species to this identification. Category changes apply to the species."
        )
        layout.addWidget(self.hint)
        # Explicit ordering keeps Unknown between Cancel and OK across native styles.
        buttons = QHBoxLayout()
        if annotation:
            delete = QPushButton("Delete")
            delete.clicked.connect(self.delete_annotation)
            buttons.addWidget(delete)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        if not isinstance(annotation, Identification):
            unknown = self.unknown_button = QPushButton("Unknown")
            unknown.clicked.connect(self.mark_unknown)
            buttons.addWidget(unknown)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        if isinstance(annotation, Identification):
            self.selector.setCurrentIndex(
                next(i + 1 for i, s in enumerate(catalogue) if s.id == annotation.species.id)
            )
        layout.addLayout(buttons)

    def mark_unknown(self) -> None:
        """Return an unknown-marker request without requiring species names."""
        self.unknown = True
        super().accept()

    def select_species(self, index: int) -> None:
        """Fill names from the catalogue, or clear for explicit new entry."""
        species = self.catalogue[index - 1] if index else None
        self.category.setCurrentIndex(
            max(0, self.category.findData(species.category_id if species else None))
        )
        self.common.setText(species.common_name if species else "")
        self.scientific.setText(species.scientific_name if species else "")

    def category_id(self) -> int | None:
        """Return the selected category ID, including the empty selection."""
        return self.category.currentData()

    def names(self) -> tuple[str, str]:
        """Return whitespace-trimmed display names."""
        return self.common.text().strip(), self.scientific.text().strip()

    def accept(self) -> None:
        """Keep incomplete or conflicting species entries open for correction."""
        common, scientific = self.names()
        if not common or not scientific:
            QMessageBox.warning(self, "Species required", "Enter both names or select a species.")
            return
        conflicts = [
            s
            for s in self.catalogue
            if (s.common_name == common or s.scientific_name == scientific)
            and (s.common_name, s.scientific_name) != (common, scientific)
        ]
        if conflicts:
            QMessageBox.warning(
                self,
                "Species already exists",
                "A name already exists in the catalogue. Select that species or correct the names.",
            )
            return
        super().accept()

    def delete_annotation(self) -> None:
        """Require confirmation before returning a deletion request."""
        if (
            QMessageBox.question(
                self, "Delete identification?", "Permanently delete this identification?"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.deleted = True
            super().accept()
