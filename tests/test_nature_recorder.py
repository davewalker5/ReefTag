"""Acceptance tests for atomic, repeatable Nature Recorder transfers."""

import logging
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from reef_tag.db import connect
from reef_tag.nature_recorder import TransferResult, main, parse_date, transfer

DAY = "2026-10-13"


def test_species_logging(databases: tuple[Path, Path], caplog: pytest.LogCaptureFixture) -> None:
    """Report committed species creations and skips with their names and IDs."""
    source, target = databases
    caplog.set_level(logging.INFO, logger="reef_tag.nature_recorder")
    transfer(source, target, DAY)
    assert caplog.messages == [
        "Created species: Fish A (Species alpha); ID 1.",
        "Created species: Fish B (Species beta); ID 2.",
    ]
    caplog.clear()
    transfer(source, target, DAY)
    assert caplog.messages == [
        "Skipped species: Fish A (Species alpha); already exists as ID 1.",
        "Skipped species: Fish B (Species beta); already exists as ID 2.",
    ]


@pytest.fixture
def databases(tmp_path: Path) -> tuple[Path, Path]:
    """Create source annotations and a destination using the brief's exact DDL."""
    source = tmp_path / "reef.db"
    target = tmp_path / "nature.db"
    root = Path(__file__).resolve().parents[1]
    connection = connect(source)
    with connection:
        connection.executescript("""
            INSERT INTO LOCATION (Id, Name, Region, Country)
                VALUES (1, 'Reef', 'Atoll', 'Maldives');
            INSERT INTO FOLDER VALUES (1, '/photos/day1', '2026-10-13', 1),
                (2, '/photos/day2', '2026-10-13 12:00:00', 1),
                (3, '/photos/next', '2026-10-14', 1);
            INSERT INTO IMAGE VALUES (1, 'one.png', 0, 1),
                (2, 'two.png', 0, 2), (3, 'other.png', 0, 3);
            INSERT INTO CATEGORY VALUES (1, 'Fish');
            INSERT INTO SPECIES VALUES (1, 'Fish A', 'Species alpha', 1),
                (2, 'Fish B', 'Species beta', 1), (3, 'Unused', 'Unused species', 1);
            INSERT INTO IDENTIFICATION VALUES (1,1,1,1,0,0), (2,1,1,2,0,0),
                (3,2,2,1,0,0), (4,3,3,1,0,0);
        """)
    connection.close()
    brief = root / "docs/Project Briefs/Project Brief - Nature Recorder Data Transfer.md"
    schemas = brief.read_text().split("```sql\n")[1:]
    with sqlite3.connect(target) as connection:
        for schema in schemas:
            connection.executescript(schema.split("```")[0])
        connection.executescript("""
            INSERT INTO Categories (Id, Name) VALUES (1, 'Fish'), (2, 'Other');
            INSERT INTO Locations (Id, Name) VALUES (1, 'Reef'), (2, 'Elsewhere');
        """)
    return source, target


def test_transfer_and_repeat(databases: tuple[Path, Path]) -> None:
    """Transfer distinct species for the day and populate all requested fields."""
    source, target = databases
    before = source.read_bytes()
    assert transfer(source, target, DAY) == TransferResult(2, 2, 0)
    stamp = f"{date.today()} 00:00:00"
    with sqlite3.connect(target) as connection:
        rows = connection.execute("SELECT * FROM Sightings ORDER BY SpeciesId").fetchall()
        assert rows == [
            (1, 1, 1, f"{DAY} 00:00:00", None, 0, 0, None, 1, 1, stamp, stamp),
            (2, 1, 2, f"{DAY} 00:00:00", None, 0, 0, None, 1, 1, stamp, stamp),
        ]
        assert connection.execute("SELECT CategoryId FROM Species").fetchall() == [(1,), (1,)]
        assert connection.execute("SELECT Created_By, Updated_By FROM Species").fetchall() == [
            (1, 1),
            (1, 1),
        ]
        connection.execute("UPDATE Sightings SET Date = substr(Date, 1, 10) || ' 15:30:00'")
    assert transfer(source, target, DAY) == TransferResult(0, 0, 2)
    assert source.read_bytes() == before


def test_existing_non_fish_species(databases: tuple[Path, Path]) -> None:
    """Reuse manually prepared species from any category, ignoring name case."""
    source, target = databases
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO Species (CategoryId, Name, Scientific_Name) VALUES (2, ?, ?)",
            ("FISH A", "SPECIES ALPHA"),
        )
    assert transfer(source, target, DAY) == TransferResult(1, 2, 0)


