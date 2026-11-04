"""Acceptance tests for atomic, repeatable Nature Recorder transfers."""

import logging
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from reef_tag.nature_recorder import TransferResult, main, parse_date, transfer

DAY = "2026-10-13"


def test_species_logging(databases: tuple[Path, Path], caplog: pytest.LogCaptureFixture) -> None:
    """Report committed species creations and skips with their names and IDs."""
    source, target = databases
    caplog.set_level(logging.INFO, logger="reef_tag.nature_recorder")
    transfer(source, target, "Reef", DAY)
    assert caplog.messages == [
        "Created species: Fish A (Species alpha); ID 1.",
        "Created species: Fish B (Species beta); ID 2.",
    ]
    caplog.clear()
    transfer(source, target, "Reef", DAY)
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
    with sqlite3.connect(source) as connection:
        connection.executescript(
            (root / "src/reef_tag/migrations/0001_initial_schema.sql").read_text()
        )
        connection.executescript("""
            INSERT INTO IMAGE VALUES (1, 'one.png', '2026-10-13'),
                (2, 'two.png', '2026-10-13 12:00:00'), (3, 'other.png', '2026-10-14');
            INSERT INTO SPECIES VALUES (1, 'Fish A', 'Species alpha'),
                (2, 'Fish B', 'Species beta'), (3, 'Unused', 'Unused species');
            INSERT INTO IDENTIFICATION VALUES (1,1,1,1,0,0), (2,1,1,2,0,0),
                (3,2,2,1,0,0), (4,3,3,1,0,0);
        """)
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
    assert transfer(source, target, "reef", DAY) == TransferResult(2, 2, 0)
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
    assert transfer(source, target, "Reef", DAY) == TransferResult(0, 0, 2)
    assert transfer(source, target, "Elsewhere", DAY) == TransferResult(0, 2, 0)
    assert source.read_bytes() == before


def test_existing_non_fish_species(databases: tuple[Path, Path]) -> None:
    """Reuse manually prepared species from any category, ignoring name case."""
    source, target = databases
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO Species (CategoryId, Name, Scientific_Name) VALUES (2, ?, ?)",
            ("FISH A", "SPECIES ALPHA"),
        )
    assert transfer(source, target, "Reef", DAY) == TransferResult(1, 2, 0)


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
        transfer(source, target, "Reef", DAY)
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
        transfer(source, target, "Reef", DAY)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Species").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM Sightings").fetchone()[0] == 0


@pytest.mark.parametrize("value", ["20261013", "2026-1-13", "2026-02-30", "2026-10-13T12:00:00"])
def test_strict_dates(value: str) -> None:
    """Reject noncanonical and impossible calendar dates."""
    with pytest.raises(ValueError):
        parse_date(value)


def test_missing_inputs(databases: tuple[Path, Path], tmp_path: Path) -> None:
    """Reject missing locations and files without creating a database."""
    source, target = databases
    for location in ("", "Unknown"):
        with pytest.raises(ValueError):
            transfer(source, target, location, DAY)
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        transfer(source, missing, "Reef", DAY)
    assert not missing.exists()
    with pytest.raises(ValueError, match="different"):
        transfer(source, source, "Reef", DAY)


def test_cli_environment_and_options(
    databases: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Support environment defaults, both option forms, and readable failures."""
    source, target = databases
    monkeypatch.setenv("REEFTAG_DB_PATH", str(source))
    monkeypatch.setenv("NATURE_RECORDER_DB", str(target))
    assert main(["-l", "Reef", "-d", DAY]) == 0
    assert "Created 2 species and 2 sightings" in capsys.readouterr().out
    assert (
        main(
            [
                "--reeftag-db",
                str(source),
                "--nature-recorder-db",
                str(target),
                "--location",
                "Reef",
                "--date",
                DAY,
            ]
        )
        == 0
    )
    assert main(["-l", "Missing", "-d", DAY]) == 1
    assert "Transfer failed" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["-d", DAY])
