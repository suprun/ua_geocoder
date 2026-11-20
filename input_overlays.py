"""Numbered input points, owned independently of result previews and project layers."""

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainterPath, QPen, QPolygonF
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsMapCanvasItem

STYLES = {
    "near": ("#168da5", "cross", "Центр радіуса"),
}
GLYPHS = {"circle": "●", "square": "■", "diamond": "◆", "cross": "✚", "x": "×"}


class NumberedPoint(QgsMapCanvasItem):
    def __init__(self, canvas, number, coordinates, role, selected, label_offset=0):
        super().__init__(canvas)
        self.canvas = canvas
        self.number = number
        self.coordinates = coordinates
        self.role = role
        self.selected = selected
        self.label_offset = label_offset
        self.setZValue(150)
        self.updatePosition()

    def boundingRect(self):
        return QRectF(-12, -32 - self.label_offset, 75, 46 + self.label_offset)

    def updatePosition(self):
        try:
            target = self.canvas.mapSettings().destinationCrs()
            if not target.isValid():
                self.hide()
                return
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), target, QgsProject.instance()
            )
            self.map_point = transform.transform(QgsPointXY(*self.coordinates))
            self.setPos(self.toCanvasCoordinates(self.map_point))
            self.show()
        except (QgsCsException, RuntimeError):
            self.hide()

    def paint(self, painter, option, widget=None):
        color, shape, _ = STYLES[self.role]
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("white"), 6 if self.selected else 4))
        painter.setBrush(QColor(color))
        self.draw_shape(painter, shape)
        painter.setPen(QPen(QColor("#111111"), 3 if self.selected else 1))
        self.draw_shape(painter, shape)
        font = QFont("Arial", 10)
        font.setBold(True)
        path = QPainterPath()
        path.addText(QPointF(10, -8 - self.label_offset), font, str(self.number))
        painter.setPen(QPen(QColor("white"), 3))
        painter.setBrush(QColor("#111111"))
        painter.drawPath(path)
        painter.setPen(getattr(Qt, "PenStyle", Qt).NoPen)
        painter.drawPath(path)

    @staticmethod
    def draw_shape(painter, shape):
        if shape == "circle":
            painter.drawEllipse(QPointF(0, 0), 6, 6)
        elif shape == "square":
            painter.drawRect(QRectF(-6, -6, 12, 12))
        elif shape == "diamond":
            painter.drawPolygon(
                QPolygonF([QPointF(0, -8), QPointF(8, 0), QPointF(0, 8), QPointF(-8, 0)])
            )
        else:
            painter.save()
            if shape == "x":
                painter.rotate(45)
            path = QPainterPath()
            path.addRect(QRectF(-2, -8, 4, 16))
            path.addRect(QRectF(-8, -2, 16, 4))
            painter.drawPath(path.simplified())
            painter.restore()


class InputOverlayManager:
    def __init__(self, canvas):
        self.canvas = canvas
        self.items = []
        self.closed = False
        canvas.destinationCrsChanged.connect(self.reproject)

    def clear(self):
        for item in self.items:
            self.canvas.scene().removeItem(item)
            sip.delete(item)
        self.items.clear()

    def show(self, points):
        self.clear()
        coincident = {}
        for number, coordinates, role, selected in points:
            key = tuple(coordinates)
            offset = coincident.get(key, 0)
            coincident[key] = offset + 16
            self.items.append(
                NumberedPoint(self.canvas, number, coordinates, role, selected, offset)
            )

    def reproject(self):
        for item in self.items:
            item.updatePosition()

    def close(self):
        if not self.closed:
            self.closed = True
            self.canvas.destinationCrsChanged.disconnect(self.reproject)
            self.clear()


def page_points(page):
    if (
        getattr(page, "operation", None) != "objects"
        or page.scope.currentIndex() != 1
        or page.get_mode.currentIndex() != 0
    ):
        return []
    coordinates = page.editors["near"].preview_coordinates()
    return [(1, coordinates, "near", False)] if coordinates is not None else []


def editor_roles(page, key):
    return ["near"] * page.editors[key].table.rowCount()


def legend_text(points):
    roles = {point[2] for point in points}
    return " · ".join(
        f'<span style="color:{color}">{GLYPHS[shape]}</span> {title}'
        for role, (color, shape, title) in STYLES.items()
        if role in roles
    )
