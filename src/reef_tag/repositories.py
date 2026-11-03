"""Transactional image, species and annotation operations."""

import sqlite3
from datetime import date
from pathlib import Path

from reef_tag.models import Identification, Species


def image_identity(path: Path) -> str:
    """Identify images by filename only, so moving their folder preserves annotations.

    Equal filenames in different folders intentionally refer to the same saved image.
    """
    return path.name


class Repository:
    """Own persistence operations on an explicitly supplied connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Retain the connection; the application owns closing it."""
        self.connection = connection

    def species(self) -> list[Species]:
        """Return the complete catalogue in deterministic common-name order."""
        return [
            Species(*row)
            for row in self.connection.execute(
                "SELECT id, CommonName, ScientificName FROM SPECIES "
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
        """Return annotation counts by stored filename, excluding untagged images."""
        return dict(
            self.connection.execute(
                "SELECT m.Name, COUNT(*) FROM IMAGE m "
                "JOIN IDENTIFICATION i ON i.ImageId=m.id GROUP BY m.Name"
            )
        )

    def update_date(self, path: Path, footage_date: date) -> None:
        """Update an existing image only; never create an empty image record."""
        with self.connection:
            self.connection.execute(
                "UPDATE IMAGE SET Date=? WHERE Name=?",
                (footage_date.isoformat(), image_identity(path)),
            )

    def identifications(self, path: Path) -> list[Identification]:
        """Return an image's observations in stable number order."""
        rows = self.connection.execute(
            """
            SELECT i.id, i.Number, i.X, i.Y, s.id, s.CommonName, s.ScientificName
            FROM IDENTIFICATION i JOIN IMAGE m ON m.id=i.ImageId
            JOIN SPECIES s ON s.id=i.SpeciesId WHERE m.Name=? ORDER BY i.Number
        """,
            (image_identity(path),),
        )
        return [Identification(*row[:4], Species(*row[4:])) for row in rows]

    def _resolve_species(self, common_name: str, scientific_name: str) -> int:
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
                return rows[0][0]
            existing = "; ".join(f"{row[1]} ({row[2]})" for row in rows)
            raise ValueError(
                f"A name already belongs to {existing}. Select it or correct the names."
            )
        cursor = self.connection.execute(
            "INSERT INTO SPECIES (CommonName, ScientificName) VALUES (?, ?)",
            (common_name, scientific_name),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def create(
        self, path: Path, footage_date: date, x: int, y: int, common_name: str, scientific_name: str
    ) -> None:
        """Atomically save the image, species and a max-plus-one numbered annotation."""
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0:
            raise ValueError("Coordinates must be non-negative integer pixels.")
        with self.connection:
            # Acquire the write lock before reading numbering or catalogue state.
            self.connection.execute("BEGIN IMMEDIATE")
            species_id = self._resolve_species(common_name, scientific_name)
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

    def edit(self, identification_id: int, common_name: str, scientific_name: str) -> None:
        """Change only the selected observation's species assignment."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if not self.connection.execute(
                "SELECT 1 FROM IDENTIFICATION WHERE id=?", (identification_id,)
            ).fetchone():
                raise ValueError("This identification no longer exists. Refresh the image.")
            species_id = self._resolve_species(common_name, scientific_name)
            self.connection.execute(
                "UPDATE IDENTIFICATION SET SpeciesId=? WHERE id=?", (species_id, identification_id)
            )

    def delete(self, identification_id: int) -> None:
        """Delete only an observation, retaining its parent and catalogue entry."""
        with self.connection:
            self.connection.execute("DELETE FROM IDENTIFICATION WHERE id=?", (identification_id,))
