"""Species assignment without implicit global catalogue renames."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reef_tag.models import Identification, Species


class SpeciesDialog(QDialog):
    """Collect an existing species or a new name pair; defer writes to the caller."""

    def __init__(
        self, catalogue: list[Species], annotation: Identification | None, parent: QWidget
    ) -> None:
        """Populate catalogue and optional edit context without persisting anything."""
        super().__init__(parent)
        self.setWindowTitle("Species Identification Details")
        self.deleted = False
        self.catalogue = catalogue
        self.selector = QComboBox()
        self.selector.addItem("Enter a new species…")
        for species in catalogue:
            self.selector.addItem(f"{species.common_name} ({species.scientific_name})")
        self.common = QLineEdit()
        self.scientific = QLineEdit()
        self.selector.currentIndexChanged.connect(self.select_species)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        if annotation:
            layout.addWidget(
                QLabel(f"Position {annotation.number} · pixel ({annotation.x}, {annotation.y})")
            )
        form = QFormLayout()
        # Grow every field on macOS too, where the native form style can cap widths.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.addRow("Species", self.selector)
        form.addRow("Common Name", self.common)
        form.addRow("Scientific Name", self.scientific)
        layout.addLayout(form)
        layout.addWidget(QLabel("Changing names assigns a species to this identification only."))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if annotation:
            delete = QPushButton("Delete")
            delete.clicked.connect(self.delete_annotation)
            buttons.addButton(delete, QDialogButtonBox.ButtonRole.DestructiveRole)
            self.selector.setCurrentIndex(
                next(i + 1 for i, s in enumerate(catalogue) if s.id == annotation.species.id)
            )
        layout.addWidget(buttons)

    def select_species(self, index: int) -> None:
        """Fill names from the catalogue, or clear for explicit new entry."""
        species = self.catalogue[index - 1] if index else None
        self.common.setText(species.common_name if species else "")
        self.scientific.setText(species.scientific_name if species else "")

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
