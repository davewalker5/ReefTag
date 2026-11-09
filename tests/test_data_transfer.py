"""CSV round trips, geographical metadata, duplicate rules and atomic failure checks."""

import csv
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from reef_tag.data_transfer import COLUMNS, export_csv, folder_records, import_csv
from reef_tag.db import connect
from reef_tag.repositories import Repository


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[Repository]:
    """Provide an isolated migrated database."""
    connection = connect(tmp_path / "db.sqlite3")
    yield Repository(connection)
    connection.close()


def csv_row(
    folder: Path, image: str = "fish.png", changes: dict[str, str] | None = None
) -> list[str]:
    """Build a valid identification row with optional named field replacements."""
    fields = {
        "Date": "2026-10-13",
        "Folder": str(folder),
        "Location": "Reef",
        "Region": "Atoll",
        "Country": "Maldives",
        "Latitude": "3.88549",
        "Longitude": "72.72746",
        "Image": image,
        "Further Examination": "0",
        "Type": "IDENTIFICATION",
        "Number": "1",
        "X": "1",
        "Y": "2",
        "Category": "Fish",
        "Common Name": "A",
        "Scientific Name": "Alpha",
    }
    fields.update(changes or {})
    return [fields[column] for column in COLUMNS]


def unknown_row(folder: Path, image: str = "fish.png") -> list[str]:
    """Build an unknown row without species or identification number fields."""
    return csv_row(
        folder,
        image,
        {
            "Type": "UNKNOWN",
            "Number": "",
            "Category": "",
            "Common Name": "",
            "Scientific Name": "",
        },
    )


def write_rows(path: Path, rows: list[list[str]]) -> None:
    """Write test CSV rows with the published header."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def test_round_trip_and_duplicates(repository: Repository, tmp_path: Path) -> None:
    """Round-trip folder locations, names, categories, markers and examination flags."""
    assert COLUMNS == (
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
    first = tmp_path / "fish,é.png"
    repository.save_category("Fish, reef")
    category = repository.categories()[0]
    repository.create(
        first, date(2026, 10, 13), 42, 67, 'Fish "A"', "Alpha", category_id=category.id
    )
    repository.create_pending(first, date.today(), 99, 100)
    repository.create(tmp_path / "child" / "other.png", date.today(), 1, 2, "B", "Beta")
    repository.save_location("Reef, é", "South Ari Atoll", "Maldives", 3.88549, 72.72746)
    folder = next(item for item in repository.folders() if item.path == tmp_path)
    repository.save_folder(folder, tmp_path, folder.default_date, repository.locations()[0].id)
    records = folder_records(repository, tmp_path)
    path = tmp_path / "observations.csv"
    summary = export_csv(path, records)
    assert (summary.images, summary.identifications, summary.unknowns) == (1, 1, 1)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == list(COLUMNS)
    assert rows[1] == [
        "2026-10-13",
        str(tmp_path),
        "Reef, é",
        "South Ari Atoll",
        "Maldives",
        "3.88549",
        "72.72746",
        first.name,
        "1",
        "IDENTIFICATION",
        "1",
        "42",
        "67",
        "Fish, reef",
        'Fish "A"',
        "Alpha",
    ]
    assert rows[2][9:] == ["UNKNOWN", "", "99", "100", "", "", ""]
    destination = connect(tmp_path / "destination.sqlite3")
    target = Repository(destination)
    try:
        summary = import_csv(target, path)
        assert summary.identifications == summary.unknowns == 1
        assert target.image_date(first) == date(2026, 10, 13)
        assert target.identifications(first)[0].species.common_name == 'Fish "A"'
        assert target.categories()[0].name == "Fish, reef"
        assert target.locations()[0].name == "Reef, é"
        assert target.folders()[0].location_id == target.locations()[0].id
        assert target.pending_identifications(first)[0].x == 99
        assert str(first) in target.further_examination_images()
        repeated = import_csv(target, path)
        assert repeated.duplicates == 2
        assert repeated.identifications == repeated.unknowns == repeated.images == 0
        assert len(target.locations()) == len(target.folders()) == 1
        assert folder_records(target, tmp_path) == records
    finally:
        destination.close()


def test_input_duplicates_and_unknown_flag(repository: Repository, tmp_path: Path) -> None:
    """Skip duplicates within the file, retaining marker identity and setting examination."""
    path = tmp_path / "in.csv"
    identification = csv_row(tmp_path, changes={"Number": "7"})
    unknown = unknown_row(tmp_path)
    write_rows(path, [identification, identification, unknown, unknown])
    summary = import_csv(repository, path)
    assert summary.duplicates == 2
    assert summary.identifications == summary.unknowns == 1
    assert repository.identifications(tmp_path / "fish.png")[0].number == 7
    assert str(tmp_path / "fish.png") in repository.further_examination_images()


@pytest.mark.parametrize(
    "field,value",
    [
        ("Date", "20261013"),
        ("Date", "2026-02-30"),
        ("Folder", "relative"),
        ("Folder", ""),
        ("Folder", "/bad\0path"),
        ("Image", "/full/path.png"),
        ("Image", "nested/fish.png"),
        ("Image", "nested\\fish.png"),
        ("Image", ".."),
        ("Image", "."),
        ("Image", ""),
        ("Image", "bad\0image"),
        ("Further Examination", "maybe"),
        ("Type", "OTHER"),
        ("Number", "0"),
        ("X", "-1"),
        ("Y", "nan"),
        ("Scientific Name", ""),
        ("Latitude", "90.1"),
        ("Latitude", "-90.1"),
        ("Latitude", "nan"),
        ("Longitude", "inf"),
        ("Longitude", "-180.1"),
        ("Longitude", "180.1"),
        ("Latitude", "invalid"),
        ("Region", ""),
        ("Country", ""),
        ("Location", ""),
    ],
)
def test_invalid_row_rolls_back(
    repository: Repository,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Reject malformed rows and roll back earlier locations, folders, images and species."""
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path, "a.png"), csv_row(tmp_path, "b.png", {field: value})])
    with pytest.raises(ValueError, match="CSV line 3"):
        import_csv(repository, path)
    assert repository.image_paths() == {}
    assert repository.species() == []
    assert repository.categories() == []
    assert repository.locations() == []
    assert repository.folders() == ()


