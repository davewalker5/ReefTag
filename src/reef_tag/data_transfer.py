"""CSV interchange for saved observations, independent of the desktop interface."""

import csv
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reef_tag.repositories import IMAGE_PATHS, Repository

COLUMNS = (
    "Date",
    "Image",
    "Further Examination",
    "Type",
    "Number",
    "X",
    "Y",
    "Category",
    "Common Name",
    "Scientific Name",
)


@dataclass(frozen=True)
class TransferRecord:
    """A validated CSV observation using original-image integer pixel coordinates."""

    footage_date: str
    image: str
    examination: bool
    kind: str
    number: int | None
    x: int
    y: int
    category: str
    common_name: str
    scientific_name: str


@dataclass
class TransferSummary:
    """Counts of observations transferred and duplicate rows skipped."""

    images: int = 0
    identifications: int = 0
    unknowns: int = 0
    duplicates: int = 0

    def description(self) -> str:
        """Return counts suitable for a completion dialog."""
        return (
            f"Images: {self.images}\nIdentifications: {self.identifications}\n"
            f"Unknown markers: {self.unknowns}\nDuplicates skipped: {self.duplicates}"
        )


def folder_records(repository: Repository, folder: Path) -> list[TransferRecord]:
    """Return observations directly in folder, including images absent from disk.

    :param repository: Database containing the saved observations.
    :param folder: Folder to export; descendants are excluded.
    :return: Records in image, type and marker order.
    """
    rows = repository.connection.execute(
        f"""SELECT m.Date, m.Name, m.FurtherExamination, 'IDENTIFICATION',
                  i.Number, i.X, i.Y, COALESCE(c.Name, ''), s.CommonName, s.ScientificName
           FROM {IMAGE_PATHS} m JOIN IDENTIFICATION i ON i.ImageId=m.id
           JOIN SPECIES s ON s.id=i.SpeciesId LEFT JOIN CATEGORY c ON c.Id=s.CategoryId
           UNION ALL
           SELECT m.Date, m.Name, m.FurtherExamination, 'UNKNOWN',
                  NULL, p.X, p.Y, '', '', ''
           FROM {IMAGE_PATHS} m JOIN PENDING_IDENTIFICATION p ON p.ImageId=m.id
           ORDER BY 2, 4, 5, 6, 7"""
    )
    folder = folder.resolve()
    return [TransferRecord(*row) for row in rows if Path(row[1]).parent == folder]


def export_csv(path: Path, records: list[TransferRecord]) -> TransferSummary:
    """Write UTF-8 CSV with fixed columns and return exported observation counts.

    :param path: Destination selected and approved for replacement by the caller.
    :param records: Snapshot of observations to export.
    :return: Counts written to the CSV.
    :raises OSError: If the destination cannot be written.
    """
    summary = TransferSummary(images=len({record.image for record in records}))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for record in records:
            writer.writerow(
                (
                    record.footage_date,
                    record.image,
                    int(record.examination),
                    record.kind,
                    record.number if record.number is not None else "",
                    record.x,
                    record.y,
                    record.category,
                    record.common_name,
                    record.scientific_name,
                )
            )
            if record.kind == "IDENTIFICATION":
                summary.identifications += 1
            else:
                summary.unknowns += 1
    return summary


def _parse_record(values: list[str]) -> TransferRecord:
    """Validate one CSV row, raising ValueError for invalid fields."""
    if len(values) != len(COLUMNS):
        raise ValueError(f"Expected {len(COLUMNS)} columns.")
    day, image, examination, kind, number, x, y, category, common, scientific = values
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("Date must use YYYY-MM-DD.")
    if not image or not Path(image).is_absolute():
        raise ValueError("Image must contain an absolute image path.")
    if examination not in ("0", "1"):
        raise ValueError("Further Examination must be 0 or 1.")
    if kind not in ("IDENTIFICATION", "UNKNOWN"):
        raise ValueError("Type must be IDENTIFICATION or UNKNOWN.")
    pixel_x, pixel_y = int(x), int(y)
    if pixel_x < 0 or pixel_y < 0:
        raise ValueError("Coordinates must be non-negative integer pixels.")
    marker_number = None
    if kind == "IDENTIFICATION":
        marker_number = int(number)
        if marker_number <= 0 or not common.strip() or not scientific.strip():
            raise ValueError("Identifications require a positive number and both species names.")
    elif any((number, category, common, scientific)):
        raise ValueError("Unknown markers require blank number, category and species fields.")
    return TransferRecord(
        day,
        image,
        examination == "1",
        kind,
        marker_number,
        pixel_x,
        pixel_y,
        category.strip(),
        common.strip(),
        scientific.strip(),
    )


