"""Source-coordinate mapping and discovery acceptance tests."""

from pathlib import Path

import pytest

from reef_tag.files import discover_images
from reef_tag.image_geometry import ImageGeometry


def test_letterboxing_and_boundaries() -> None:
    """Ignore margins and map extreme pixels consistently."""
    geometry = ImageGeometry(400, 200, 200, 200)
    assert geometry.offset == (0, 50)
    assert geometry.to_source(0, 50) == (0, 0)
    assert geometry.to_source(199.99, 149.99) == (399, 199)
    for point in ((0, 49), (0, 150), (200, 100), (-1, 100)):
        assert geometry.to_source(*point) is None
    for width, height in ((200, 200), (800, 300), (100, 900)):
        resized = ImageGeometry(400, 200, width, height)
        for source in ((0, 0), (399, 199), (200, 100)):
            assert resized.to_source(*resized.to_preview(*source)) == source
    with pytest.raises(ValueError):
        ImageGeometry(0, 200, 200, 200)


def test_discovery(tmp_path: Path) -> None:
    """Include mixed-case supported files, without recursion."""
    for name in ("b.JPG", "A.png", "c.JpEg", "ignore.mp4"):
        (tmp_path / name).write_bytes(b"123")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "hidden.png").touch()
    assert [path.name for path, _ in discover_images(tmp_path)] == ["A.png", "b.JPG", "c.JpEg"]


def test_zoom_and_pan_bounds() -> None:
    """Keep zoomed images bounded while preserving coordinate round trips."""
    for width, height in ((200, 200), (800, 300), (100, 900)):
        for zoom in (1, 1.5, 4):
            for pan in (-10000, 0, 10000):
                geometry = ImageGeometry(400, 200, width, height, zoom, pan, pan)
                left, top = geometry.offset
                displayed_width = 400 * geometry.scale
                displayed_height = 200 * geometry.scale
                if displayed_width >= width:
                    assert left <= 0
                    assert left + displayed_width >= width
                else:
                    assert left == pytest.approx((width - displayed_width) / 2)
                if displayed_height >= height:
                    assert top <= 0
                    assert top + displayed_height >= height
                else:
                    assert top == pytest.approx((height - displayed_height) / 2)
                source = geometry.to_source(width / 2, height / 2)
                assert source is not None
                assert geometry.to_source(*geometry.to_preview(*source)) == source
                assert geometry.to_source(-1, height / 2) is None
    with pytest.raises(ValueError):
        ImageGeometry(400, 200, 200, 200, 0.5)
