"""Immutable domain records."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class SpeciesImage:
    """An existing image and its count of identifications of one species."""

    id: int
    path: str
    footage_date: str
    count: int


@dataclass(frozen=True)
class ImagePathChange:
    """A proposed path update guarded by the image's current stored path."""

    image_id: int
    original: str
    replacement: str


@dataclass(frozen=True)
class Species:
    """A reusable catalogue entry."""

    id: int
    common_name: str
    scientific_name: str
    category_id: int | None = None


@dataclass(frozen=True)
class Identification:
    """An occurrence at original-image integer pixel coordinates."""

    id: int
    number: int
    x: int
    y: int
    species: Species


@dataclass(frozen=True)
class PendingIdentification:
    """A fish awaiting identification at original-image pixel coordinates."""

    id: int
    x: int
    y: int


@dataclass(frozen=True)
class Category:
    """A named species group and its current catalogue usage."""

    id: int
    name: str
    species_count: int = 0


@dataclass(frozen=True)
class Folder:
    """A saved folder default and the image records associated with it."""

    id: int
    path: Path
    default_date: date
    images: dict[int, str]
    location_id: int | None = None


@dataclass(frozen=True)
class Location:
    """A geographical location with optional coordinates in decimal degrees."""

    id: int
    name: str
    region: str
    country: str
    latitude: float | None = None
    longitude: float | None = None