def test_number_conflict_rolls_back(repository: Repository, tmp_path: Path) -> None:
    """Do not silently skip or renumber an existing number at a different position."""
    image = tmp_path / "fish.png"
    repository.create(image, date(2026, 10, 13), 1, 2, "A", "Alpha")
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            csv_row(
                tmp_path,
                changes={
                    "Date": "2026-10-14",
                    "Further Examination": "1",
                    "X": "3",
                    "Y": "4",
                    "Common Name": "B",
                    "Scientific Name": "Beta",
                },
            )
        ],
    )
    with pytest.raises(ValueError, match="different position"):
        import_csv(repository, path)
    assert repository.image_date(image) == date(2026, 10, 13)
    assert str(image) not in repository.further_examination_images()
    assert len(repository.species()) == 1
    assert repository.folders()[0].location_id is None
    assert repository.locations() == []


def test_existing_metadata_retained(repository: Repository, tmp_path: Path) -> None:
    """Retain folder dates, assigned locations, location details and species categories."""
    image = tmp_path / "fish.png"
    repository.save_category("Existing")
    category = repository.categories()[0]
    repository.create(image, date(2026, 10, 13), 1, 2, "A", "Alpha", category_id=category.id)
    repository.save_location("Saved", "Saved region", "Saved country", 1, 2)
    location = repository.locations()[0]
    folder = repository.folders()[0]
    repository.save_folder(folder, tmp_path, folder.default_date, location.id)
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            csv_row(
                tmp_path,
                changes={
                    "Date": "2026-10-14",
                    "Number": "9",
                    "X": "3",
                    "Y": "4",
                    "Category": "Different",
                },
            )
        ],
    )
    import_csv(repository, path)
    assert repository.image_date(image) == date(2026, 10, 13)
    assert repository.species()[0].category_id == category.id
    assert len(repository.categories()) == 1
    assert repository.locations() == [location]
    assert repository.folders()[0].location_id == location.id


def test_species_conflict_rolls_back(repository: Repository, tmp_path: Path) -> None:
    """Conflicting catalogue names reject an import without creating locations or images."""
    repository.create(tmp_path / "existing.png", date.today(), 1, 2, "A", "Alpha")
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path, "new.png", {"Scientific Name": "Beta"})])
    with pytest.raises(ValueError, match="Species names conflict"):
        import_csv(repository, path)
    assert len(repository.image_paths()) == len(repository.species()) == 1
    assert repository.categories() == []
    assert repository.locations() == []


