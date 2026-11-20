"""Local WGS84 search outlines, independent of requests and project layers."""

import math
from statistics import median
from typing import List, Optional, Sequence

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
    QgsDistanceArea, QgsGeometry, QgsPointXY, QgsProject, QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand

from .core.models import point

PREVIEW_COLOR = "#168da5"
CIRCLE_SEGMENTS = 360


def radius_ring(center: Sequence[float], radius: float) -> List[QgsPointXY]:
    """Sample an ellipsoidal WGS84 circle with a radius in meters."""
    origin = QgsPointXY(*point(list(center)))
    if not math.isfinite(radius) or not 1 <= radius <= 20_000_000:
        raise ValueError("Некоректний радіус попереднього перегляду.")
    distance = QgsDistanceArea()
    distance.setEllipsoid("WGS84")
    ring = [distance.computeSpheroidProject(origin, radius, math.tau * i / CIRCLE_SEGMENTS)
            for i in range(CIRCLE_SEGMENTS)]
    return ring + [QgsPointXY(ring[0])]


def split_dateline(ring: Sequence[QgsPointXY]) -> List[List[QgsPointXY]]:
    """Split wrapped longitudes at ±180 instead of drawing across the world."""
    if not ring:
        return []
    parts = [[QgsPointXY(ring[0])]]
    for previous, current in zip(ring, ring[1:]):
        delta = current.x() - previous.x()
        if abs(delta) > 180:
            unwrapped = current.x() - math.copysign(360, delta)
            boundary = -180.0 if delta > 0 else 180.0
            span = unwrapped - previous.x()
            fraction = (boundary - previous.x()) / span if span else 0.5
            latitude = previous.y() + fraction * (current.y() - previous.y())
            parts[-1].append(QgsPointXY(boundary, latitude))
            parts.append([QgsPointXY(-boundary, latitude)])
        parts[-1].append(QgsPointXY(current))
    return [part for part in parts if len(part) > 1]


class SearchAreaPreview:
    """Own one dashed map outline and release all canvas resources on unload."""

    def __init__(self, canvas: QgsMapCanvas) -> None:
        self.canvas = canvas
        self.band = None
        self.key = None
        self.parts = []
        self.closed = False
        canvas.destinationCrsChanged.connect(self.reproject)

    def clear(self) -> None:
        """Forget the old geometry, including after invalid or incomplete input."""
        self.key = None
        self.parts = []
        if self.band is not None:
            self.canvas.scene().removeItem(self.band)
            sip.delete(self.band)
            self.band = None

    def show_radius(self, center: Sequence[float], radius: float) -> None:
        """Update only when the confirmed or currently typed radius changes."""
        key = ("radius", tuple(center), radius)
        if key != self.key:
            self.parts = split_dateline(radius_ring(center, radius))
            self.key = key
            self.reproject()

    def show_rectangle(self, area: Optional[dict]) -> None:
        """Use the saved request polygon; interpolate edges before projection."""
        if not area or area.get("type") != "Polygon":
            self.clear()
            return
        key = ("rectangle", str(area))
        if key == self.key:
            return
        parts = []
        for coordinates in area["coordinates"]:
            ring = [QgsPointXY(*point(list(coordinate[:2]))) for coordinate in coordinates]
            for part in split_dateline(ring):
                dense = []
                for first, last in zip(part, part[1:]):
                    steps = min(360, max(1, math.ceil(max(
                        abs(last.x() - first.x()), abs(last.y() - first.y())
                    ) / 0.5)))
                    dense.extend(QgsPointXY(
                        first.x() + (last.x() - first.x()) * i / steps,
                        first.y() + (last.y() - first.y()) * i / steps,
                    ) for i in range(steps))
                dense.append(part[-1])
                parts.append(dense)
        self.parts, self.key = parts, key
        self.reproject()

    def reproject(self) -> None:
        """Keep invalid points and projection jumps out of the rendered paths."""
        if self.closed or not self.parts:
            return
        target = self.canvas.mapSettings().destinationCrs()
        if not target.isValid():
            if self.band is not None:
                self.band.hide()
            return
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), target, QgsProject.instance()
        )
        projected = []
        for part in self.parts:
            line = []
            for coordinate in part:
                try:
                    value = transform.transform(coordinate)
                    if not math.isfinite(value.x()) or not math.isfinite(value.y()):
                        raise ValueError("Projection discontinuity")
                except (QgsCsException, ValueError):
                    if len(line) > 1:
                        projected.append(line)
                    line = []
                    continue
                line.append(value)
            if len(line) > 1:
                projected.append(line)
        lengths = [math.hypot(b.x() - a.x(), b.y() - a.y())
                   for line in projected for a, b in zip(line, line[1:])]
        positive = [length for length in lengths if length > 0]
        # Cuts in projected CRSs may be finite. Reject isolated jumps relative
        # to the densely sampled outline, independent of the map's distance unit.
        limit = median(positive) * 32 if positive else 0
        safe = []
        for line in projected:
            part = [line[0]]
            for first, last in zip(line, line[1:]):
                if math.hypot(last.x() - first.x(), last.y() - first.y()) > limit:
                    if len(part) > 1:
                        safe.append(part)
                    part = []
                part.append(last)
            if len(part) > 1:
                safe.append(part)
        if not safe:
            if self.band is not None:
                self.band.hide()
            return
        if self.band is None:
            self.band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            self.band.setColor(QColor(PREVIEW_COLOR))
            self.band.setWidth(2)
            self.band.setLineStyle(getattr(Qt, "PenStyle", Qt).DashLine)
            self.band.setZValue(140)
        self.band.setToGeometry(QgsGeometry.fromMultiPolylineXY(safe))
        self.band.show()

    def close(self) -> None:
        """Disconnect canvas signals before its scene or the plugin is destroyed."""
        if not self.closed:
            self.closed = True
            self.canvas.destinationCrsChanged.disconnect(self.reproject)
            self.clear()
