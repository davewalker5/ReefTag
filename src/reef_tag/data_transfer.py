"""CSV interchange for saved observations, independent of the desktop interface."""

import csv
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reef_tag.repositories import Repository

COLUMNS = (
    "Date",
    "Folder",
    "Location",
    "Region",
    "Country",
    "Latitude",
    "Longitude",
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
    folder: str
    location: str
    region: str
    country: str
    latitude: float | None
    longitude: float | None
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
        """WITH markers AS (
               SELECT i.ImageId, 'IDENTIFICATION' AS Kind, i.Number, i.X, i.Y,
                      COALESCE(c.Name, '') AS Category, s.CommonName, s.ScientificName
               FROM IDENTIFICATION i JOIN SPECIES s ON s.Id=i.SpeciesId
               LEFT JOIN CATEGORY c ON c.Id=s.CategoryId
               UNION ALL
               SELECT p.ImageId, 'UNKNOWN', NULL, p.X, p.Y, '', '', ''
               FROM PENDING_IDENTIFICATION p
           )
           SELECT SUBSTR(f.Date, 1, 10), f.Path, COALESCE(l.Name, ''),
                  COALESCE(l.Region, ''), COALESCE(l.Country, ''), l.Latitude, l.Longitude,
                  im.Name, im.FurtherExamination, m.Kind, m.Number, m.X, m.Y,
                  m.Category, m.CommonName, m.ScientificName
           FROM markers m JOIN IMAGE im ON im.Id=m.ImageId
           JOIN FOLDER f ON f.Id=im.FolderId LEFT JOIN LOCATION l ON l.Id=f.LocationId
           WHERE f.Path=? ORDER BY im.Name, m.Kind, m.Number, m.X, m.Y""",
        (str(folder.resolve()),),
    )
    return [TransferRecord(*row) for row in rows]