def test_invalid_headers(repository: Repository, tmp_path: Path) -> None:
    """Reject empty, reordered or older CSV formats with guidance to re-export."""
    path = tmp_path / "in.csv"
    for content in (
        "",
        "Image,Date\n",
        "Date,Image,Further Examination,Type,Number,X,Y,Category,Common Name,Scientific Name\n",
    ):
        path.write_text(content)
        with pytest.raises(ValueError, match="columns"):
            import_csv(repository, path)
    assert repository.image_paths() == {}


def test_unlocated_folder_round_trip(repository: Repository, tmp_path: Path) -> None:
    """Export blank geography fields and import unlocated folders without creating locations."""
    image = tmp_path / "missing.png"
    repository.create_pending(image, date(2026, 10, 13), 1, 2)
    records = folder_records(repository, tmp_path)
    path = tmp_path / "blank-location.csv"
    export_csv(path, records)
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[1][2:7] == ["", "", "", "", ""]
    target_connection = connect(tmp_path / "target.db")
    try:
        target = Repository(target_connection)
        import_csv(target, path)
        assert target.locations() == []
        assert target.folders()[0].location_id is None
        assert folder_records(target, tmp_path) == records
    finally:
        target_connection.close()


@pytest.mark.parametrize(
    "latitude,longitude,expected",
    [
        ("", "", (None, None)),
        ("", "180", (None, 180)),
        ("-90", "", (-90, None)),
        ("0", "0", (0, 0)),
        ("-90", "-180", (-90, -180)),
        ("90", "180", (90, 180)),
    ],
)
def test_optional_coordinates_round_trip(
    repository: Repository,
    tmp_path: Path,
    latitude: str,
    longitude: str,
    expected: tuple[float | None, float | None],
) -> None:
    """Retain blank, zero and boundary coordinates across import and export."""
    path = tmp_path / "coordinates.csv"
    write_rows(path, [csv_row(tmp_path, changes={"Latitude": latitude, "Longitude": longitude})])
    import_csv(repository, path)
    location = repository.locations()[0]
    assert (location.latitude, location.longitude) == expected
    export_csv(path, folder_records(repository, tmp_path))
    with path.open(newline="") as stream:
        row = list(csv.reader(stream))[1]
    assert (
        None if not row[5] else float(row[5]),
        None if not row[6] else float(row[6]),
    ) == expected
    assert import_csv(repository, path).duplicates == 1
    assert len(repository.locations()) == 1


def test_named_locations_reused_without_updates(repository: Repository, tmp_path: Path) -> None:
    """Reuse a location across folders by case-insensitive name and retain all saved details."""
    repository.save_location("Reef", "Saved region", "Saved country", 1, 2)
    location = repository.locations()[0]
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            csv_row(tmp_path / "one", changes={"Location": "reef"}),
            csv_row(tmp_path / "two", changes={"Location": "REEF"}),
        ],
    )
    summary = import_csv(repository, path)
    assert summary.images == 2
    assert repository.locations() == [location]
    assert {folder.location_id for folder in repository.folders()} == {location.id}


def test_missing_folder_location_is_filled(repository: Repository, tmp_path: Path) -> None:
    """Fill a missing assignment even on a duplicate marker without changing the saved date."""
    repository.create(tmp_path / "fish.png", date(2026, 10, 10), 1, 2, "A", "Alpha")
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path)])
    summary = import_csv(repository, path)
    assert summary.duplicates == 1
    assert summary.images == summary.identifications == 0
    assert repository.folders()[0].location_id == repository.locations()[0].id
    assert repository.folder_date(tmp_path) == date(2026, 10, 10)


def test_first_folder_metadata_is_retained(repository: Repository, tmp_path: Path) -> None:
    """Repeated rows for a folder retain the first date and nonblank location assignment."""
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            csv_row(tmp_path, "one.png"),
            csv_row(
                tmp_path,
                "two.png",
                {
                    "Date": "2026-10-14",
                    "Location": "Other reef",
                    "Region": "Other region",
                },
            ),
        ],
    )
    summary = import_csv(repository, path)
    assert summary.images == 2
    assert repository.folder_date(tmp_path) == date(2026, 10, 13)
    assert [location.name for location in repository.locations()] == ["Reef"]


