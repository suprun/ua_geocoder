"""Raw ordered point inputs with symbolic, non-editable first column."""

from qgis.PyQt.QtCore import pyqtSignal, QSignalBlocker, Qt, QSize
from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QSizePolicy,
)
from qgis.core import QgsApplication
from ..core.models import point
from ..core.styles import plugin_icon, symbol_icon
from .table_tools import symbol_column


class PointEditor(QWidget):
    pick_requested = pyqtSignal(object)
    error = pyqtSignal(str)
    changed = pyqtSignal()
    selection_changed = pyqtSignal()
    zoom_requested = pyqtSignal(object)
    SYMBOL, ID, LON, LAT, NAME = range(5)

    def __init__(self, title, parent=None, names=False, compact=False):
        super().__init__(parent)
        self.names = names
        self.import_selected_only = False
        self.maximum = lambda: 250
        self.setWindowIcon(plugin_icon())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setSpacing(3)
        heading = self.heading = QLabel(title + " — WGS84: довгота, широта")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        columns = ["", "ID", "Довгота", "Широта"] + (["Назва"] if names else [])
        self.table = QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setIconSize(QSize(36, 28))
        symbol_column(self.table)
        self.table.setMinimumHeight(50)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.itemChanged.connect(self.item_changed)
        self.table.itemSelectionChanged.connect(self.selection_changed.emit)
        row = QHBoxLayout()
        row.setSpacing(3)
        text_row = QHBoxLayout() if compact else row
        text_row.setSpacing(3)
        self.buttons = []
        for text, title, icon, action in (
            ("", "Додати рядок", "mActionAdd.svg", self.add_empty),
            ("Вибрати на карті", "Вибрати на карті", "mActionIdentify.svg", self.pick),
            ("Додати з шару", "Додати з шару", "mActionAddPolyline.svg", self.import_layer),
            ("", "Видалити рядок", "mActionDeleteSelected.svg", self.remove),
        ):
            button = QPushButton(text)
            button.setIcon(QgsApplication.getThemeIcon("/" + icon))
            button.setToolTip(title)
            button.setAccessibleName(title)
            if not text:
                button.setMaximumWidth(34)
            button.clicked.connect(action)
            (text_row if compact and text else row).addWidget(button)
            self.buttons.append(button)
        if compact:
            layout.addLayout(text_row)
        layout.addLayout(row)
        self.zoom_button = QPushButton()
        self.zoom_button.setIcon(QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"))
        self.zoom_button.setToolTip("Наблизити до об’єкта")
        self.zoom_button.setAccessibleName("Наблизити до об’єкта")
        self.zoom_button.setMaximumWidth(34)
        self.zoom_button.clicked.connect(
            lambda: self.zoom_requested.emit(self.selected_geometries())
        )
        row.addWidget(self.zoom_button)
        layout.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self.update_zoom)
        self.changed.connect(self.update_zoom)
        self.update_zoom()

    def selected_geometries(self):
        return [
            {"type": "Point", "coordinates": list(coords)}
            for _, coords, selected in self.map_points()
            if selected
        ]

    def update_zoom(self, *args):
        self.zoom_button.setEnabled(bool(self.selected_geometries()))

    def input_count(self) -> int:
        return self.table.rowCount()

    def item_changed(self, item):
        if item.column() != self.SYMBOL:
            self.changed.emit()

    def text(self, row, column):
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    def raw_state(self):
        return {
            "rows": [
                [self.text(r, c) for c in range(1, self.table.columnCount())]
                for r in range(self.input_count())
            ],
        }

    def set_raw_state(self, state):
        blocker = QSignalBlocker(self)
        table_blocker = QSignalBlocker(self.table)
        self.table.setRowCount(0)
        for values in state["rows"]:
            self.append_raw(values)
        del table_blocker, blocker
        self.changed.emit()

    def append_raw(self, values):
        blocker = QSignalBlocker(self.table)
        row = self.input_count()
        self.table.insertRow(row)
        icon = QTableWidgetItem()
        flags = getattr(Qt, "ItemFlag", Qt)
        icon.setFlags(icon.flags() & ~flags.ItemIsEditable)
        self.table.setItem(row, 0, icon)
        for column in range(1, self.table.columnCount()):
            value = values[column - 1] if column - 1 < len(values) else ""
            self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.setCurrentCell(row, self.LON)
        del blocker
        self.changed.emit()

    def add_empty(self):
        self.append(None)

    def pick(self):
        self.pick_requested.emit(self)

    def unique_id(self, identifier=None):
        used = {self.text(r, self.ID) for r in range(self.input_count())}
        if identifier is None:
            number = 1
            while str(number) in used:
                number += 1
            return str(number)
        candidate, number = str(identifier), 2
        while candidate in used:
            candidate = str(identifier) + "_" + str(number)
            number += 1
        return candidate

    def append(self, coordinates, identifier=None, name=""):
        values = [self.unique_id(identifier)]
        values.extend(["", ""] if coordinates is None else [f"{c:.12g}" for c in coordinates])
        if self.names:
            values.append(name)
        self.append_raw(values)

    def remove(self):
        row = self.table.currentRow()
        if 0 <= row < self.input_count():
            blocker = QSignalBlocker(self.table)
            self.table.removeRow(row)
            del blocker
            self.changed.emit()

    def replace_records(self, records):
        blocker = QSignalBlocker(self)
        self.table.setRowCount(0)
        for record in records:
            self.append(record["point"], record.get("source_id"), record.get("name", ""))
        del blocker
        self.changed.emit()

    def map_points(self):
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        for row in range(self.table.rowCount()):
            try:
                coords = point([float(self.text(row, c)) for c in (self.LON, self.LAT)])
            except (ValueError, TypeError):
                continue
            yield row + 1, coords, row in selected

    def set_symbols(self, roles, enabled=True):
        from ..input_overlays import STYLES

        blocker = QSignalBlocker(self.table)
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        valid = {number - 1 for number, _, _ in self.map_points()}
        for row, role in enumerate(roles):
            item = self.table.item(row, 0)
            if item is None:
                continue
            color, shape, title = STYLES[role]
            item.setIcon(symbol_icon(color if enabled else "#aaaaaa", shape, row in selected))
            state = "" if enabled and row in valid else " — не відображається"
            item.setToolTip(f"{title}, рядок {row + 1}{state}")
        del blocker

    def records(self):
        result = []
        for row in range(self.input_count()):
            try:
                coords = point([float(self.text(row, c)) for c in (self.LON, self.LAT)])
            except ValueError:
                raise ValueError(f"Рядок {row + 1}: введіть довготу та широту WGS84.") from None
            identifier = self.text(row, self.ID).strip()
            if not identifier or identifier in [r["source_id"] for r in result]:
                raise ValueError("ID точок мають бути непорожніми й унікальними.")
            result.append(
                {
                    "source_id": identifier,
                    "point": list(coords),
                    "name": self.text(row, self.NAME) if self.names else "",
                }
            )
        return result