def _species_id(connection: sqlite3.Connection, record: TransferRecord) -> int:
    """Reuse matching species without changing its metadata, or create its category and species."""
    rows = connection.execute(
        "SELECT id, CommonName, ScientificName FROM SPECIES WHERE CommonName=? OR ScientificName=?",
        (record.common_name, record.scientific_name),
    ).fetchall()
    if rows:
        if len(rows) != 1 or tuple(rows[0][1:]) != (record.common_name, record.scientific_name):
            raise ValueError("Species names conflict with the existing catalogue.")
        return rows[0][0]
    category_id = None
    if record.category:
        connection.execute("INSERT OR IGNORE INTO CATEGORY (Name) VALUES (?)", (record.category,))
        category_id = connection.execute(
            "SELECT Id FROM CATEGORY WHERE Name=?", (record.category,)
        ).fetchone()[0]
    cursor = connection.execute(
        "INSERT INTO SPECIES (CommonName, ScientificName, CategoryId) VALUES (?, ?, ?)",
        (record.common_name, record.scientific_name, category_id),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _import_record(connection: sqlite3.Connection, record: TransferRecord) -> bool:
    """Merge one observation and return whether a new marker was inserted."""
    repository = Repository(connection)
    folder_id, filename = repository._image_key(
        Path(record.image), date.fromisoformat(record.footage_date)
    )
    connection.execute(
        "INSERT INTO IMAGE (FolderId, Name, FurtherExamination) VALUES (?, ?, ?) "
        "ON CONFLICT(FolderId, Name) DO UPDATE SET "
        "FurtherExamination=MAX(IMAGE.FurtherExamination, excluded.FurtherExamination)",
        (
            folder_id,
            filename,
            int(record.examination or record.kind == "UNKNOWN"),
        ),
    )
    image_id = connection.execute(
        "SELECT id FROM IMAGE WHERE FolderId=? AND Name=?", (folder_id, filename)
    ).fetchone()[0]
    if record.kind == "UNKNOWN":
        if connection.execute(
            "SELECT 1 FROM PENDING_IDENTIFICATION WHERE ImageId=? AND X=? AND Y=?",
            (image_id, record.x, record.y),
        ).fetchone():
            return False
        connection.execute(
            "INSERT INTO PENDING_IDENTIFICATION (ImageId, X, Y) VALUES (?, ?, ?)",
            (image_id, record.x, record.y),
        )
        return True
    existing = connection.execute(
        "SELECT X, Y FROM IDENTIFICATION WHERE ImageId=? AND Number=?",
        (image_id, record.number),
    ).fetchone()
    if existing:
        if tuple(existing) == (record.x, record.y):
            return False
        raise ValueError(f"Identification number {record.number} already has a different position.")
    species_id = _species_id(connection, record)
    connection.execute(
        "INSERT INTO IDENTIFICATION (ImageId, SpeciesId, Number, X, Y) VALUES (?, ?, ?, ?, ?)",
        (image_id, species_id, record.number, record.x, record.y),
    )
    return True


def import_csv(repository: Repository, path: Path) -> TransferSummary:
    """Validate and import an entire CSV atomically, skipping exact marker duplicates.

    Existing folder dates and species metadata are retained. Examination flags are merged.

    :param repository: Destination database.
    :param path: UTF-8 CSV previously exported by ReefTag.
    :return: Counts inserted and skipped; images counts newly inserted observations' images.
    :raises ValueError: If any row is malformed or conflicts with saved data.
    :raises OSError: If the source cannot be read.
    :raises sqlite3.Error: If persistence fails; all writes are rolled back.
    """
    summary = TransferSummary()
    images: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as stream, repository.connection:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != list(COLUMNS):
            raise ValueError("CSV columns do not match the ReefTag export format.")
        repository.connection.execute("BEGIN IMMEDIATE")
        for values in reader:
            try:
                record = _parse_record(values)
                if not _import_record(repository.connection, record):
                    summary.duplicates += 1
                    continue
            except ValueError as error:
                raise ValueError(f"CSV line {reader.line_num}: {error}") from error
            images.add(record.image)
            if record.kind == "IDENTIFICATION":
                summary.identifications += 1
            else:
                summary.unknowns += 1
    summary.images = len(images)
    return summary
