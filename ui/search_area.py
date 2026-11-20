"""Search-area controls and lossless preparation of polygon requests."""

from copy import deepcopy
import json

from qgis.PyQt.QtCore import Qt, pyqtSignal, QSignalBlocker
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QComboBox,
)
from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer, QgsWkbTypes, QgsGeometry,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsIconUtils,
)
from .radio_choices import RadioChoices


def polygon_layer(layer):
    """Accept only valid polygon vector layers."""
    return (isinstance(layer, QgsVectorLayer) and layer.isValid()
            and layer.geometryType() == QgsWkbTypes.PolygonGeometry)


class SearchAreaOptions(QWidget):
    changed = pyqtSignal()
    pick_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manual_area = None
        self.extent_body = QWidget()
        extent = QHBoxLayout(self.extent_body)
        extent.setContentsMargins(0, 0, 0, 0)
        self.extent_mode = RadioChoices([
            ("Поточні межі карти", "canvas"), ("Задана область", "rectangle"),
        ], columns=2)
        self.pick_button = QPushButton("Вибрати область на карті")
        self.pick_button.setIcon(QgsApplication.getThemeIcon("/mActionSelectRectangle.svg"))
        self.pick_button.clicked.connect(self.pick_requested.emit)
        extent.addWidget(self.extent_mode, 1)
        extent.addWidget(self.pick_button)
        self.layer_body = QWidget()
        layers = QVBoxLayout(self.layer_body)
        layers.setContentsMargins(0, 0, 0, 0)
        self.layer_mode = RadioChoices([
            ("Поточний шар", "active"), ("Вибрати зі списку", "project"),
        ], columns=2)
        self.layer = QComboBox()
        self.layer.setMinimumContentsLength(20)
        self.layer.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selected_only = QCheckBox("Лише виділені полігони")
        layers.addWidget(self.layer_mode)
        layers.addWidget(self.layer)
        layers.addWidget(self.selected_only)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.extent_body)
        layout.addWidget(self.layer_body)
        self.extent_mode.currentIndexChanged.connect(self.update_controls)
        self.layer_mode.currentIndexChanged.connect(self.update_controls)
        self.layer.currentIndexChanged.connect(self.changed.emit)
        self.selected_only.toggled.connect(self.changed.emit)
        self.refresh_layers()
        self.update_controls()

    def refresh_layers(self, *args):
        previous = self.layer.currentData()
        blocker = QSignalBlocker(self.layer)
        self.layer.clear()
        project_layers = QgsProject.instance().mapLayers().values()
        for layer in sorted(project_layers, key=lambda item: item.name()):
            if polygon_layer(layer):
                self.layer.addItem(QgsIconUtils.iconForWkbType(layer.wkbType()),
                                   layer.name(), layer.id())
                self.layer.setItemData(self.layer.count() - 1, layer.name(),
                                       getattr(Qt, "ItemDataRole", Qt).ToolTipRole)
        index = self.layer.findData(previous)
        # A removed choice remains missing rather than silently targeting another layer.
        self.layer.setCurrentIndex(index if previous is not None
                                   else (0 if self.layer.count() else -1))
        del blocker
        if self.layer.currentData() != previous:
            self.changed.emit()

    def update_controls(self, *args):
        self.pick_button.setEnabled(self.extent_mode.currentData() == "rectangle")
        self.layer.setEnabled(self.layer_mode.currentData() == "project")
        self.changed.emit()

    def set_scope(self, scope):
        self.setVisible(scope in (2, 3))
        self.extent_body.setVisible(scope == 2)
        self.layer_body.setVisible(scope == 3)

    def set_active_layer(self, layer):
        self.layer_mode.buttons[0].setEnabled(polygon_layer(layer))

    def snapshot(self):
        return {"extent": self.extent_mode.currentIndex(),
                "source": self.layer_mode.currentIndex(), "layer": self.layer.currentData(),
                "selected": self.selected_only.isChecked(), "area": deepcopy(self.manual_area)}

    def restore(self, state):
        blocker = QSignalBlocker(self)
        self.extent_mode.setCurrentIndex(state["extent"])
        self.layer_mode.setCurrentIndex(state["source"])
        self.layer.setCurrentIndex(self.layer.findData(state["layer"]))
        self.selected_only.setChecked(state["selected"])
        self.manual_area = deepcopy(state["area"])
        self.update_controls()
        del blocker


def search_geometry(canvas, page, active_layer):
    """Copy and union the requested area without editing or simplifying its source."""
    options = page.area_options
    if page.scope.currentIndex() == 2:
        if options.extent_mode.currentData() == "rectangle":
            if options.manual_area is None:
                raise ValueError("Виберіть прямокутну область на карті.")
            return deepcopy(options.manual_area)
        geom = QgsGeometry.fromRect(canvas.extent())
        crs = canvas.mapSettings().destinationCrs()
    else:
        layer = (active_layer if options.layer_mode.currentData() == "active"
                 else QgsProject.instance().mapLayer(options.layer.currentData() or ""))
        if not polygon_layer(layer):
            raise ValueError("Виберіть полігональний шар проєкту.")
        crs = layer.crs()
        features = (layer.getSelectedFeatures() if options.selected_only.isChecked()
                    else layer.getFeatures())
        geometries = []
        for feature in features:
            geom = QgsGeometry(feature.geometry())
            if geom.isNull() or geom.isEmpty() or not geom.isGeosValid():
                raise ValueError(
                    f"Полігон FID {feature.id()} має порожню або некоректну геометрію.")
            geometries.append(geom)
        if not geometries:
            raise ValueError("Немає виділених полігонів." if options.selected_only.isChecked()
                             else "Шар не містить полігонів.")
        geom = QgsGeometry.unaryUnion(geometries)
    if not crs.isValid() or geom.isNull() or geom.isEmpty() or not geom.isGeosValid():
        raise ValueError("Область має мати відомий CRS і коректну геометрію.")
    geom.transform(QgsCoordinateTransform(
        crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance(),
    ))
    if geom.isEmpty() or not geom.isGeosValid():
        raise ValueError("Некоректна область після перетворення у WGS84.")
    return json.loads(geom.asJson())