def export_csv(path: Path, records: list[TransferRecord]) -> TransferSummary:
    """Write UTF-8 CSV with fixed columns and return exported observation counts.

    :param path: Destination selected and approved for replacement by the caller.
    :param records: Snapshot of observations to export.
    :return: Counts written to the CSV.
    :raises OSError: If the destination cannot be written.
    """
    summary = TransferSummary(images=len({(record.folder, record.image) for record in records}))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for record in records:
            writer.writerow(
                (
                    record.footage_date,
                    record.folder,
                    record.location,
                    record.region,
                    record.country,
                    record.latitude,
                    record.longitude,
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


def _parse_coordinate(value: str, label: str, limit: int) -> float | None:
    """Parse optional finite decimal degrees within the supplied geographical limit.

    :param value: CSV cell, with a blank cell representing an absent coordinate.
    :param label: Field name used in validation errors.
    :param limit: Inclusive positive limit; the negative limit is also allowed.
    :return: Coordinate or None for a blank cell.
    :raises ValueError: If the cell is nonnumeric, nonfinite or out of range.
    """
    if not value.strip():
        return None
    try:
        coordinate = float(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a number in decimal degrees.") from error
    if not math.isfinite(coordinate) or not -limit <= coordinate <= limit:
        raise ValueError(f"{label} must be between {-limit} and {limit} degrees.")
    return coordinate


def _parse_record(values: list[str]) -> TransferRecord:
    """Validate one CSV row, raising ValueError for invalid fields."""
    if len(values) != len(COLUMNS):
        raise ValueError(f"Expected {len(COLUMNS)} columns.")
    (
        day,
        folder,
        location,
        region,
        country,
        latitude,
        longitude,
        image,
        examination,
        kind,
        number,
        x,
        y,
        category,
        common,
        scientific,
    ) = values
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("Date must use YYYY-MM-DD.")
    if not folder.strip() or "\0" in folder or not Path(folder).is_absolute():
        raise ValueError("Folder must contain an absolute folder path.")
    if not image.strip() or image in {".", ".."} or any(char in image for char in "/\\\0"):
        raise ValueError("Image must contain a filename only, without a folder path.")
    location, region, country = location.strip(), region.strip(), country.strip()
    parsed_latitude = _parse_coordinate(latitude, "Latitude", 90)
    parsed_longitude = _parse_coordinate(longitude, "Longitude", 180)
    if location:
        if not region or not country:
            raise ValueError("Locations require both Region and Country.")
    elif region or country or latitude.strip() or longitude.strip():
        raise ValueError("Location details require a Location name.")
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
        footage_date=day,
        folder=str(Path(folder).resolve()),
        location=location,
        region=region,
        country=country,
        latitude=parsed_latitude,
        longitude=parsed_longitude,
        image=image,
        examination=examination == "1",
        kind=kind,
        number=marker_number,
        x=pixel_x,
        y=pixel_y,
        category=category.strip(),
        common_name=common.strip(),
        scientific_name=scientific.strip(),
    )


def _location_id(connection: sqlite3.Connection, record: TransferRecord) -> int | None:
    """Reuse a unique name match unchanged or create a location within the import transaction.

    :param connection: Destination connection owned by the outer import transaction.
    :param record: Validated record with optional location details.
    :return: Location ID, or None if the record has no location.
    :raises ValueError: If several saved locations match the case-insensitive name.
    """
    if not record.location:
        return None
    matches = [
        row[0]
        for row in connection.execute("SELECT Id, Name FROM LOCATION")
        if row[1].casefold() == record.location.casefold()
    ]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous location name {record.location!r}.")
    if matches:
        return matches[0]
    cursor = connection.execute(
        "INSERT INTO LOCATION (Name, Region, Country, Latitude, Longitude) VALUES (?, ?, ?, ?, ?)",
        (record.location, record.region, record.country, record.latitude, record.longitude),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _folder_id(connection: sqlite3.Connection, record: TransferRecord) -> int:
    """Preserve saved folder metadata, filling only a missing location assignment.

    :param connection: Destination connection owned by the outer import transaction.
    :param record: Validated record with a resolved folder path and its metadata.
    :return: Existing or newly created folder ID.
    """
    row = connection.execute(
        "SELECT Id, LocationId FROM FOLDER WHERE Path=?", (record.folder,)
    ).fetchone()
    if row:
        if row[1] is None and record.location:
            connection.execute(
                "UPDATE FOLDER SET LocationId=? WHERE Id=?",
                (_location_id(connection, record), row[0]),
            )
        return row[0]
    location_id = _location_id(connection, record)
    cursor = connection.execute(
        "INSERT INTO FOLDER (Path, Date, LocationId) VALUES (?, ?, ?)",
        (record.folder, record.footage_date, location_id),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


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
    folder_id = _folder_id(connection, record)
    filename = record.image
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

    Existing folder dates, assigned locations and shared metadata are retained. Missing
    folder locations are filled from the file. Examination flags are merged.

    :param repository: Destination database.
    :param path: UTF-8 CSV previously exported by ReefTag.
    :return: Counts inserted and skipped; images counts newly inserted observations' images.
    :raises ValueError: If any row is malformed or conflicts with saved data.
    :raises OSError: If the source cannot be read.
    :raises sqlite3.Error: If persistence fails; all writes are rolled back.
    """
    summary = TransferSummary()
    images: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as stream, repository.connection:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != list(COLUMNS):
            raise ValueError(
                "CSV columns do not match the current ReefTag export format. "
                "Re-export using this version."
            )
        repository.connection.execute("BEGIN IMMEDIATE")
        for values in reader:
            try:
                record = _parse_record(values)
                if not _import_record(repository.connection, record):
                    summary.duplicates += 1
                    continue
            except ValueError as error:
                raise ValueError(f"CSV line {reader.line_num}: {error}") from error
            images.add((record.folder, record.image))
            if record.kind == "IDENTIFICATION":
                summary.identifications += 1
            else:
                summary.unknowns += 1
    summary.images = len(images)
    return summary
