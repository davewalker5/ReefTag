"""Preferences persistence and startup-folder restoration."""

from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths

from reef_tag.preferences import Preferences, preferences_path


def test_standard_location() -> None:
    """Use Qt's per-application configuration directory with an explicit INI filename."""
    expected = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    assert preferences_path() == Path(expected) / "preferences.ini"


def test_folder_round_trip_and_missing_directory(tmp_path: Path) -> None:
    """Persist across preferences instances and ignore missing folders or ordinary files."""
    path = tmp_path / "settings" / "preferences.ini"
    folder = tmp_path / "Reef stills #1"
    folder.mkdir()
    preferences = Preferences(path)
    assert preferences.last_folder() is None
    preferences.save_last_folder(folder)
    assert path.is_file()
    assert Preferences(path).last_folder() == folder
    folder.rmdir()
    assert Preferences(path).last_folder() is None
    folder.touch()
    assert Preferences(path).last_folder() is None


def test_preferences_write_failure(tmp_path: Path) -> None:
    """Report an unwritable preferences target instead of silently claiming it saved."""
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.touch()
    with pytest.raises(OSError, match="Cannot save preferences"):
        Preferences(invalid_parent / "preferences.ini").save_last_folder(tmp_path)


def test_last_image_is_paired_with_folder(tmp_path: Path) -> None:
    """Persist a basename with its folder, ignore missing images, and clear it on folder changes."""
    preferences = Preferences(tmp_path / "preferences.ini")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    image = first / "frame.PNG"
    image.touch()
    preferences.save_last_image(image)
    restored = Preferences(preferences.path)
    assert restored.last_folder() == first
    assert restored.last_image(first) == image
    assert restored.last_image(second) is None
    restored.save_last_folder(first)
    assert restored.last_image(first) == image
    image.unlink()
    assert restored.last_image(first) is None
    image.touch()
    restored.save_last_folder(second)
    assert restored.last_image(second) is None
    restored.save_last_folder(first)
    assert restored.last_image(first) is None


def test_preview_preferences_and_invalid_values(tmp_path: Path) -> None:
    """Round-trip preview controls and fall back safely for malformed or out-of-range values."""
    from PySide6.QtCore import QSettings

    from reef_tag.preferences import PreviewSettings

    preferences = Preferences(tmp_path / "preferences.ini")
    assert preferences.preview_settings() == PreviewSettings()
    preferences.save_last_image(tmp_path / "frame.png", PreviewSettings(-30, 250))
    assert Preferences(preferences.path).preview_settings() == PreviewSettings(-30, 250)
    for brightness, zoom in (("bad", "bad"), (999, 0)):
        settings = QSettings(str(preferences.path), QSettings.Format.IniFormat)
        settings.setValue("preview/brightness", brightness)
        settings.setValue("preview/zoom", zoom)
        settings.sync()
        assert preferences.preview_settings() == PreviewSettings()
