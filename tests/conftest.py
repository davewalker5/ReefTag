"""Keep test preferences separate from the user's real application settings."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from reef_tag import preferences


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all default preferences reads and writes to a per-test temporary file."""
    monkeypatch.setattr(
        preferences, "preferences_path", lambda: tmp_path / "settings/preferences.ini"
    )


@pytest.fixture(autouse=True)
def accept_folder_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply a date for folder prompts without blocking unattended UI tests."""
    from reef_tag.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "prompt_default_date", lambda self, folder, initial: initial)


@pytest.fixture(scope="session", autouse=True)
def qt_application_lifetime() -> Iterator[None]:
    """Keep Qt alive until all dialogs and their deferred deletions are cleaned up."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
