"""Immutable domain records."""

from dataclasses import dataclass


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
