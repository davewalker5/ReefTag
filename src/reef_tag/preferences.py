"""Small user preferences file in Qt's standard per-application configuration directory."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths


def preferences_path() -> Path:
    """Return the user preferences path using Qt's OS-specific configuration location."""
    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if not directory:
        raise OSError("Qt could not locate the user configuration directory.")
    return Path(directory) / "preferences.ini"


@dataclass(frozen=True)
class PreviewSettings:
    """Brightness adjustment and zoom percentage for the remembered image."""

    brightness: int = 0
    zoom: int = 100


class Preferences:
    """Read and atomically save user preferences independently of the catalogue database."""

    def __init__(self, path: Path | None = None) -> None:
        """Use the standard location, or an explicit file for isolated tests."""
        self.path = path if path is not None else preferences_path()

    def last_folder(self) -> Path | None:
        """Return a saved folder only when it still exists as a directory.

        :raises OSError: If the preferences file cannot be read or is malformed.
        """
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        value = settings.value("images/last_folder", "")
        if settings.status() != QSettings.Status.NoError:
            raise OSError(f"Cannot read preferences from {self.path}.")
        if not isinstance(value, str) or not value:
            return None
        folder = Path(value)
        return folder if folder.is_absolute() and folder.is_dir() else None

    def save_last_folder(self, folder: Path) -> None:
        """Immediately save the chosen folder, creating the preferences directory if needed.

        :raises OSError: If the preferences file cannot be written.
        """
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        if settings.value("images/last_folder", "") != str(folder.resolve()):
            settings.remove("images/last_image")
            settings.remove("preview")
        settings.setValue("images/last_folder", str(folder.resolve()))
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError(f"Cannot save preferences to {self.path}.")

    def last_image(self, folder: Path) -> Path | None:
        """Return the remembered image only if it still belongs to the restored folder."""
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        saved_folder = settings.value("images/last_folder", "")
        filename = settings.value("images/last_image", "")
        if settings.status() != QSettings.Status.NoError:
            raise OSError(f"Cannot read preferences from {self.path}.")
        if saved_folder != str(folder.resolve()) or not isinstance(filename, str) or not filename:
            return None
        # Store a basename and reject path components so restoration stays inside the folder.
        if Path(filename).name != filename:
            return None
        image = folder / filename
        return image if image.is_file() else None

    def save_last_image(self, image: Path, preview: PreviewSettings = PreviewSettings()) -> None:
        """Save a loaded image, its folder and preview settings together."""
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        settings.setValue("images/last_folder", str(image.parent.resolve()))
        settings.setValue("images/last_image", image.name)
        settings.setValue("preview/brightness", preview.brightness)
        settings.setValue("preview/zoom", preview.zoom)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError(f"Cannot save preferences to {self.path}.")

    def preview_settings(self) -> PreviewSettings:
        """Read remembered preview settings, using neutral defaults for invalid values."""
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        brightness = settings.value("preview/brightness", 0)
        zoom = settings.value("preview/zoom", 100)
        if settings.status() != QSettings.Status.NoError:
            raise OSError(f"Cannot read preferences from {self.path}.")
        try:
            brightness, zoom = int(brightness), int(zoom)
        except TypeError, ValueError, OverflowError:
            return PreviewSettings()
        return PreviewSettings(
            brightness if -100 <= brightness <= 100 else 0,
            zoom if 100 <= zoom <= 400 else 100,
        )
