"""WGS84 transforms and temporary map overlays."""

import json
from qgis.PyQt.QtCore import Qt, pyqtSignal, QVariantAnimation
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCsException,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from .core.styles import appearance


class ReverseMapTool(QgsMapToolEmitPoint):
    coordinates_selected = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvasClicked.connect(self.clicked)

    def clicked(self, point, button):
        left = getattr(Qt, "LeftButton", None)
        if left is None:
            left = Qt.MouseButton.LeftButton
        if button == left:
            self.coordinates_selected.emit(point)


class PointPickMapTool(ReverseMapTool):
    finished = pyqtSignal()

    def clicked(self, point, button):
        if button == getattr(Qt, "MouseButton", Qt).RightButton:
            self.finished.emit()
        else:
            super().clicked(point, button)

    def keyPressEvent(self, event):
        if event.key() == getattr(Qt, "Key", Qt).Key_Escape:
            event.accept()
            self.finished.emit()
        else:
            super().keyPressEvent(event)


class RectanglePickMapTool(QgsMapTool):
    area_selected = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.start = None
        self.band = None

    def canvasPressEvent(self, event):
        if event.button() == getattr(Qt, "MouseButton", Qt).LeftButton:
            self.start = self.toMapCoordinates(event.pos())

    def canvasMoveEvent(self, event):
        if self.start is None:
            return
        if self.band is None:
            self.band = QgsRubberBand(self.canvas(), QgsWkbTypes.PolygonGeometry)
            self.band.setColor(QColor(22, 115, 165, 65))
            self.band.setWidth(2)
        rect = QgsRectangle(self.start, self.toMapCoordinates(event.pos()))
        self.band.setToGeometry(QgsGeometry.fromRect(rect))

    def canvasReleaseEvent(self, event):
        if event.button() == getattr(Qt, "MouseButton", Qt).RightButton:
            self.finished.emit()
        elif self.start is not None:
            rect = QgsRectangle(self.start, self.toMapCoordinates(event.pos()))
            if rect.width() > 0 and rect.height() > 0:
                self.area_selected.emit(QgsGeometry.fromRect(rect))
            self.finished.emit()

    def keyPressEvent(self, event):
        if event.key() == getattr(Qt, "Key", Qt).Key_Escape:
            event.accept()
            self.finished.emit()
        else:
            super().keyPressEvent(event)

    def deactivate(self):
        self.start = None
        if self.band is not None:
            self.canvas().scene().removeItem(self.band)
            self.band = None
        super().deactivate()


