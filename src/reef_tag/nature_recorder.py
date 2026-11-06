"""Transfer a day's identified species to an existing Nature Recorder database."""

import argparse
import logging
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferResult:
    """Counts of species and sightings created, and existing sightings skipped."""

    species_created: int
    sightings_created: int
    sightings_skipped: int


@dataclass(frozen=True)
class _Species:
    """Names and identity used to validate species from either database."""

    id: int
    common_name: str
    scientific_name: str
    category_name: str | None = None


def parse_date(value: str) -> date:
    """Parse a strict YYYY-MM-DD date.

    :param value: Calendar date to validate.
    :return: Parsed date.
    :raises ValueError: If the date is invalid or uses a different format.
    """
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Date must use YYYY-MM-DD format.")
    return parsed


def _open_database(path: Path, mode: str) -> sqlite3.Connection:
    """Open an existing database without creating or migrating it.

    :param path: Database file to open.
    :param mode: SQLite access mode, either ro or rw.
    :return: Connection with named rows and foreign keys enabled.
    :raises sqlite3.Error: If the existing database cannot be opened.
    """
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode={mode}", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _named_id(connection: sqlite3.Connection, table: str, name: str) -> int:
    """Resolve a unique case-insensitive location or category name.

    :param connection: Destination database connection.
    :param table: Internal table name, Locations or Categories.
    :param name: Name to look up.
    :return: Matching record ID.
    :raises ValueError: If there is no unique match.
    """
    # Table names are internal constants; user values are always bound parameters.
    rows = connection.execute(f'SELECT Id, Name FROM "{table}"').fetchall()
    matches = [row for row in rows if (row["Name"] or "").casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {table} entry named {name!r}; found {len(matches)}."
        )
    return matches[0]["Id"]


