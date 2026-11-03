"""Launch ReefTag directly as a Python desktop application."""

import logging
import sqlite3
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from reef_tag.config import database_path
from reef_tag.db import MigrationError, connect
from reef_tag.repositories import Repository
from reef_tag.ui.main_window import ICON_PATH, MainWindow


def main() -> int:
    """Validate configuration, open the database and run the Qt event loop."""
    logging.basicConfig(level=logging.INFO)
    application = QApplication(sys.argv)
    application.setApplicationName("ReefTag")
    application.setWindowIcon(QIcon(str(ICON_PATH)))
    connection = None
    try:
        connection = connect(database_path())
        window = MainWindow(Repository(connection))
    except (ValueError, OSError, sqlite3.Error, MigrationError) as error:
        if connection is not None:
            connection.close()
        logging.exception("ReefTag startup failed")
        QMessageBox.critical(None, "Cannot start ReefTag", str(error))
        return 1
    try:
        window.show()
        return application.exec()
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