@pytest.mark.parametrize(
    "common,scientific",
    [("Fish B", "Wrong"), ("Wrong", "Species beta")],
)
def test_conflicting_mapping_is_atomic(
    databases: tuple[Path, Path], common: str, scientific: str
) -> None:
    """Reject a late conflict by either name before inserting any missing species."""
    source, target = databases
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO Species (CategoryId, Name, Scientific_Name) VALUES (1, ?, ?)",
            (common, scientific),
        )
    with pytest.raises(ValueError, match="Conflicting"):
        transfer(source, target, DAY)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Species").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM Sightings").fetchone()[0] == 0


def test_write_failure_rolls_back(databases: tuple[Path, Path]) -> None:
    """Rollback earlier species and sightings if a subsequent write fails."""
    source, target = databases
    with sqlite3.connect(target) as connection:
        connection.executescript("""
            CREATE TRIGGER reject_second BEFORE INSERT ON Sightings WHEN NEW.SpeciesId = 2
            BEGIN SELECT RAISE(ABORT, 'simulated failure'); END;
        """)
    with pytest.raises(sqlite3.IntegrityError):
        transfer(source, target, DAY)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Species").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM Sightings").fetchone()[0] == 0


@pytest.mark.parametrize("value", ["20261013", "2026-1-13", "2026-02-30", "2026-10-13T12:00:00"])
def test_strict_dates(value: str) -> None:
    """Reject noncanonical and impossible calendar dates."""
    with pytest.raises(ValueError):
        parse_date(value)


def test_missing_inputs(databases: tuple[Path, Path], tmp_path: Path) -> None:
    """Reject missing databases and identical source/target paths without creating files."""
    source, target = databases
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        transfer(source, missing, DAY)
    assert not missing.exists()
    with pytest.raises(ValueError, match="different"):
        transfer(source, source, DAY)


