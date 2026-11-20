"""Layer, explicit order and selection filter chosen in one local dialog."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFormLayout,
    QComboBox,
    QDialogButtonBox,
    QLabel,
)
from qgis.core import QgsIconUtils
from ..core.styles import plugin_icon


class RadiusLayerDialog(QDialog):
    """Choose only the source layer for a single radius center."""

    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Центр радіуса з шару")
        self.setWindowIcon(plugin_icon())
        self.layers = layers
        layout = QFormLayout(self)
        self.layer = QComboBox()
        self.layer.setMinimumContentsLength(24)
        self.layer.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        for layer in layers:
            title = layer.name() + " [" + layer.id() + "]"
            self.layer.addItem(QgsIconUtils.iconForWkbType(layer.wkbType()), title, layer.id())
            self.layer.setItemData(
                self.layer.count() - 1, title, getattr(Qt, "ItemDataRole", Qt).ToolTipRole
            )
        layout.addRow("Точковий шар", self.layer)
        hint = QLabel("Одна виділена точка або єдина точка шару. MultiPoint не підтримується.")
        hint.setWordWrap(True)
        layout.addRow(hint)
        standard = QDialogButtonBox.StandardButton
        buttons = QDialogButtonBox(standard.Ok | standard.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
