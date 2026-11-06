"""Transactional image, species and annotation operations."""

import sqlite3
from datetime import date
from pathlib import Path

from reef_tag.models import (
    Category,
    Identification,
    ImagePathChange,
    PendingIdentification,
    Species,
)


def image_identity(path: Path) -> str:
    """Identify an image by its resolved absolute filesystem path."""
    return str(path.resolve())


class Repository:
    """Own persistence operations on an explicitly supplied connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Retain the connection; the application owns closing it."""
        self.connection = connection

    def image_paths(self) -> dict[int, str]:
        """Return stored image paths keyed by ID in a single query."""
        return dict(self.connection.execute("SELECT id, Name FROM IMAGE"))

    def update_image_paths(self, changes: tuple[ImagePathChange, ...]) -> None:
        """Atomically apply confirmed paths without changing image IDs or metadata.

        :param changes: Validated replacements with their expected original paths.
        :raises ValueError: If a record changed since the mapping was prepared.
        :raises sqlite3.Error: If any update fails; all changes are rolled back.
        """
        if not changes:
            return
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            for change in changes:
                cursor = self.connection.execute(
                    "UPDATE IMAGE SET Name=? WHERE id=? AND Name=?",
                    (change.replacement, change.image_id, change.original),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "Image paths changed during folder mapping. Close the dialog "
                        "and run Check Image Paths again."
                    )

    def species(self) -> list[Species]:
        """Return the complete catalogue in deterministic common-name order."""
        return [
            Species(*row)
            for row in self.connection.execute(
                "SELECT id, CommonName, ScientificName, CategoryId FROM SPECIES "
                "ORDER BY CommonName COLLATE NOCASE, id"
            )
        ]

    def image_date(self, path: Path) -> date | None:
        """Return a saved footage date, or None for an unrecorded image."""
        row = self.connection.execute(
            "SELECT Date FROM IMAGE WHERE Name=?", (image_identity(path),)
        ).fetchone()
        return date.fromisoformat(row[0]) if row else None

    def tagged_image_counts(self) -> dict[str, int]:
        """Return annotation counts by stored image path, excluding untagged images."""
        return dict(
            self.connection.execute(
                "SELECT m.Name, COUNT(*) FROM IMAGE m "
                "JOIN IDENTIFICATION i ON i.ImageId=m.id GROUP BY m.Name"
            )
        )

    def species_image_names(self) -> dict[int, set[str]]:
        """Return identified image paths grouped by species ID.

        :return: Species IDs mapped to unique stored image paths.
        """
        images: dict[int, set[str]] = {}
        for species_id, name in self.connection.execute(
            "SELECT DISTINCT i.SpeciesId, m.Name FROM IDENTIFICATION i "
            "JOIN IMAGE m ON m.id=i.ImageId"
        ):
            images.setdefault(species_id, set()).add(name)
        return images

    def further_examination_images(self) -> set[str]:
        """Return image paths flagged for further examination, including untagged images."""
        return {
            row[0]
            for row in self.connection.execute("SELECT Name FROM IMAGE WHERE FurtherExamination=1")
        }

    def set_further_examination(self, path: Path, footage_date: date, enabled: bool) -> None:
        """Save the flag independently of identifications, retaining existing image data."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if not enabled and self.pending_identifications(path):
                raise ValueError("Resolve all unknown markers before clearing further examination.")
            self.connection.execute(
                "INSERT INTO IMAGE (Name, Date, FurtherExamination) VALUES (?, ?, ?) "
                "ON CONFLICT(Name) DO UPDATE SET FurtherExamination=excluded.FurtherExamination",
                (image_identity(path), footage_date.isoformat(), int(enabled)),
            )

    def update_date(self, path: Path, footage_date: date) -> None:
        """Save an image date, creating an untagged record when necessary."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO IMAGE (Name, Date) VALUES (?, ?) "
                "ON CONFLICT(Name) DO UPDATE SET Date=excluded.Date",
                (image_identity(path), footage_date.isoformat()),
            )

    def identifications(self, path: Path) -> list[Identification]:
        """Return an image's observations in stable number order."""
        rows = self.connection.execute(
            """
            SELECT i.id, i.Number, i.X, i.Y, s.id, s.CommonName, s.ScientificName, s.CategoryId
            FROM IDENTIFICATION i JOIN IMAGE m ON m.id=i.ImageId
            JOIN SPECIES s ON s.id=i.SpeciesId WHERE m.Name=? ORDER BY i.Number
        """,
            (image_identity(path),),
        )
        return [Identification(*row[:4], Species(*row[4:])) for row in rows]

    def _resolve_species(
        self, common_name: str, scientific_name: str, category_id: int | None = None
    ) -> int:
        """Reuse an exact name pair, or create it; reject conflicting unique names."""
        common_name, scientific_name = common_name.strip(), scientific_name.strip()
        if not common_name or not scientific_name:
            raise ValueError("Both common name and scientific name are required.")
        rows = self.connection.execute(
            """SELECT id, CommonName, ScientificName FROM SPECIES
            WHERE CommonName=? OR ScientificName=?""",
            (common_name, scientific_name),
        ).fetchall()
        if rows:
            if len(rows) == 1 and tuple(rows[0][1:]) == (common_name, scientific_name):
                self.connection.execute(
                    "UPDATE SPECIES SET CategoryId=? WHERE id=?", (category_id, rows[0][0])
                )
                return rows[0][0]
            existing = "; ".join(f"{row[1]} ({row[2]})" for row in rows)
            raise ValueError(
                f"A name already belongs to {existing}. Select it or correct the names."
            )
        cursor = self.connection.execute(
            "INSERT INTO SPECIES (CommonName, ScientificName, CategoryId) VALUES (?, ?, ?)",
            (common_name, scientific_name, category_id),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def create(
        self,
        path: Path,
        footage_date: date,
        x: int,
        y: int,
        common_name: str,
        scientific_name: str,
        *,
        pending_id: int | None = None,
        category_id: int | None = None,
    ) -> None:
        """Atomically save an identification, optionally replacing an unknown marker.

        :param path: Photograph containing the observation.
        :param footage_date: Date used for a newly recorded photograph.
        :param x: Original horizontal pixel coordinate for a new identification.
        :param y: Original vertical pixel coordinate for a new identification.
        :param common_name: Selected species common name.
        :param scientific_name: Selected species scientific name.
        :param category_id: Category assigned to the selected or newly created species.
        :param pending_id: Unknown marker to replace, using its saved coordinates.
        :raises ValueError: If coordinates, species names or the pending marker are invalid.
        """
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0:
            raise ValueError("Coordinates must be non-negative integer pixels.")
        with self.connection:
            # Acquire the write lock before reading numbering or catalogue state.
            self.connection.execute("BEGIN IMMEDIATE")
            if pending_id is not None:
                pending = next(
                    (item for item in self.pending_identifications(path) if item.id == pending_id),
                    None,
                )
                if pending is None:
                    raise ValueError("This unknown marker no longer exists. Refresh the image.")
                x, y = pending.x, pending.y
                self.connection.execute(
                    "DELETE FROM PENDING_IDENTIFICATION WHERE id=?", (pending_id,)
                )
            species_id = self._resolve_species(common_name, scientific_name, category_id)
            identity = image_identity(path)
            row = self.connection.execute(
                "SELECT id FROM IMAGE WHERE Name=?", (identity,)
            ).fetchone()
            if row:
                image_id = row[0]
            else:
                cursor = self.connection.execute(
                    "INSERT INTO IMAGE (Name, Date) VALUES (?, ?)",
                    (identity, footage_date.isoformat()),
                )
                assert cursor.lastrowid is not None
                image_id = cursor.lastrowid
            number = self.connection.execute(
                "SELECT COALESCE(MAX(Number), 0)+1 FROM IDENTIFICATION WHERE ImageId=?", (image_id,)
            ).fetchone()[0]
            self.connection.execute(
                "INSERT INTO IDENTIFICATION (ImageId, SpeciesId, Number, X, Y) "
                "VALUES (?, ?, ?, ?, ?)",
                (image_id, species_id, number, x, y),
            )

    def edit(
        self,
        identification_id: int,
        common_name: str,
        scientific_name: str,
        *,
        category_id: int | None = None,
    ) -> None:
        """Assign an observation to a species and save that species category.

        :param identification_id: Observation to reassign.
        :param common_name: Selected or new common name.
        :param scientific_name: Selected or new scientific name.
        :param category_id: Shared species category, or None to clear it.
        :raises ValueError: If the observation is missing or species names conflict.
        """
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if not self.connection.execute(
                "SELECT 1 FROM IDENTIFICATION WHERE id=?", (identification_id,)
            ).fetchone():
                raise ValueError("This identification no longer exists. Refresh the image.")
            species_id = self._resolve_species(common_name, scientific_name, category_id)
            self.connection.execute(
                "UPDATE IDENTIFICATION SET SpeciesId=? WHERE id=?", (species_id, identification_id)
            )

    def delete(self, identification_id: int) -> None:
        """Delete only an observation, retaining its parent and catalogue entry."""
        with self.connection:
            self.connection.execute("DELETE FROM IDENTIFICATION WHERE id=?", (identification_id,))

    def pending_identifications(self, path: Path) -> list[PendingIdentification]:
        """Return unknown markers for an image path in stable creation order.

        :param path: Photograph whose markers should be loaded.
        :return: Saved markers in original-image pixels.
        """
        return [
            PendingIdentification(*row)
            for row in self.connection.execute(
                "SELECT p.id, p.X, p.Y FROM PENDING_IDENTIFICATION p "
                "JOIN IMAGE m ON m.id=p.ImageId WHERE m.Name=? ORDER BY p.id",
                (image_identity(path),),
            )
        ]

    def create_pending(self, path: Path, footage_date: date, x: int, y: int) -> None:
        """Save an unknown marker and flag its photograph atomically.

        :param path: Photograph containing the fish.
        :param footage_date: Date used only for a newly recorded photograph.
        :param x: Non-negative horizontal original-image pixel coordinate.
        :param y: Non-negative vertical original-image pixel coordinate.
        :raises ValueError: If coordinates are not non-negative integers.
        """
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0:
            raise ValueError("Coordinates must be non-negative integer pixels.")
        with self.connection:
            self.connection.execute(
                "INSERT INTO IMAGE (Name, Date, FurtherExamination) VALUES (?, ?, 1) "
                "ON CONFLICT(Name) DO UPDATE SET FurtherExamination=1",
                (image_identity(path), footage_date.isoformat()),
            )
            self.connection.execute(
                "INSERT INTO PENDING_IDENTIFICATION (ImageId, X, Y) "
                "SELECT id, ?, ? FROM IMAGE WHERE Name=?",
                (x, y, image_identity(path)),
            )

    def delete_pending(self, pending_id: int) -> None:
        """Remove an unknown marker, retaining its image and examination flag.

        :param pending_id: Primary key of the marker to remove.
        """
        with self.connection:
            self.connection.execute("DELETE FROM PENDING_IDENTIFICATION WHERE id=?", (pending_id,))

    def categories(self) -> list[Category]:
        """Return categories with species counts in name order."""
        return [
            Category(*row)
            for row in self.connection.execute(
                "SELECT c.Id, c.Name, COUNT(s.id) FROM CATEGORY c "
                "LEFT JOIN SPECIES s ON s.CategoryId=c.Id GROUP BY c.Id "
                "ORDER BY c.Name COLLATE NOCASE, c.Id"
            )
        ]

    def save_category(self, name: str, category_id: int | None = None) -> None:
        """Create or rename a category, rejecting blank or duplicate names."""
        name = name.strip()
        if not name:
            raise ValueError("Enter a category name.")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if any(
                c.name.casefold() == name.casefold() and c.id != category_id
                for c in self.categories()
            ):
                raise ValueError("A category with that name already exists.")
            if category_id is None:
                self.connection.execute("INSERT INTO CATEGORY (Name) VALUES (?)", (name,))
            elif (
                self.connection.execute(
                    "UPDATE CATEGORY SET Name=? WHERE Id=?", (name, category_id)
                ).rowcount
                != 1
            ):
                raise ValueError("This category no longer exists.")

    def delete_category(self, category_id: int) -> None:
        """Delete an unused category; reject deletion while species reference it."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.connection.execute(
                "SELECT 1 FROM SPECIES WHERE CategoryId=?", (category_id,)
            ).fetchone():
                raise ValueError("This category is used by species and cannot be deleted.")
            self.connection.execute("DELETE FROM CATEGORY WHERE Id=?", (category_id,))

    def update_species(
        self, species_id: int, common_name: str, scientific_name: str, category_id: int | None
    ) -> None:
        """Update a shared catalogue entry without changing observation assignments."""
        common_name, scientific_name = common_name.strip(), scientific_name.strip()
        if not common_name or not scientific_name:
            raise ValueError("Both common name and scientific name are required.")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if any(
                s.id != species_id
                and (
                    s.common_name.casefold() == common_name.casefold()
                    or s.scientific_name.casefold() == scientific_name.casefold()
                )
                for s in self.species()
            ):
                raise ValueError("A species with one of these names already exists.")
            if (
                self.connection.execute(
                    "UPDATE SPECIES SET CommonName=?, ScientificName=?, CategoryId=? WHERE id=?",
                    (common_name, scientific_name, category_id, species_id),
                ).rowcount
                != 1
            ):
                raise ValueError("This species no longer exists.")
