"""Versioned SQLite schema and connection lifecycle."""

import sqlite3
from pathlib import Path
from urllib.parse import quote

from yoyo import get_backend, read_migrations
from yoyo.exceptions import BadMigration, LockTimeout, MigrationConflict

MIGRATIONS_PATH = Path(__file__).parent / "migrations"


class MigrationError(RuntimeError):
    """Database migrations could not complete; application startup must stop."""


def migrate(path: Path) -> None:
    """Apply pending bundled migrations under yoyo's database lock.

    :param path: SQLite file to initialise or upgrade.
    :raises MigrationError: If migration loading, locking or application fails.
    """
    try:
        migrations = read_migrations(str(MIGRATIONS_PATH))
        if not migrations:
            raise MigrationError("No bundled database migrations were found. Reinstall ReefTag.")
        # Yoyo passes the encoded path to SQLite's URI parser. Quote reserved characters
        # so filenames containing spaces, ?, # or % refer to the same file as sqlite3.connect.
        uri = "sqlite:///" + quote(str(path.resolve()), safe="/")
        with get_backend(uri) as backend:
            backend.connection.execute("PRAGMA foreign_keys = ON")
            with backend.lock():
                backend.apply_migrations(backend.to_apply(migrations))
    except (sqlite3.Error, OSError, BadMigration, MigrationConflict, LockTimeout) as error:
        raise MigrationError(
            "Cannot apply ReefTag database migrations. Check database access and the error below. "
            "If this is a database from the pre-migration test version, use a fresh database file. "
            f"Details: {error}"
        ) from error


def connect(path: Path) -> sqlite3.Connection:
    """Migrate the database before returning a foreign-key-enforcing application connection.

    :param path: Database file, created if absent; legacy unversioned schemas are unsupported.
    :return: Open SQLite connection with named rows and foreign-key enforcement.
    :raises MigrationError: If migrations cannot complete.
    :raises sqlite3.Error: If the application connection cannot be opened or configured.
    """
    migrate(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error:
        connection.close()
        raise
