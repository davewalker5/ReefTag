"""Folder-only recording dates, schema migration and date-dependent read coverage."""

import shutil
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from yoyo import get_backend, read_migrations

from reef_tag import db
from reef_tag.data_transfer import export_csv, folder_records, import_csv
from reef_tag.repositories import Repository


def test_folder_date_upgrade_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discard image overrides while preserving IDs, folder metadata and annotations."""
    migrations = db.MIGRATIONS_PATH
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for source in migrations.glob("*.sql"):
        if source.name[:4] < "0008":
            shutil.copy(source, legacy)
    monkeypatch.setattr(db, "MIGRATIONS_PATH", legacy)
    path = tmp_path / "upgrade.db"
    connection = db.connect(path)
    connection.executescript("""
        INSERT INTO LOCATION VALUES (8, 'Reef', 'Atoll', 'Maldives', NULL, NULL);
        INSERT INTO FOLDER VALUES (7, '/photos', '2026-10-13', 8);
        INSERT INTO FOLDER VALUES (9, '/empty', '2026-10-10', NULL);
        INSERT INTO IMAGE VALUES (10, 'a.png', '2026-10-01', 0, 7);
        INSERT INTO IMAGE VALUES (20, 'b.png', '2026-10-02', 1, 7);
        INSERT INTO SPECIES VALUES (3, 'Fish', 'Fish species', NULL);
        INSERT INTO IDENTIFICATION VALUES (11, 10, 3, 1, 10, 20);
        INSERT INTO PENDING_IDENTIFICATION VALUES (12, 20, 30, 40);
    """)
    tables = ("FOLDER", "LOCATION", "SPECIES", "IDENTIFICATION", "PENDING_IDENTIFICATION")
    original = {table: list(connection.execute(f"SELECT * FROM {table}")) for table in tables}
    connection.close()
    monkeypatch.setattr(db, "MIGRATIONS_PATH", migrations)
    connection = db.connect(path)
    assert "Date" not in {row[1] for row in connection.execute("PRAGMA table_info(IMAGE)")}
    for table in tables:
        assert list(connection.execute(f"SELECT * FROM {table}")) == original[table]
    assert [
        tuple(row)
        for row in connection.execute(
            "SELECT id, Name, FurtherExamination, FolderId FROM IMAGE ORDER BY id"
        )
    ] == [(10, "a.png", 0, 7), (20, "b.png", 1, 7)]
    repository = Repository(connection)
    assert repository.image_date(Path("/photos/a.png")) == date(2026, 10, 13)
    assert repository.image_date(Path("/photos/b.png")) == date(2026, 10, 13)
    repository.save_folder_date(Path("/photos"), date(2026, 10, 15))
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
    connection = db.connect(path)
    assert Repository(connection).image_date(Path("/photos/b.png")) == date(2026, 10, 15)
    connection.close()
    with get_backend("sqlite:///" + quote(str(path), safe="/")) as backend:
        backend.connection.execute("PRAGMA foreign_keys=ON")
        with backend.lock():
            pending = backend.to_rollback(read_migrations(str(migrations)))
            backend.rollback_migrations([m for m in pending if m.id == "0008_folder_dates"])
        assert backend.connection.execute("SELECT id, Date FROM IMAGE ORDER BY id").fetchall() == [
            (10, "2026-10-15"),
            (20, "2026-10-15"),
        ]
        assert backend.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection = db.connect(path)
    assert "Date" not in {row[1] for row in connection.execute("PRAGMA table_info(IMAGE)")}
    connection.close()


def test_all_date_reads_follow_folder_edits(tmp_path: Path) -> None:
    """Search, CSV and SQL reports see folder edits immediately, including new images."""
    connection = db.connect(tmp_path / "dates.db")
    repository = Repository(connection)
    folder = tmp_path / "photos"
    first, second = date(2026, 10, 13), date(2026, 10, 15)
    repository.save_folder_date(folder, first)
    repository.create(folder / "a.png", date(2026, 1, 1), 1, 2, "Moorish Idol", "Zanclus")
    repository.create_pending(folder / "b.png", date(2026, 2, 1), 3, 4)
    repository.set_further_examination(folder / "c.png", date(2026, 3, 1), True)
    assert repository.image_date(folder / "a.png") == first
    assert repository.image_date(folder / "b.png") == first
    repository.save_folder_date(folder, second)
    repository.create(folder / "d.png", date(2026, 4, 1), 5, 6, "Moorish Idol", "Zanclus")
    assert {repository.image_date(Path(path)) for path in repository.image_paths().values()} == {
        second
    }
    assert {
        image.footage_date for image in repository.images_for_species(repository.species()[0].id)
    } == {second.isoformat()}
    records = folder_records(repository, folder)
    assert {record.footage_date for record in records} == {second.isoformat()}
    csv_path = tmp_path / "out.csv"
    export_csv(csv_path, records)
    target_connection = db.connect(tmp_path / "target.db")
    target = Repository(target_connection)
    import_csv(target, csv_path)
    assert target.folder_date(folder) == second
    assert folder_records(target, folder) == records
    # Importing into an existing folder retains its date for every imported image.
    target.save_folder_date(folder, first)
    import_csv(target, csv_path)
    assert {record.footage_date for record in folder_records(target, folder)} == {first.isoformat()}
    target_connection.close()
    reports = Path(__file__).resolve().parents[1] / "sql"
    for report in reports.glob("*.sql"):
        rows = connection.execute(report.read_text()).fetchall()
        if rows and "Date" in rows[0].keys():
            assert {row["Date"] for row in rows} == {second.isoformat()}
    connection.close()
