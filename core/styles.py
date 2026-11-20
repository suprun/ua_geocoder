"""Map and table symbols for search results."""

from pathlib import Path
from qgis.PyQt.QtCore import Qt, QRectF, QPointF
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap, QPen, QPolygonF

RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources"


def plugin_icon():
    return QIcon(str(RESOURCE_ROOT / "icon.svg"))


def appearance(operation, geometry, attributes=None):
    kind = (geometry or {}).get("type", "")
    shape = (
        "line"
        if "Line" in kind
        else "polygon"
        if "Polygon" in kind
        else "cross"
        if "Point" in kind
        else "none"
    )
    color = QColor("#1673a5")
    return color, shape


def symbol_icon(color, shape, selected=False):
    pixmap = QPixmap(36, 28)
    pixmap.fill(getattr(Qt, "GlobalColor", Qt).transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(18, 14)
    painter.setPen(QPen(QColor("#111111"), 3 if selected else 1))
    painter.setBrush(QColor(color))
    if shape == "circle":
        painter.drawEllipse(QPointF(0, 0), 6, 6)
    elif shape == "square":
        painter.drawRect(QRectF(-6, -6, 12, 12))
    elif shape == "diamond":
        painter.drawPolygon(
            QPolygonF([QPointF(0, -8), QPointF(8, 0), QPointF(0, 8), QPointF(-8, 0)])
        )
    elif shape in ("cross", "x"):
        if shape == "x":
            painter.rotate(45)
        painter.setPen(QPen(QColor(color), 4 if selected else 3))
        painter.drawLine(-7, 0, 7, 0)
        painter.drawLine(0, -7, 0, 7)
    elif shape == "line":
        painter.setPen(QPen(QColor(color), 5))
        painter.drawPolyline(QPolygonF([QPointF(-14, 4), QPointF(-3, -4), QPointF(14, 2)]))
    elif shape == "polygon":
        fill = QColor(color)
        fill.setAlpha(65)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(color), 2))
        painter.drawPolygon(
            QPolygonF([QPointF(-12, 6), QPointF(-7, -7), QPointF(9, -5), QPointF(12, 6)])
        )
    painter.end()
    return QIcon(pixmap)


def result_icon(operation, record):
    return symbol_icon(*appearance(operation, record.get("geometry"), record.get("attributes")))
