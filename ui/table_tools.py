"""Compact accessible symbol columns and local WGS84 zoom."""

import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QHeaderView, QStyle, QTableWidgetItem
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsJsonUtils,
    QgsProject,
    QgsRectangle,
)


def symbol_column(table):
    item = table.horizontalHeaderItem(0) or QTableWidgetItem()
    item.setText("")
    item.setToolTip("Символ на карті")
    item.setData(getattr(Qt, "ItemDataRole", Qt).AccessibleTextRole, "Символ на карті")
    table.setHorizontalHeaderItem(0, item)
    margin = table.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setColumnWidth(0, table.iconSize().width() + 2 * margin + 2)


def zoom_geometries(canvas, geometries):
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"),
        canvas.mapSettings().destinationCrs(),
        QgsProject.instance(),
    )
    extent = None
    for geometry in geometries:
        features = QgsJsonUtils.stringToFeatureList(
            json.dumps({"type": "Feature", "geometry": geometry, "properties": {}})
        )
        if not features or features[0].geometry().isEmpty():
            continue
        box = features[0].geometry().boundingBox()
        if box.width() == 0 and box.height() == 0:
            box = QgsRectangle(
                max(-180, box.xMinimum() - 0.001),
                max(-90, box.yMinimum() - 0.001),
                min(180, box.xMaximum() + 0.001),
                min(90, box.yMaximum() + 0.001),
            )
        box = transform.transformBoundingBox(box)
        if extent is None:
            extent = box
        else:
            extent.combineExtentWith(box)
    if extent is not None:
        extent.scale(1.2)
        canvas.setExtent(extent)
        canvas.refresh()
    return extent is not None
