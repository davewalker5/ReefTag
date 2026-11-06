"""CSV round trips, duplicate rules and atomic failure checks."""

import csv
from datetime import date
from pathlib import Path

import pytest

from reef_tag.data_transfer import COLUMNS, export_csv, folder_records, import_csv
from reef_tag.db import connect
from reef_tag.repositories import Repository


@pytest.fixture
def repository(tmp_path: Path):
    """Provide an isolated migrated database."""
    connection = connect(tmp_path / "db.sqlite3")
    yield Repository(connection)
    connection.close()


def write_rows(path: Path, rows: list[list[str]]) -> None:
    """Write test CSV rows with the published header."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def test_round_trip_and_duplicates(repository: Repository, tmp_path: Path) -> None:
    """Preserve dates, names, categories, numbers, coordinates and examination flags."""
    first = tmp_path / "fish,é.png"
    repository.save_category("Fish, reef")
    category = repository.categories()[0]
    repository.create(
        first, date(2026, 10, 13), 42, 67, 'Fish "A"', "Alpha", category_id=category.id
    )
    repository.create_pending(first, date.today(), 99, 100)
    repository.create(tmp_path / "child" / "other.png", date.today(), 1, 2, "B", "Beta")
    records = folder_records(repository, tmp_path)
    path = tmp_path / "observations.csv"
    summary = export_csv(path, records)
    assert (summary.images, summary.identifications, summary.unknowns) == (1, 1, 1)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == list(COLUMNS)
    assert rows[2][4] == ""
    destination = connect(tmp_path / "destination.sqlite3")
    target = Repository(destination)
    try:
        summary = import_csv(target, path)
        assert summary.identifications == summary.unknowns == 1
        assert target.image_date(first) == date(2026, 10, 13)
        assert target.identifications(first)[0].number == 1
        assert target.identifications(first)[0].species.common_name == 'Fish "A"'
        assert target.categories()[0].name == "Fish, reef"
        assert target.pending_identifications(first)[0].x == 99
        assert str(first) in target.further_examination_images()
        repeated = import_csv(target, path)
        assert repeated.duplicates == 2
        assert repeated.identifications == repeated.unknowns == repeated.images == 0
        assert folder_records(target, tmp_path) == records
    finally:
        destination.close()


def test_input_duplicates_and_unknown_flag(repository: Repository, tmp_path: Path) -> None:
    """Skip duplicates within the file, even with differing non-key fields."""
    image = str(tmp_path / "fish.png")
    path = tmp_path / "in.csv"
    identification = ["2026-10-13", image, "0", "IDENTIFICATION", "7", "1", "2", "", "A", "Alpha"]
    unknown = ["2026-10-13", image, "0", "UNKNOWN", "", "1", "2", "", "", ""]
    write_rows(path, [identification, identification, unknown, unknown])
    summary = import_csv(repository, path)
    assert summary.duplicates == 2
    assert summary.identifications == summary.unknowns == 1
    assert repository.identifications(Path(image))[0].number == 7
    assert image in repository.further_examination_images()


@pytest.mark.parametrize(
    "field,value",
    [(0, "20261013"), (2, "maybe"), (3, "OTHER"), (4, "0"), (5, "-1"), (6, "nan"), (9, "")],
)
def test_invalid_row_rolls_back(
    repository: Repository, tmp_path: Path, field: int, value: str
) -> None:
    """Reject invalid rows without leaving even earlier valid rows in the database."""
    good = [
        "2026-10-13",
        str(tmp_path / "a.png"),
        "0",
        "IDENTIFICATION",
        "1",
        "1",
        "2",
        "Fish",
        "A",
        "Alpha",
    ]
    bad = good.copy()
    bad[field] = value
    path = tmp_path / "in.csv"
    write_rows(path, [good, bad])
    with pytest.raises(ValueError, match="CSV line 3"):
        import_csv(repository, path)
    assert repository.image_paths() == {}
    assert repository.species() == []
    assert repository.categories() == []


def test_number_conflict_rolls_back(repository: Repository, tmp_path: Path) -> None:
    """A reused number at a different position must not be silently skipped or renumbered."""
    image = tmp_path / "a.png"
    repository.create(image, date(2026, 10, 13), 1, 2, "A", "Alpha")
    path = tmp_path / "in.csv"
    write_rows(
        path, [["2026-10-14", str(image), "1", "IDENTIFICATION", "1", "3", "4", "", "B", "Beta"]]
    )
    with pytest.raises(ValueError, match="different position"):
        import_csv(repository, path)
    assert repository.image_date(image) == date(2026, 10, 13)
    assert str(image) not in repository.further_examination_images()
    assert len(repository.species()) == 1


def test_existing_metadata_retained(repository: Repository, tmp_path: Path) -> None:
    """Adding observations retains existing image dates and shared species categories."""
    image = tmp_path / "a.png"
    repository.save_category("Existing")
    category = repository.categories()[0]
    repository.create(image, date(2026, 10, 13), 1, 2, "A", "Alpha", category_id=category.id)
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            [
                "2026-10-14",
                str(image),
                "0",
                "IDENTIFICATION",
                "9",
                "3",
                "4",
                "Different",
                "A",
                "Alpha",
            ]
        ],
    )
    import_csv(repository, path)
    assert repository.image_date(image) == date(2026, 10, 13)
    assert repository.species()[0].category_id == category.id
    assert len(repository.categories()) == 1


def test_species_conflict_rolls_back(repository: Repository, tmp_path: Path) -> None:
    """Conflicting catalogue names reject the import without creating a new image."""
    repository.create(tmp_path / "existing.png", date.today(), 1, 2, "A", "Alpha")
    path = tmp_path / "in.csv"
    write_rows(
        path,
        [
            [
                "2026-10-13",
                str(tmp_path / "new.png"),
                "0",
                "IDENTIFICATION",
                "1",
                "3",
                "4",
                "Fish",
                "A",
                "Beta",
            ]
        ],
    )
    with pytest.raises(ValueError, match="Species names conflict"):
        import_csv(repository, path)
    assert len(repository.image_paths()) == len(repository.species()) == 1
    assert repository.categories() == []


def test_invalid_headers(repository: Repository, tmp_path: Path) -> None:
    """Fail clearly when the file is empty or uses a different column layout."""
    path = tmp_path / "in.csv"
    for content in ("", "Image,Date\n"):
        path.write_text(content)
        with pytest.raises(ValueError, match="columns"):
            import_csv(repository, path)
    assert repository.image_paths() == {}