def _ensure_category(connection: sqlite3.Connection, name: str, stamp: str) -> int:
    """Reuse a unique case-insensitive category or create it with audit fields.

    :param connection: Destination connection inside the transfer transaction.
    :param name: Source category name.
    :param stamp: Current date at midnight for audit fields.
    :return: Destination category ID.
    :raises ValueError: If multiple destination categories match the name.
    """
    matches = [
        row["Id"]
        for row in connection.execute("SELECT Id, Name FROM Categories")
        if (row["Name"] or "").casefold() == name.casefold()
    ]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous category mapping for {name!r}.")
    if matches:
        return matches[0]
    cursor = connection.execute(
        "INSERT INTO Categories (Name, Created_By, Updated_By, Date_Created, Date_Updated) "
        "VALUES (?, 1, 1, ?, ?)",
        (name, stamp, stamp),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _match_species(source: _Species, targets: list[_Species]) -> int | None:
    """Match common name first, then scientific name.

    :param source: Species whose names must both agree with a match.
    :param targets: Existing species in any category.
    :return: Matching ID, or None when neither name matches.
    :raises ValueError: If names conflict or a match is ambiguous.
    """
    common = source.common_name.casefold()
    scientific = source.scientific_name.casefold()
    matches = [row for row in targets if row.common_name.casefold() == common]
    if not matches:
        matches = [row for row in targets if row.scientific_name.casefold() == scientific]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Ambiguous species mapping for {source.common_name!r}.")
    match = matches[0]
    if match.common_name.casefold() != common or match.scientific_name.casefold() != scientific:
        raise ValueError(f"Conflicting species names for {source.common_name!r}.")
    return match.id


def transfer(
    reef_tag_path: Path, nature_recorder_path: Path, location: str, recording_date: str
) -> TransferResult:
    """Atomically transfer distinct identified species for the selected image date.

    :param reef_tag_path: Existing ReefTag database, opened read-only.
    :param nature_recorder_path: Existing Nature Recorder database.
    :param location: Name of an existing destination location.
    :param recording_date: Date in strict YYYY-MM-DD format.
    :return: Counts of created records and skipped duplicate sightings.
    :raises ValueError: If inputs or species mappings are invalid or ambiguous.
    :raises sqlite3.Error: If database access fails; destination writes are rolled back.
    """
    selected_date = parse_date(recording_date).isoformat()
    species_messages: list[str] = []
    if not location.strip():
        raise ValueError("Location must not be blank.")
    if reef_tag_path.resolve() == nature_recorder_path.resolve():
        raise ValueError("Source and destination must be different database files.")
    with closing(_open_database(reef_tag_path, "ro")) as source:
        # Older source databases predate categories; preserve their Fish-only transfer.
        has_categories = any(
            row["name"] == "CategoryId" for row in source.execute("PRAGMA table_info(SPECIES)")
        )
        category_column = "c.Name" if has_categories else "'Fish'"
        category_join = "LEFT JOIN CATEGORY c ON c.Id=s.CategoryId" if has_categories else ""
        rows = source.execute(
            f"""SELECT DISTINCT s.Id, s.CommonName, s.ScientificName, {category_column}
               FROM SPECIES s
               JOIN IDENTIFICATION i ON i.SpeciesId = s.Id
               JOIN IMAGE im ON im.Id = i.ImageId
               {category_join}
               WHERE substr(im.Date, 1, 10) = ? ORDER BY s.Id""",
            (selected_date,),
        ).fetchall()
        species = [_Species(*row) for row in rows]
    with closing(_open_database(nature_recorder_path, "rw")) as destination:
        with destination:
            # Lock before reading mappings to prevent concurrent duplicate inserts.
            destination.execute("BEGIN IMMEDIATE")
            location_id = _named_id(destination, "Locations", location)
            targets = [
                _Species(row[0], row[1] or "", row[2] or "")
                for row in destination.execute("SELECT Id, Name, Scientific_Name FROM Species")
            ]
            mappings = [_match_species(row, targets) for row in species]
            # Source uniqueness is case-sensitive; reject case-only conflicting catalogue entries.
            unique_species: list[_Species] = []
            for row in species:
                if _match_species(row, unique_species) is None:
                    unique_species.append(row)
            stamp = f"{date.today().isoformat()} 00:00:00"
            created_species = created_sightings = skipped = 0
            for row, species_id in zip(species, mappings, strict=True):
                if species_id is None:
                    # Recheck against inserted rows for case-only aliases in the source catalogue.
                    species_id = _match_species(row, targets)
                if species_id is None:
                    if not row.category_name:
                        raise ValueError(
                            f"Select a category for {row.common_name!r} before transferring "
                            "a new species."
                        )
                    category_id = _ensure_category(destination, row.category_name, stamp)
                    cursor = destination.execute(
                        """INSERT INTO Species
                           (CategoryId, Name, Scientific_Name, Created_By, Updated_By,
                            Date_Created, Date_Updated) VALUES (?, ?, ?, 1, 1, ?, ?)""",
                        (category_id, row.common_name, row.scientific_name, stamp, stamp),
                    )
                    species_id = cursor.lastrowid
                    targets.append(_Species(species_id, row.common_name, row.scientific_name))
                    created_species += 1
                    species_messages.append(
                        f"Created species: {row.common_name} ({row.scientific_name}); "
                        f"ID {species_id}."
                    )
                else:
                    species_messages.append(
                        f"Skipped species: {row.common_name} ({row.scientific_name}); "
                        f"already exists as ID {species_id}."
                    )
                exists = destination.execute(
                    """SELECT 1 FROM Sightings WHERE LocationId = ? AND SpeciesId = ?
                       AND substr(Date, 1, 10) = ?""",
                    (location_id, species_id, selected_date),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                destination.execute(
                    """INSERT INTO Sightings
                       (LocationId, SpeciesId, Date, Number, WithYoung, Gender, Notes,
                        Created_By, Updated_By, Date_Created, Date_Updated)
                       VALUES (?, ?, ?, NULL, 0, 0, NULL, 1, 1, ?, ?)""",
                    (location_id, species_id, f"{selected_date} 00:00:00", stamp, stamp),
                )
                created_sightings += 1
    # Report committed changes only, so a rollback cannot leave misleading success messages.
    for message in species_messages:
        logger.info(message)
    return TransferResult(created_species, created_sightings, skipped)


def main(argv: list[str] | None = None) -> int:
    """Run the transfer command line interface.

    :param argv: Arguments to parse, or None to use the process arguments.
    :return: Zero on success or one on transfer failure.
    :raises SystemExit: For help or invalid command line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-r",
        "--reeftag-db",
        default=os.environ.get("REEFTAG_DB_PATH"),
        help="Existing ReefTag database (default: REEFTAG_DB_PATH).",
    )
    parser.add_argument(
        "-n",
        "--nature-recorder-db",
        default=os.environ.get("NATURE_RECORDER_DB"),
        help="Existing Nature Recorder database (default: NATURE_RECORDER_DB).",
    )
    parser.add_argument(
        "-l", "--location", required=True, help="Existing destination location name."
    )
    parser.add_argument("-d", "--date", required=True, help="Image recording date (YYYY-MM-DD).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.reeftag_db or not args.nature_recorder_db:
        parser.error("Supply both database paths using options or environment variables.")
    try:
        result = transfer(
            Path(args.reeftag_db), Path(args.nature_recorder_db), args.location, args.date
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"Transfer failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Created {result.species_created} species and {result.sightings_created} sightings; "
        f"skipped {result.sightings_skipped} existing sightings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
