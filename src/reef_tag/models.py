"""Immutable domain records."""

from dataclasses import dataclass


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
