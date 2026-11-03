"""Aspect-fit geometry in logical screen pixels, independent of Qt."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ImageGeometry:
    """Map an original image into a centred aspect-fit viewport."""

    source_width: int
    source_height: int
    viewport_width: float
    viewport_height: float
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self) -> None:
        """Reject empty dimensions before calculating a scale."""
        if (
            min(self.source_width, self.source_height, self.viewport_width, self.viewport_height)
            <= 0
        ):
            raise ValueError("Image and viewport dimensions must be positive.")
        if (
            not all(isfinite(value) for value in (self.zoom, self.pan_x, self.pan_y))
            or self.zoom < 1
        ):
            raise ValueError("Zoom must be at least 1 and pan offsets must be finite.")

    @property
    def scale(self) -> float:
        """Return screen pixels per source pixel."""
        return self.zoom * min(
            self.viewport_width / self.source_width, self.viewport_height / self.source_height
        )

    @property
    def offset(self) -> tuple[float, float]:
        """Return bounded image offsets, centring any dimension smaller than the viewport."""
        pan_x, pan_y = self.bounded_pan
        return (
            (self.viewport_width - self.source_width * self.scale) / 2 + pan_x,
            (self.viewport_height - self.source_height * self.scale) / 2 + pan_y,
        )

    @property
    def bounded_pan(self) -> tuple[float, float]:
        """Clamp screen-pixel pan to image edges, preventing additional empty margins."""
        limit_x = max(0.0, (self.source_width * self.scale - self.viewport_width) / 2)
        limit_y = max(0.0, (self.source_height * self.scale - self.viewport_height) / 2)
        return (
            max(-limit_x, min(self.pan_x, limit_x)),
            max(-limit_y, min(self.pan_y, limit_y)),
        )

    def to_source(self, x: float, y: float) -> tuple[int, int] | None:
        """Truncate an in-image click to source pixels; ignore letterboxed margins."""
        if not (0 <= x < self.viewport_width and 0 <= y < self.viewport_height):
            return None
        left, top = self.offset
        sx, sy = (x - left) / self.scale, (y - top) / self.scale
        if not (0 <= sx < self.source_width and 0 <= sy < self.source_height):
            return None
        return min(int(sx), self.source_width - 1), min(int(sy), self.source_height - 1)

    def to_preview(self, x: int, y: int) -> tuple[float, float]:
        """Return the screen location of a source pixel's centre."""
        left, top = self.offset
        return left + (x + 0.5) * self.scale, top + (y + 0.5) * self.scale