def test_cli_environment_and_options(
    databases: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Support environment defaults, both option forms, and readable failures."""
    source, target = databases
    monkeypatch.setenv("REEFTAG_DB_PATH", str(source))
    monkeypatch.setenv("NATURE_RECORDER_DB", str(target))
    assert main(["-d", DAY]) == 0
    assert "Created 2 species and 2 sightings" in capsys.readouterr().out
    assert (
        main(
            [
                "--reeftag-db",
                str(source),
                "--nature-recorder-db",
                str(target),
                "--date",
                DAY,
            ]
        )
        == 0
    )
    assert main(["-d", "invalid"]) == 1
    assert "Transfer failed" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([])


def test_category_aware_transfer(databases: tuple[Path, Path]) -> None:
    """Create categories once with audit values and match names without case."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            INSERT INTO CATEGORY VALUES (2, 'Molluscs');
            UPDATE CATEGORY SET Name='fish' WHERE Id=1;
            UPDATE SPECIES SET CategoryId=2 WHERE Id=1;
        """)
    assert transfer(source, target, DAY) == TransferResult(2, 2, 0)
    with sqlite3.connect(target) as connection:
        stamp = f"{date.today()} 00:00:00"
        assert connection.execute(
            "SELECT Created_By, Updated_By, Date_Created, Date_Updated, Supports_Gender "
            "FROM Categories WHERE Name='Molluscs'"
        ).fetchone() == (1, 1, stamp, stamp, 1)
        assert connection.execute(
            "SELECT c.Name FROM Species s JOIN Categories c ON c.Id=s.CategoryId ORDER BY s.Id"
        ).fetchall() == [("Molluscs",), ("Fish",)]
    assert transfer(source, target, DAY) == TransferResult(0, 0, 2)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Categories").fetchone()[0] == 3


def test_uncategorized_transfer_rolls_back(databases: tuple[Path, Path]) -> None:
    """Require a category for new species and roll back earlier category inserts."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            INSERT INTO CATEGORY VALUES (2, 'Molluscs');
            UPDATE SPECIES SET CategoryId=2 WHERE Id=1;
            UPDATE SPECIES SET CategoryId=NULL WHERE Id=2;
        """)
    with pytest.raises(ValueError, match="Select a category"):
        transfer(source, target, DAY)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Categories").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM Species").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM Sightings").fetchone()[0] == 0


def test_transfer_uses_folder_dates(databases: tuple[Path, Path], tmp_path: Path) -> None:
    """Select observations by their folder recording date and assigned location."""
    from reef_tag.repositories import Repository

    _, target = databases
    source = tmp_path / "phase3.db"
    connection = connect(source)
    repository = Repository(connection)
    repository.save_category("Fish")
    category_id = repository.categories()[0].id
    folder = tmp_path / "photos"
    repository.create(
        folder / "a.png", date(2026, 10, 13), 1, 2, "A", "Alpha", category_id=category_id
    )
    repository.create(
        folder / "b.png", date(2026, 10, 14), 1, 2, "B", "Beta", category_id=category_id
    )
    repository.save_location("Reef", "Atoll", "Maldives")
    snapshot = repository.folders()[0]
    repository.save_folder(snapshot, folder, date(2026, 10, 15), repository.locations()[0].id)
    connection.close()
    before = source.read_bytes()
    assert transfer(source, target, DAY) == TransferResult(0, 0, 0)
    assert transfer(source, target, "2026-10-15") == TransferResult(2, 2, 0)
    assert source.read_bytes() == before


def test_multiple_folder_locations(
    databases: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    """Deduplicate within a location while retaining sightings of the same species elsewhere."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            INSERT INTO LOCATION VALUES (2, 'Lagoon', 'South Atoll', 'Maldives', -3.5, 72.7);
            INSERT INTO LOCATION VALUES (3, 'Unused location', 'Region', 'Country', NULL, NULL);
            INSERT INTO FOLDER VALUES (4, '/photos/lagoon', '2026-10-13', 2),
                (5, '/photos/also-reef', '2026-10-13', 1),
                (6, '/photos/unknowns', '2026-10-13', 3);
            INSERT INTO IMAGE VALUES (4, 'four.png', 0, 4), (5, 'five.png', 0, 5),
                (6, 'six.png', 1, 6);
            INSERT INTO IDENTIFICATION VALUES (5,4,1,1,1,2), (6,5,1,1,3,4);
            INSERT INTO PENDING_IDENTIFICATION VALUES (1,6,5,6);
        """)
    before = source.read_bytes()
    caplog.set_level(logging.INFO, logger="reef_tag.nature_recorder")
    assert transfer(source, target, DAY) == TransferResult(2, 3, 0)
    assert len(caplog.messages) == 2
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT l.Name, s.Name FROM Sightings si JOIN Locations l ON l.Id=si.LocationId "
            "JOIN Species s ON s.Id=si.SpeciesId ORDER BY l.Name, s.Name"
        ).fetchall() == [("Lagoon", "Fish A"), ("Reef", "Fish A"), ("Reef", "Fish B")]
        assert (
            connection.execute("SELECT 1 FROM Locations WHERE Name='Unused location'").fetchone()
            is None
        )
    assert transfer(source, target, DAY) == TransferResult(0, 0, 3)
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "coordinates", [(3.88549, 72.72746), (-90, -180), (0, 0), (None, None), (None, 10), (10, None)]
)
def test_new_location_mapping(
    databases: tuple[Path, Path], coordinates: tuple[float | None, float | None]
) -> None:
    """Map all geographical and audit fields, including independent optional coordinates."""
    source, target = databases
    latitude, longitude = coordinates
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE LOCATION SET Name=?, Region=?, Country=?, Latitude=?, Longitude=? WHERE Id=1",
            ("Constance Moofushi", "South Ari Atoll", "Maldives", latitude, longitude),
        )
    assert transfer(source, target, DAY) == TransferResult(2, 2, 0)
    with sqlite3.connect(target) as connection:
        row = connection.execute(
            "SELECT Name, County, Country, Latitude, Longitude, Created_By, Updated_By, "
            "Date_Created, Date_Updated, Address, City, Postcode FROM Locations "
            "WHERE Name='Constance Moofushi'"
        ).fetchone()
        assert row[:3] == ("Constance Moofushi", "South Ari Atoll", "Maldives")
        assert (None if row[3] is None else float(row[3])) == latitude
        assert (None if row[4] is None else float(row[4])) == longitude
        stamp = f"{date.today()} 00:00:00"
        assert row[5:] == (1, 1, stamp, stamp, None, None, None)
    assert transfer(source, target, DAY) == TransferResult(0, 0, 2)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Locations").fetchone()[0] == 3


@pytest.mark.parametrize("source_name,target_name", [("reef", "Reef"), ("Straße", "STRASSE")])
def test_existing_location_is_unchanged(
    databases: tuple[Path, Path],
    source_name: str,
    target_name: str,
) -> None:
    """Reuse case-insensitive names without overwriting any stored location fields."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE LOCATION SET Name=?, Latitude=42, Longitude=72", (source_name,))
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE Locations SET Name=?, County='Existing county', Country='Existing country', "
            "Latitude='1.25', Longitude='2.5', Updated_By=9, Date_Updated='2020-01-01' WHERE Id=1",
            (target_name,),
        )
        before = connection.execute("SELECT * FROM Locations ORDER BY Id").fetchall()
    assert transfer(source, target, DAY) == TransferResult(2, 2, 0)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT * FROM Locations ORDER BY Id").fetchall() == before
        assert connection.execute("SELECT DISTINCT LocationId FROM Sightings").fetchall() == [(1,)]