class MapDisplay:
    def __init__(self, canvas, on_change=None):
        self.canvas = canvas
        self.marker = None
        self.band = None
        self.flashes = {}
        self.on_change = on_change
        self.result_items = []

    def has_overlays(self):
        return (self.marker is not None or self.band is not None or bool(self.flashes)
                or bool(self.result_items))

    def clear_results(self):
        for item in self.result_items:
            self.canvas.scene().removeItem(item)
        self.result_items.clear()

    def set_results(self, results):
        """Draw already available results without requests or project layers."""
        from qgis.core import QgsJsonUtils

        self.clear_results()
        transform = self.transform(
            QgsCoordinateReferenceSystem("EPSG:4326"), self.canvas.mapSettings().destinationCrs(),
        )
        try:
            for result in results:
                center = transform.transform(QgsPointXY(*result.center))
                marker = QgsVertexMarker(self.canvas)
                marker.setIconType(QgsVertexMarker.ICON_CROSS)
                marker.setIconSize(10)
                marker.setPenWidth(2)
                marker.setColor(QColor("#1673a5"))
                marker.setCenter(center)
                self.result_items.append(marker)
                if result.geometry:
                    features = QgsJsonUtils.stringToFeatureList(json.dumps({
                        "type": "Feature", "properties": {}, "geometry": result.geometry,
                    }))
                    if not features or features[0].geometry().isNull():
                        raise ValueError("Некоректна геометрія результату.")
                    geometry = QgsGeometry(features[0].geometry())
                    geometry.transform(transform)
                    band = QgsRubberBand(self.canvas, geometry.type())
                    band.setColor(QColor(22, 115, 165, 55)
                                  if geometry.type() == QgsWkbTypes.PolygonGeometry
                                  else QColor("#1673a5"))
                    band.setWidth(2)
                    band.setToGeometry(geometry)
                    self.result_items.append(band)
        except (ValueError, RuntimeError, QgsCsException):
            self.clear_results()
            raise
        self.canvas.refresh()
        self.changed()

    def changed(self):
        if self.on_change is not None:
            self.on_change()

    def transform(self, source, target):
        return QgsCoordinateTransform(source, target, QgsProject.instance().transformContext())

    def wgs84(self, map_point):
        crs = self.canvas.mapSettings().destinationCrs()
        result = self.transform(crs, QgsCoordinateReferenceSystem("EPSG:4326")).transform(map_point)
        return result.x(), result.y()

    def show(self, result, recenter=True, style=None):
        self.clear_selected()
        transform = self.transform(
            QgsCoordinateReferenceSystem("EPSG:4326"), self.canvas.mapSettings().destinationCrs()
        )
        center = transform.transform(QgsPointXY(*result.center))
        marker = QgsVertexMarker(self.canvas)
        color, shape = style or appearance("addresses", result.geometry or {"type": "Point"})
        marker.setIconType(
            {"circle": QgsVertexMarker.ICON_CIRCLE, "diamond": QgsVertexMarker.ICON_RHOMBUS}.get(
                shape, QgsVertexMarker.ICON_CROSS
            )
        )
        marker.setIconSize(18)
        marker.setPenWidth(3)
        marker.setColor(color)
        marker.setCenter(center)
        self.marker = marker
        box = result.bbox
        if not box or box[0] == box[2] or box[1] == box[3]:
            x, y = result.center
            box = (
                max(-180, x - 0.001),
                max(-90, y - 0.001),
                min(180, x + 0.001),
                min(90, y + 0.001),
            )
        if recenter:
            extent = transform.transformBoundingBox(QgsRectangle(*box))
            extent.scale(1.3)
            self.canvas.setExtent(extent)
        if result.geometry:
            feature = {"type": "Feature", "properties": {}, "geometry": result.geometry}
            # QgsJsonUtils is available throughout QGIS 3.28–4.x.
            from qgis.core import QgsJsonUtils

            features = QgsJsonUtils.stringToFeatureList(json.dumps(feature))
            if not features or features[0].geometry().isNull():
                raise ValueError("Не вдалося відобразити геометрію об’єкта.")
            geom = QgsGeometry(features[0].geometry())
            geom.transform(transform)
            self.band = QgsRubberBand(self.canvas, geom.type())
            fill = QColor(color)
            fill.setAlpha(65 if geom.type() == QgsWkbTypes.PolygonGeometry else 255)
            self.band.setColor(fill)
            self.band.setWidth(5 if geom.type() == QgsWkbTypes.LineGeometry else 3)
            self.band.setToGeometry(geom)
        self.flash(QgsGeometry.fromPointXY(center))
        if result.geometry:
            self.flash(geom)
        self.canvas.refresh()
        self.changed()

    def flash(self, geometry):
        """Keep ownership of every animation and overlay so cancellation is immediate."""
        band = QgsRubberBand(self.canvas, geometry.type())
        band.setWidth(4 if geometry.type() == QgsWkbTypes.LineGeometry else 2)
        band.setToGeometry(geometry)
        animation = QVariantAnimation(self.canvas)
        animation.setDuration(500)
        animation.setLoopCount(3)
        animation.setStartValue(QColor(255, 0, 0, 0))
        animation.setKeyValueAt(0.2, QColor(255, 0, 0, 255))
        animation.setEndValue(QColor(255, 0, 0, 0))
        animation.valueChanged.connect(band.setColor)
        animation.finished.connect(lambda: self.remove_flash(animation))
        self.flashes[animation] = band
        animation.start()

    def remove_flash(self, animation, notify=True):
        band = self.flashes.pop(animation, None)
        if band is None:
            return
        animation.stop()
        animation.valueChanged.disconnect()
        animation.finished.disconnect()
        self.canvas.scene().removeItem(band)
        animation.deleteLater()
        if notify:
            self.changed()

    def clear_selected(self):
        for animation in list(self.flashes):
            self.remove_flash(animation, notify=False)
        for item in (self.marker, self.band):
            if item is not None:
                self.canvas.scene().removeItem(item)
        self.marker = None
        self.band = None
        self.changed()

    def clear(self):
        self.clear_results()
        self.clear_selected()
