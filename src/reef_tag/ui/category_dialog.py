"""Category maintenance and shared species editing dialogs."""

import sqlite3

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reef_tag.models import Species
from reef_tag.repositories import Repository
from reef_tag.ui.species_dialog import SpeciesDialog


class CategoriesDialog(QDialog):
    """Maintain names and delete unused categories with confirmation."""

    def __init__(self, repository: Repository, parent: QWidget) -> None:
        """Build the category table and load current usage counts."""
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("Species Categories")
        self.resize(540, 360)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Species", ""])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 44)
        self.table.cellDoubleClicked.connect(self.edit_category)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        buttons.addStretch()
        add = QPushButton("Add")
        add.clicked.connect(lambda: self.edit_category(-1, 0))
        buttons.addWidget(add)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        """Reload counts and enable deletion only for unused categories."""
        self.categories = self.repository.categories()
        self.table.setRowCount(len(self.categories))
        for row, category in enumerate(self.categories):
            self.table.setItem(row, 0, QTableWidgetItem(category.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(category.species_count)))
            delete = QPushButton()
            delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
            delete.setToolTip(f"Delete {category.name}")
            delete.setAccessibleName(f"Delete {category.name}")
            delete.setEnabled(category.species_count == 0)
            delete.clicked.connect(lambda checked=False, key=category.id: self.delete_category(key))
            self.table.setCellWidget(row, 2, delete)

    def edit_category(self, row: int, column: int) -> None:
        """Prompt for a name and keep invalid edits available for correction."""
        if column == 2:
            return
        category = self.categories[row] if row >= 0 else None
        name = category.name if category else ""
        while True:
            name, accepted = QInputDialog.getText(self, "Category Name", "Name", text=name)
            if not accepted:
                return
            try:
                self.repository.save_category(name, category.id if category else None)
            except (ValueError, sqlite3.Error) as error:
                QMessageBox.warning(self, "Cannot save category", str(error))
                continue
            self.reload()
            return

    def delete_category(self, category_id: int) -> None:
        """Confirm and delete an unused category, displaying persistence errors."""
        if QMessageBox.question(self, "Delete category?", "Permanently delete this category?") != (
            QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.repository.delete_category(category_id)
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Cannot delete category", str(error))
        self.reload()


class SpeciesMaintenanceDialog(SpeciesDialog):
    """Edit a shared catalogue record and validate before closing."""

    def __init__(self, repository: Repository, species: Species, parent: QWidget) -> None:
        """Reuse the name/category form without identification controls."""
        super().__init__(repository.species(), None, parent, repository.categories())
        self.repository = repository
        self.species_id = species.id
        self.setWindowTitle("Species Editor")
        self.setMinimumWidth(520)
        self.selector.setCurrentIndex(
            next(index + 1 for index, item in enumerate(self.catalogue) if item.id == species.id)
        )
        self.selector.hide()
        self.form.labelForField(self.selector).hide()
        self.hint.hide()
        self.unknown_button.hide()

    def accept(self) -> None:
        """Save validated shared changes, leaving failures open for correction."""
        try:
            self.repository.update_species(self.species_id, *self.names(), self.category_id())
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Cannot save species", str(error))
            return
        QDialog.accept(self)