@pytest.mark.parametrize("all_unlocated", [False, True])
def test_folders_without_location_are_excluded(
    databases: tuple[Path, Path],
    all_unlocated: bool,
) -> None:
    """Unlocated folders do not create locations, species, categories or sightings."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        if all_unlocated:
            connection.execute("UPDATE FOLDER SET LocationId=NULL")
        else:
            connection.execute("UPDATE FOLDER SET LocationId=NULL WHERE Id=2")
        # This would fail species matching if unlocated observations were still included.
        connection.execute("UPDATE SPECIES SET CategoryId=NULL WHERE Id=2")
    with sqlite3.connect(target) as connection:
        before_locations = connection.execute("SELECT * FROM Locations").fetchall()
        before_categories = connection.execute("SELECT * FROM Categories").fetchall()
    count = 0 if all_unlocated else 1
    assert transfer(source, target, DAY) == TransferResult(count, count, 0)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT * FROM Locations").fetchall() == before_locations
        assert connection.execute("SELECT * FROM Categories").fetchall() == before_categories
        assert connection.execute("SELECT COUNT(*) FROM Species").fetchone()[0] == count
        assert connection.execute("SELECT COUNT(*) FROM Sightings").fetchone()[0] == count


@pytest.mark.parametrize("failure", ["ambiguous", "location-write", "sighting-write"])
def test_location_failures_roll_back_entire_transfer(
    databases: tuple[Path, Path],
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """Late location or sighting failures roll back categories, species and new locations."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            INSERT INTO CATEGORY VALUES (2, 'Molluscs');
            UPDATE SPECIES SET CategoryId=2 WHERE Id=1;
            UPDATE LOCATION SET Name='New reef' WHERE Id=1;
            INSERT INTO LOCATION VALUES (2, 'Lagoon', 'Region', 'Country', NULL, NULL);
            UPDATE FOLDER SET LocationId=2 WHERE Id=2;
        """)
    with sqlite3.connect(target) as connection:
        if failure == "ambiguous":
            connection.executescript("INSERT INTO Locations (Name) VALUES ('Lagoon'), ('LAGOON');")
        elif failure == "location-write":
            connection.executescript("""
                CREATE TRIGGER reject_location BEFORE INSERT ON Locations WHEN NEW.Name='Lagoon'
                BEGIN SELECT RAISE(ABORT, 'location rejected'); END;
            """)
        else:
            connection.executescript("""
                CREATE TRIGGER reject_sighting BEFORE INSERT ON Sightings WHEN NEW.SpeciesId=2
                BEGIN SELECT RAISE(ABORT, 'sighting rejected'); END;
            """)
        tables = ("Locations", "Categories", "Species", "Sightings")
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables
        }
    source_before = source.read_bytes()
    caplog.set_level(logging.INFO, logger="reef_tag.nature_recorder")
    expected = ValueError if failure == "ambiguous" else sqlite3.IntegrityError
    with pytest.raises(expected):
        transfer(source, target, DAY)
    with sqlite3.connect(target) as connection:
        for table in tables:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]
    assert source.read_bytes() == source_before
    assert not caplog.messages


def test_source_location_aliases_share_one_sighting(databases: tuple[Path, Path]) -> None:
    """Two source records with the same case-insensitive name create one target location."""
    source, target = databases
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            UPDATE LOCATION SET Name='New reef' WHERE Id=1;
            INSERT INTO LOCATION VALUES (2, 'NEW REEF', 'Other region', 'Other country', 0, 0);
            INSERT INTO FOLDER VALUES (4, '/photos/alias', '2026-10-13', 2);
            INSERT INTO IMAGE VALUES (4, 'alias.png', 0, 4);
            INSERT INTO IDENTIFICATION VALUES (5,4,1,1,1,2);
        """)
    assert transfer(source, target, DAY) == TransferResult(2, 2, 0)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Locations").fetchone()[0] == 3
        assert connection.execute(
            "SELECT Name, County, Country FROM Locations WHERE Id=3"
        ).fetchone() == ("New reef", "Atoll", "Maldives")
    assert transfer(source, target, DAY) == TransferResult(0, 0, 2)


def test_legacy_source_requires_folder_location_upgrade(
    databases: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """Reject old schemas with an actionable error while leaving both databases intact."""
    _, target = databases
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE IMAGE (Id INTEGER PRIMARY KEY, Date TEXT)")
    before = source.read_bytes(), target.read_bytes()
    with pytest.raises(ValueError, match="Open it in the current ReefTag"):
        transfer(source, target, DAY)
    assert (source.read_bytes(), target.read_bytes()) == before


@pytest.mark.parametrize("option", ["-l", "--location"])
def test_location_override_is_removed(
    databases: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    option: str,
) -> None:
    """Reject the removed override before either database is modified."""
    source, target = databases
    before = source.read_bytes(), target.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(["-r", str(source), "-n", str(target), "-d", DAY, option, "Reef"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
    assert (source.read_bytes(), target.read_bytes()) == before
