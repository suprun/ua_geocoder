"""One radius center with the same history/map-pick contract as point editors."""

from typing import List, Optional, Sequence
from qgis.PyQt.QtCore import Qt, QSignalBlocker
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget
from qgis.core import QgsProject, QgsWkbTypes, QgsCsException
from .point_editor import PointEditor
from .layer_import import RadiusLayerDialog
from ..core.models import point
from ..core.qgis_io import source_radius_center


class RadiusEditor(PointEditor):
    def preview_coordinates(self) -> Optional[Sequence[float]]:
        """Read the draft without committing fields or recording parameter history."""
        try:
            return point([float(field.text().strip())
                          for field in (self.longitude, self.latitude)])
        except ValueError:
            return None

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        # Retain the point model and its public contract; replace its multi-row view.
        for widget in self.findChildren(QWidget):
            if widget.parentWidget() is self:
                widget.hide()
        self.table.hide()
        row = QHBoxLayout()
        self.longitude = QLineEdit()
        self.latitude = QLineEdit()
        for label, field in (("Довгота", self.longitude), ("Широта", self.latitude)):
            caption = QLabel(label)
            caption.setAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight
                                 | getattr(Qt, "AlignmentFlag", Qt).AlignVCenter)
            row.addWidget(caption)
            field.setAccessibleName(label + " центра радіуса WGS84")
            field.setMaximumWidth(160)
            field.editingFinished.connect(self.commit_fields)
            row.addWidget(field)
        self.buttons[1].show()
        row.addWidget(self.buttons[1])
        # Keep layer import implemented, but hide its radius-center button.
        # self.buttons[2].show()
        # row.addWidget(self.buttons[2])
        self.buttons[2].setIcon(QIcon(":/images/themes/default/mIconPointLayer.svg"))
        self.layout().addLayout(row)
        self.changed.connect(self.sync_fields)

    def commit_fields(self) -> None:
        values = [self.longitude.text().strip(), self.latitude.text().strip()]
        rows = [[self.text(0, self.ID) or "1", *values]] if any(values) else []
        if rows != self.raw_state()["rows"]:
            self.set_raw_state({"rows": rows})

    def sync_fields(self) -> None:
        for field, column in ((self.longitude, self.LON), (self.latitude, self.LAT)):
            blocker = QSignalBlocker(field)
            field.setText(self.text(0, column) if self.table.rowCount() else "")
            del blocker

    def append(
        self, coordinates: Optional[Sequence[float]],
        identifier: Optional[str] = None, name: str = ""
    ) -> None:
        if coordinates is not None:
            point(coordinates)
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(0)
        del blocker
        super().append(coordinates, identifier, name)

    def append_records(self, records: List[dict]) -> None:
        if len(records) != 1:
            raise ValueError("Для центра радіуса виберіть рівно одну точку.")
        record = records[0]
        self.append(record["point"], record.get("source_id"))

    def import_capacity(self) -> int:
        return 1

    def import_layer(self) -> None:
        """Replace the center from one Point without the multi-point importer."""
        layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if hasattr(layer, "wkbType") and layer.isValid()
            and QgsWkbTypes.flatType(layer.wkbType()) == QgsWkbTypes.Point
        ]
        if not layers:
            self.error.emit("У проєкті немає шару Point для центра радіуса (не MultiPoint).")
            return
        dialog = RadiusLayerDialog(layers, self)
        try:
            run = getattr(dialog, "exec", None) or dialog.exec_
            if not run():
                return
            layer = QgsProject.instance().mapLayer(dialog.layer.currentData())
            self.append_records([source_radius_center(layer)])
        except (ValueError, RuntimeError, QgsCsException) as exc:
            self.error.emit(str(exc))
        finally:
            dialog.deleteLater()
