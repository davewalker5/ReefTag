"""Keep test preferences separate from the user's real application settings."""

from pathlib import Path

import pytest

from reef_tag import preferences


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all default preferences reads and writes to a per-test temporary file."""
    monkeypatch.setattr(
        preferences, "preferences_path", lambda: tmp_path / "settings/preferences.ini"
    )
