"""Native function pages and ordered, CRS-aware point input."""

from qgis.PyQt.QtCore import Qt, pyqtSignal, QSignalBlocker, QSize
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication
from .parameter_history import ParameterHistory
from ..core.styles import result_icon
from .table_tools import symbol_column
from .radio_choices import RadioChoices
from .category_picker import CategoryPicker
from .radius_editor import RadiusEditor
from .operation_status import OperationStatus
from .search_area import SearchAreaOptions
from .result_table import ResultTable, ResultItem, SOURCE_ROLE, VALUE_ROLE
from ..core.categories import split_codes, category_alias
from ..core.operations import object_filters

TITLES = ("Адреси", "Об’єкти")
OPERATIONS = ("addresses", "objects")


class FunctionPage(QWidget):
    parameters_changed = pyqtSignal()
    points_selection_changed = pyqtSignal()
    execute_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    pick_requested = pyqtSignal(object)
    zoom_requested = pyqtSignal()

    def __init__(self, operation, title, parent=None, settings=None):
        super().__init__(parent)
        if operation != "objects":
            raise ValueError("Невідома форма пошуку.")
        self.operation = operation
        self.title = title
        self.editors = {}
        self.last_result = None
        self.output_records = []
        self.busy = False
        self.busy_operation = None
        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(6, 4, 6, 4)
        layout = outer
        form = QFormLayout()
        form.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        form.setVerticalSpacing(2)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.get_mode = RadioChoices([("За параметрами", "search"), ("За ID", "ids")])
        self.get_mode_row = QHBoxLayout()
        self.get_mode_row.addWidget(self.get_mode, 1)
        form.addRow("Отримання об’єктів", self.get_mode_row)
        self.id_body = QWidget()
        id_row = QHBoxLayout(self.id_body)
        id_row.setContentsMargins(0, 0, 0, 0)
        self.ids = QLineEdit()
        self.ids.setPlaceholderText("ID об’єктів через кому")
        self.ids.setAccessibleName("ID об’єктів Visicom")
        self.id_count = QLabel("0 / 250")
        id_row.addWidget(self.ids, 1)
        id_row.addWidget(self.id_count)
        form.addRow(self.id_body)
        self.search_options = QWidget()
        options = QFormLayout(self.search_options)
        options.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        options.setContentsMargins(0, 0, 0, 0)
        options.setVerticalSpacing(2)
        options.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        category_row = QHBoxLayout()
        self.category_mode = QComboBox()
        for label, value in (("Усі", 1), ("Лише вибрані", 0), ("Виключити вибрані", 2)):
            self.category_mode.addItem(label, value)
        self.category_mode.setCurrentIndex(1)
        self.categories = CategoryPicker()
        if settings is not None:
            self.categories.setEditText(",".join(settings.object_search_categories()))
        category_row.addWidget(self.category_mode)
        category_row.addWidget(self.categories, 1)
        options.addRow("Категорії", category_row)
        self.text = QLineEdit()
        self.text.setAccessibleName("Текст пошуку об’єктів")
        self.text_mode = QComboBox()
        self.text_mode.addItems(["Частина тексту", "Цілі слова"])
        text_row = QHBoxLayout()
        text_row.addWidget(self.text_mode)
        text_row.addWidget(self.text, 1)
        options.addRow("Текст", text_row)
        self.limit = QSpinBox()
        self.limit.setRange(1, 250)
        self.limit.setValue(250)
        self.limit.setToolTip("Максимум 250 результатів за один запит Visicom Data API.")
        options.addRow("Ліміт результатів", self.limit)
        self.scope = RadioChoices(
            [
                (label, index)
                for index, label in enumerate(
                    ("Україна", "Радіус від точки", "Охоплення", "Шар проєкту")
                )
            ],
            columns=2,
        )
        options.addRow("Область пошуку", self.scope)
        self.area_group = QGroupBox()
        self.area_group_layout = QFormLayout(self.area_group)
        self.area_group_layout.setContentsMargins(6, 0, 6, 3)
        self.area_group_layout.setVerticalSpacing(2)
        self.area_group_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.area_group_layout.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        options.addRow(self.area_group)
        self.area_options = SearchAreaOptions()
        self.area_group_layout.addRow(self.area_options)
        self.spatial_relation = QComboBox()
        self.spatial_relation.addItems(["Повністю всередині", "Перетинає"])
        self.sort_order = QComboBox()
        self.sort_order.addItems(["Автоматично", "За релевантністю", "За відстанню"])
        self.spatial_label = QLabel("Просторова умова")
        self.area_group_layout.addRow(self.spatial_label, self.spatial_relation)
        options.addRow("Сортування", self.sort_order)
        self.radius = QSpinBox()
        self.radius.setRange(1, 20000000)
        self.radius.setValue(1000)
        self.radius_label = QLabel("Радіус, м")
        self.area_group_layout.addRow(self.radius_label, self.radius)
        form.addRow(self.search_options)
        layout.addLayout(form)
        editors = [("near", "Центр радіуса (одна точка)")]
        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        self.editor_body = QWidget()
        self.editor_body.setLayout(editor_row)
        for key, label in editors:
            factory = RadiusEditor
            editor = factory(label, **{})
            self.editors[key] = editor
            editor.pick_requested.connect(self.pick_requested.emit)
            editor.error.connect(lambda message: self.status.set_status(message, "error"))
            editor.maximum = lambda: 1
            editor_row.addWidget(editor, 1)
        self.area_group_layout.addRow(self.editor_body)
        self.editors["near"].setVisible(False)
        self.editors["near"].table.setMaximumHeight(70)
        self.editor_body.hide()
        self.editor_body.setMaximumHeight(48)
        self.radius.setEnabled(False)
        self.scope.currentIndexChanged.connect(self.scope_changed)
        self.get_mode.currentIndexChanged.connect(self.object_mode_changed)
        self.category_mode.currentIndexChanged.connect(self.category_mode_changed)
        self.ids.textChanged.connect(
            lambda: self.id_count.setText(f"{len(split_codes(self.ids.text()))} / 250")
        )
        self.object_mode_changed()
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        self.legend.hide()
        outer.addWidget(self.legend)
        row = QHBoxLayout()
        self.command_row = row
        self.execute_title = "Знайти об'єкти"
        self.execute_button = QPushButton(self.execute_title)
        self.execute_button.setIcon(QgsApplication.getThemeIcon("/mActionStart.svg"))
        row.addWidget(self.execute_button)
        outer.addLayout(row)
        self.status = OperationStatus("Налаштуйте параметри. Автоматичного розбиття запитів немає.")
        self.status.setWordWrap(True)
        status_row = QHBoxLayout()
        outer.addWidget(self.status)
        self.auto_zoom = QCheckBox("Наближати до об’єкта")
        from ..core.settings import PREFIX

        self.auto_zoom.setChecked(
            settings.values.value(PREFIX + "auto_zoom/objects", True, type=bool)
            if settings
            else True
        )
        status_row.addWidget(self.auto_zoom)
        status_row.addStretch()
        self.zoom_button = QPushButton()
        self.zoom_button.setIcon(QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"))
        self.zoom_button.setToolTip("Наблизити до об’єкта")
        self.zoom_button.setEnabled(False)
        self.zoom_button.setMaximumWidth(34)
        self.zoom_button.clicked.connect(self.zoom_requested.emit)
        status_row.addWidget(self.zoom_button)
        outer.addLayout(status_row)
        self.results = ResultTable()
        self.results.setMinimumHeight(32)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.results.setIconSize(QSize(36, 28))
        outer.addWidget(self.results, 2)
        actions = QHBoxLayout()
        actions.addStretch()
        outer.addLayout(actions)
        self.execute_button.clicked.connect(self.submit)
        self.parameter_widgets = {
            key: getattr(self, key)
            for key in (
                "categories",
                "text",
                "ids",
                "limit",
                "scope",
                "radius",
                "auto_zoom",
                "get_mode",
                "category_mode",
                "text_mode",
                "sort_order",
                "spatial_relation",
            )
            if hasattr(self, key)
        }
        self.history = ParameterHistory(self, self.snapshot, self.restore_snapshot)
        self.get_mode_row.addLayout(self.history.toolbar())
        self.area_options.changed.connect(self.history.record)
        self.history.changed.connect(self.parameters_changed.emit)
        for widget in self.parameter_widgets.values():
            if isinstance(widget, CategoryPicker):
                widget.changed.connect(self.history.record)
            elif isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self.history.record)
            elif isinstance(widget, (QComboBox, RadioChoices)):
                widget.currentIndexChanged.connect(self.history.record)
                if isinstance(widget, QComboBox) and widget.isEditable():
                    widget.lineEdit().editingFinished.connect(self.history.record)
            elif isinstance(widget, QSpinBox):
                widget.setKeyboardTracking(False)
                widget.valueChanged.connect(self.history.record)
            else:
                widget.toggled.connect(self.history.record)
        for editor in self.editors.values():
            editor.changed.connect(self.history.record)
            editor.selection_changed.connect(self.points_selection_changed.emit)

    def snapshot(self):
        fields = {}
        for name, widget in self.parameter_widgets.items():
            if isinstance(widget, CategoryPicker):
                fields[name] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                fields[name] = widget.text()
            elif isinstance(widget, (QComboBox, RadioChoices)):
                fields[name] = (widget.currentIndex(), widget.currentText())
            elif isinstance(widget, QSpinBox):
                fields[name] = widget.value()
            else:
                fields[name] = widget.isChecked()
        state = {
            "fields": fields,
            "editors": {name: editor.raw_state() for name, editor in self.editors.items()},
        }
        state["area_options"] = self.area_options.snapshot()
        return state

    def restore_snapshot(self, state):
        if self.operation == "objects" and "area_options" in state:
            self.area_options.restore(state["area_options"])
        for name, value in state["fields"].items():
            widget = self.parameter_widgets[name]
            blocker = QSignalBlocker(widget)
            if isinstance(widget, CategoryPicker):
                widget.setEditText(value)
            elif isinstance(widget, QLineEdit):
                widget.setText(value)
            elif isinstance(widget, (QComboBox, RadioChoices)):
                widget.setCurrentIndex(value[0])
                if isinstance(widget, QComboBox) and widget.isEditable():
                    widget.setEditText(value[1])
            elif isinstance(widget, QSpinBox):
                widget.setValue(value)
            else:
                widget.setChecked(value)
            del blocker
        for name, value in state["editors"].items():
            self.editors[name].set_raw_state(value)
        self.object_mode_changed()

    def submit(self):
        if self.busy:
            self.cancel_requested.emit()
        else:
            self.execute_requested.emit(self.operation)

    def set_busy(self, busy, operation=None):
        self.busy = busy
        self.busy_operation = operation or self.operation if busy else None
        self.execute_button.setEnabled(True)
        self.execute_button.setText("Скасувати" if busy else self.execute_title)
        self.execute_button.setIcon(
            QgsApplication.getThemeIcon("/mTaskCancel.svg" if busy else "/mActionStart.svg")
        )
        if busy:
            self.execute_button.setToolTip(
                "Скасувати поточну операцію; попередні результати збережуться."
            )

    def selected_rows(self):
        return (
            [
                self.results.source_row(row)
                for row in sorted(
                    (index.row() for index in self.results.selectionModel().selectedRows())
                )
            ]
            if hasattr(self, "results")
            else []
        )

    def scope_changed(self, index):
        search = self.get_mode.currentIndex() == 0
        self.area_group.setVisible(search and index != 0)
        self.area_group.setTitle(("", "Радіус від точки", "Охоплення", "Шар проєкту")[index])
        self.editors["near"].setVisible(search and index == 1)
        self.editor_body.setVisible(search and index == 1)
        self.radius.setEnabled(index == 1)
        self.radius.setVisible(index == 1)
        self.radius_label.setVisible(index == 1)
        self.area_options.set_scope(index)
        self.spatial_relation.setVisible(index in (2, 3))
        self.spatial_label.setVisible(index in (2, 3))
        self.spatial_relation.setEnabled(index in (2, 3))
        self.sort_order.model().item(2).setEnabled(index == 1)
        if index != 1 and self.sort_order.currentIndex() == 2:
            self.sort_order.setCurrentIndex(0)

    def object_mode_changed(self, *args):
        by_ids = self.get_mode.currentIndex() == 1
        self.search_options.setVisible(not by_ids)
        self.id_body.setVisible(by_ids)
        self.scope_changed(self.scope.currentIndex())
        self.category_mode_changed()

    def category_mode_changed(self, *args):
        self.categories.setEnabled(self.category_mode.currentData() != 1)

    def parameters(self):
        identifiers = list(
            dict.fromkeys((item.strip() for item in self.ids.text().split(",") if item.strip()))
        )
        if self.get_mode.currentIndex() == 1:
            return ("features", {"ids": identifiers}, {})
        data = object_filters(
            split_codes(self.categories.currentText()),
            self.category_mode.currentData(),
            self.text.text(),
            self.text_mode.currentIndex(),
            self.sort_order.currentIndex(),
            self.spatial_relation.currentIndex(),
            self.scope.currentIndex(),
        )
        data["limit"] = self.limit.value()
        if self.scope.currentIndex() == 1:
            records = self.editors["near"].records()
            if len(records) != 1:
                raise ValueError("Для радіуса потрібна рівно одна центральна точка.")
            data.update(near=records[0]["point"], radius=self.radius.value())
        return ("objects", data, {})

    def show_records(self, records):
        self.output_records = list(records)
        if not hasattr(self, "results"):
            return
        hidden = {"attribution", "label", "rank", "status"}
        columns = sorted(
            {key for record in self.output_records for key in record["attributes"]} - hidden
        )
        if "category" in columns:
            columns.insert(columns.index("category") + 1, "Назва категорії")
        blocker = QSignalBlocker(self.results)
        self.results.setSortingEnabled(False)
        self.results.clear()
        self.results.setColumnCount(len(columns) + 1)
        self.results.setHorizontalHeaderLabels(["Символ"] + columns)
        self.results.setRowCount(len(self.output_records))
        for row, record in enumerate(self.output_records):
            icon = ResultItem("" if record.get("geometry") else "—")
            icon.setData(SOURCE_ROLE, row)
            if record.get("geometry"):
                icon.setIcon(result_icon(self.operation, record))
            self.results.setItem(row, 0, icon)
            for col, key in enumerate(columns, 1):
                value = record["attributes"].get(key)
                if key == "Назва категорії":
                    code = record["attributes"].get("category", "")
                    value = category_alias(code)
                item = ResultItem("" if value is None else str(value))
                item.setData(SOURCE_ROLE, row)
                item.setData(VALUE_ROLE, value)
                item.setToolTip("" if value is None else str(value))
                self.results.setItem(row, col, item)
        symbol_column(self.results)
        self.results.setSortingEnabled(True)
        del blocker