def test_same_filename_in_different_folders(repository: Repository, tmp_path: Path) -> None:
    """Keep image and marker identities separate when only their folder paths differ."""
    first, second = tmp_path / "one", tmp_path / "two"
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(first), csv_row(second, changes={"X": "3", "Date": "2026-10-14"})])
    summary = import_csv(repository, path)
    assert summary.images == summary.identifications == 2
    assert repository.identifications(first / "fish.png")[0].x == 1
    assert repository.identifications(second / "fish.png")[0].x == 3
    records = folder_records(repository, first) + folder_records(repository, second)
    assert export_csv(path, records).images == 2
    assert import_csv(repository, path).duplicates == 2
    assert len(repository.image_paths()) == 2


def test_export_uses_current_shared_location_details(
    repository: Repository, tmp_path: Path
) -> None:
    """Export current folder and location metadata after shared fields are edited."""
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path)])
    import_csv(repository, path)
    location = repository.locations()[0]
    repository.save_location("Renamed", "New region", "New country", None, 0, location.id)
    repository.save_folder_date(tmp_path, date(2026, 10, 15))
    record = folder_records(repository, tmp_path)[0]
    assert record.footage_date == "2026-10-15"
    assert (record.folder, record.image) == (str(tmp_path), "fish.png")
    assert (record.location, record.region, record.country) == (
        "Renamed",
        "New region",
        "New country",
    )
    assert record.latitude is None
    assert record.longitude == 0


def test_ambiguous_location_rolls_back(repository: Repository, tmp_path: Path) -> None:
    """Reject ambiguous name matches without retaining any preceding imported records."""
    repository.save_location("Reef", "Region", "Country")
    repository.save_location("REEF", "Other", "Country")
    original = repository.locations()
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [csv_row(tmp_path / "one", changes={"Location": "New reef"}), csv_row(tmp_path / "two")],
    )
    with pytest.raises(ValueError, match="CSV line 3: Ambiguous location"):
        import_csv(repository, path)
    assert repository.locations() == original
    assert repository.folders() == ()
    assert repository.image_paths() == {}
    assert repository.species() == []
    assert repository.categories() == []


def test_database_failure_rolls_back_geography(repository: Repository, tmp_path: Path) -> None:
    """A marker write failure rolls back locations, folders, images, categories and species."""
    repository.connection.execute("""
        CREATE TRIGGER reject_marker BEFORE INSERT ON IDENTIFICATION
        BEGIN SELECT RAISE(ABORT, 'marker rejected'); END;
    """)
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path)])
    with pytest.raises(sqlite3.IntegrityError, match="marker rejected"):
        import_csv(repository, path)
    assert repository.locations() == []
    assert repository.folders() == ()
    assert repository.image_paths() == {}
    assert repository.species() == []
    assert repository.categories() == []


@pytest.mark.parametrize("field", ["Number", "Category", "Common Name", "Scientific Name"])
def test_unknown_fields_must_be_blank(repository: Repository, tmp_path: Path, field: str) -> None:
    """Reject species or numbered-identification data attached to an unknown marker."""
    row = unknown_row(tmp_path)
    row[COLUMNS.index(field)] = "unexpected"
    path = tmp_path / "in.csv"
    write_rows(path, [row])
    with pytest.raises(ValueError, match="Unknown markers require blank"):
        import_csv(repository, path)
    assert repository.locations() == []


def test_utf8_bom_and_malformed_rows(repository: Repository, tmp_path: Path) -> None:
    """Accept a UTF-8 BOM and reject incorrect row lengths or broken quoting atomically."""
    path = tmp_path / "in.csv"
    write_rows(path, [csv_row(tmp_path)])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert import_csv(repository, path).identifications == 1
    before = list(repository.connection.iterdump())
    write_rows(path, [csv_row(tmp_path, "new.png"), ["too", "short"]])
    with pytest.raises(ValueError, match="Expected 16 columns"):
        import_csv(repository, path)
    assert list(repository.connection.iterdump()) == before
    write_rows(path, [csv_row(tmp_path, "new.png")])
    with path.open("a") as stream:
        stream.write('"unterminated')
    with pytest.raises(csv.Error):
        import_csv(repository, path)
    assert list(repository.connection.iterdump()) == before
