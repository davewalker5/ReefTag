"""Generate repository icon assets from the vector master; no app bundling."""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RESOURCE_PATH = Path(__file__).resolve().parents[1] / "src" / "reef_tag" / "resources"


def main() -> None:
    """Render standard macOS PNG representations and assemble a PNG-backed ICNS file."""
    application = QGuiApplication([])
    renderer = QSvgRenderer(str(RESOURCE_PATH / "reeftag.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid icon master")
    iconset = RESOURCE_PATH / "reeftag.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(RESOURCE_PATH / f"reeftag-{size}.png")):
            raise OSError("Cannot save icon raster")
        if size == 1024:
            image.save(str(RESOURCE_PATH / "reeftag.png"))
    for size in (16, 32, 128, 256, 512):
        for density in (1, 2):
            suffix = "@2x" if density == 2 else ""
            (iconset / f"icon_{size}x{size}{suffix}.png").write_bytes(
                (RESOURCE_PATH / f"reeftag-{size * density}.png").read_bytes()
            )
    chunks = []
    for tag, size in (
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
        (b"ic10", 1024),
    ):
        data = (RESOURCE_PATH / f"reeftag-{size}.png").read_bytes()
        chunks.append(tag + struct.pack(">I", len(data) + 8) + data)
    payload = b"".join(chunks)
    (RESOURCE_PATH / "reeftag.icns").write_bytes(
        b"icns" + struct.pack(">I", len(payload) + 8) + payload
    )
    application.quit()


if __name__ == "__main__":
    main()
