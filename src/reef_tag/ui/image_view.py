"""Read-only image preview and screen-space marker interaction."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import QScrollBar, QWidget

from reef_tag.image_geometry import ImageGeometry
from reef_tag.models import Identification, PendingIdentification

HIT_RADIUS = 12
MIN_BRIGHTNESS = -100
MAX_BRIGHTNESS = 100
MIN_ZOOM = 100
MAX_ZOOM = 400


class ImageView(QWidget):
    """Render an aspect-fit image with constant-size numbered markers."""

    clicked = Signal(int, int)
    # Python objects preserve SQLite 64-bit IDs without Qt's 32-bit int conversion.
    marker_clicked = Signal(object)
    pending_clicked = Signal(object)

    def __init__(self) -> None:
        """Initialise a neutral, inactive preview."""
        super().__init__()
        self.pixmap = QPixmap()
        self.brightness = 0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._drag_position: QPointF | None = None
        self.annotations: list[Identification] = []
        self.pending: list[PendingIdentification] = []
        self.horizontal_scrollbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self.vertical_scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self.horizontal_scrollbar.setAccessibleName("Image horizontal position")
        self.vertical_scrollbar.setAccessibleName("Image vertical position")
        self.horizontal_scrollbar.valueChanged.connect(self._scroll_changed)
        self.vertical_scrollbar.valueChanged.connect(self._scroll_changed)
        self.setMinimumSize(300, 250)
        self._sync_scrollbars()

    def _preview_rect(self) -> QRect:
        """Reserve permanent space for both scrollbar tracks."""
        return QRect(
            0,
            0,
            max(1, self.width() - self.vertical_scrollbar.sizeHint().width()),
            max(1, self.height() - self.horizontal_scrollbar.sizeHint().height()),
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep scrollbar tracks and image bounds aligned after resizing."""
        super().resizeEvent(event)
        rect = self._preview_rect()
        self.horizontal_scrollbar.setGeometry(
            0, rect.height(), rect.width(), self.height() - rect.height()
        )
        self.vertical_scrollbar.setGeometry(
            rect.width(), 0, self.width() - rect.width(), rect.height()
        )
        self._sync_scrollbars()

    def _sync_scrollbars(self) -> None:
        """Express the bounded pan as a scroll position within the scaled image."""
        mapping = self.geometry_map()
        if mapping:
            self.pan_x, self.pan_y = mapping.bounded_pan
        for bar, extent, viewport, pan in (
            (
                self.horizontal_scrollbar,
                self.pixmap.width() * mapping.scale if mapping else 0,
                self._preview_rect().width(),
                self.pan_x,
            ),
            (
                self.vertical_scrollbar,
                self.pixmap.height() * mapping.scale if mapping else 0,
                self._preview_rect().height(),
                self.pan_y,
            ),
        ):
            overflow = max(0.0, extent - viewport)
            blocked = bar.blockSignals(True)
            bar.setRange(0, round(overflow))
            bar.setPageStep(viewport)
            bar.setValue(round(overflow / 2 - pan))
            bar.blockSignals(blocked)

    def _scroll_changed(self, value: int) -> None:
        """Move the image with either scrollbar while retaining source coordinates."""
        mapping = self.geometry_map()
        if mapping is None:
            return
        self.pan_x = (
            max(0, self.pixmap.width() * mapping.scale - mapping.viewport_width) / 2
            - self.horizontal_scrollbar.value()
        )
        self.pan_y = (
            max(0, self.pixmap.height() * mapping.scale - mapping.viewport_height) / 2
            - self.vertical_scrollbar.value()
        )
        self.update()

    def set_image(self, pixmap: QPixmap, annotations: list[Identification]) -> None:
        """Replace display state without touching the original image."""
        self.pixmap = pixmap
        self.annotations = annotations
        self.reset_pan()
        self.update()

    def reset_pan(self) -> None:
        """Centre the preview and end any active right-button drag."""
        self.pan_x = self.pan_y = 0.0
        self._drag_position = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self.zoom > 1 and not self.pixmap.isNull()
            else Qt.CursorShape.ArrowCursor
        )
        self._sync_scrollbars()
        self.update()

    def set_zoom(self, percentage: int) -> None:
        """Zoom from the fitted view up to 4×, preserving the current viewing centre."""
        if not MIN_ZOOM <= percentage <= MAX_ZOOM:
            raise ValueError("Zoom must be between 100 and 400 percent.")
        mapping = self.geometry_map()
        pan_x, pan_y = mapping.bounded_pan if mapping else (0.0, 0.0)
        ratio = percentage / 100 / self.zoom
        self.pan_x, self.pan_y = pan_x * ratio, pan_y * ratio
        self.zoom = percentage / 100
        self._drag_position = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self.zoom > 1 and not self.pixmap.isNull()
            else Qt.CursorShape.ArrowCursor
        )
        self._sync_scrollbars()
        self.update()

    def set_brightness(self, value: int) -> None:
        """Set preview-only brightness from -100 (black) to 100 (white), with 0 neutral.

        :param value: Brightness adjustment; the source pixmap is never modified.
        :raises ValueError: If the adjustment is outside the supported range.
        """
        if not MIN_BRIGHTNESS <= value <= MAX_BRIGHTNESS:
            raise ValueError("Brightness must be between -100 and 100.")
        self.brightness = value
        self.update()

    def geometry_map(self) -> ImageGeometry | None:
        """Return current mapping, or None when the preview is empty."""
        if self.pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            return None
        return ImageGeometry(
            self.pixmap.width(),
            self.pixmap.height(),
            self._preview_rect().width(),
            self._preview_rect().height(),
            self.zoom,
            self.pan_x,
            self.pan_y,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the photograph and legible yellow markers in logical screen pixels."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#102c35"))
        painter.setClipRect(self._preview_rect())
        mapping = self.geometry_map()
        if mapping is None:
            painter.setPen(QColor("#b9d7db"))
            painter.drawText(
                self._preview_rect(), Qt.AlignmentFlag.AlignCenter, "Choose a folder and image"
            )
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        left, top = mapping.offset
        image_rect = QRectF(
            left, top, self.pixmap.width() * mapping.scale, self.pixmap.height() * mapping.scale
        )
        painter.drawPixmap(
            image_rect,
            self.pixmap,
            QRectF(self.pixmap.rect()),
        )
        # Blend at preview resolution to keep slider interaction responsive for large stills.
        # Apply before annotations, and only inside the photograph, preserving marker contrast.
        if self.brightness:
            shade = QColor("white" if self.brightness > 0 else "black")
            shade.setAlphaF(abs(self.brightness) / MAX_BRIGHTNESS)
            painter.fillRect(image_rect, shade)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        for annotation in self.annotations:
            x, y = mapping.to_preview(annotation.x, annotation.y)
            if not (0 <= x < mapping.viewport_width and 0 <= y < mapping.viewport_height):
                continue
            painter.setPen(QPen(QColor("#16242a"), 3))
            painter.setBrush(QColor("#ffe34d"))
            painter.drawEllipse(QPointF(x, y), 5, 5)
            label_x = x + 10 if x + 40 < mapping.viewport_width else x - 30
            label_y = max(18, min(y - 8, mapping.viewport_height - 8))
            text = str(annotation.number)
            painter.setPen(QPen(QColor("black"), 4))
            # Offset shadows keep numerals visible over both sand and dark reef.
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                painter.drawText(QPointF(label_x + dx, label_y + dy), text)
            painter.setPen(QColor("#ffe34d"))
            painter.drawText(QPointF(label_x, label_y), text)

        for annotation in self.pending:
            x, y = mapping.to_preview(annotation.x, annotation.y)
            if not (0 <= x < mapping.viewport_width and 0 <= y < mapping.viewport_height):
                continue
            # Centre the glyph on its saved point, matching the marker hit target.
            rect = QRectF(x - HIT_RADIUS, y - HIT_RADIUS, HIT_RADIUS * 2, HIT_RADIUS * 2)
            painter.setPen(QColor("black"))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                painter.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, "?")
            painter.setPen(QColor("red"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Edit the nearest marker within tolerance, otherwise emit a source click."""
        mapping = self.geometry_map()
        if mapping is None:
            return
        x, y = event.position().x(), event.position().y()
        source = mapping.to_source(x, y)
        if source is None:
            return
        if event.button() == Qt.MouseButton.RightButton and self.zoom > 1:
            self._drag_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        candidates = []
        for annotation in self.annotations:
            px, py = mapping.to_preview(annotation.x, annotation.y)
            distance = (px - x) ** 2 + (py - y) ** 2
            if distance <= HIT_RADIUS**2:
                candidates.append((distance, 0, annotation.id))
        for annotation in self.pending:
            px, py = mapping.to_preview(annotation.x, annotation.y)
            distance = (px - x) ** 2 + (py - y) ** 2
            if distance <= HIT_RADIUS**2:
                candidates.append((distance, 1, annotation.id))
        if candidates:
            _, pending, marker_id = min(candidates)
            signal = self.pending_clicked if pending else self.marker_clicked
            signal.emit(marker_id)
            return
        self.clicked.emit(*source)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pan during a right-button drag, clamping at each image edge."""
        if self._drag_position is None:
            return
        mapping = self.geometry_map()
        if mapping is None:
            return
        delta = event.position() - self._drag_position
        pan_x, pan_y = mapping.bounded_pan
        self.pan_x, self.pan_y = pan_x + delta.x(), pan_y + delta.y()
        self.pan_x, self.pan_y = self.geometry_map().bounded_pan
        self._drag_position = event.position()
        self._sync_scrollbars()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End right-button panning without creating an annotation."""
        if event.button() == Qt.MouseButton.RightButton:
            self._drag_position = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if self.zoom > 1 else Qt.CursorShape.ArrowCursor
            )
            event.accept()
