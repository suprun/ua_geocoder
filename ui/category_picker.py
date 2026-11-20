"""Offline, keyboard-accessible category dialog for object search."""

from typing import Iterable, List, Optional
from qgis.PyQt.QtCore import Qt, QSignalBlocker, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)
from qgis.core import QgsApplication
from ..core.categories import (
    GROUPS,
    category_catalog,
    category_group,
    category_summary,
    split_codes,
    valid_code,
)
from ..core.styles import plugin_icon

CHECK = getattr(Qt, "CheckState", Qt)
FLAGS = getattr(Qt, "ItemFlag", Qt)
ROLE = getattr(Qt, "ItemDataRole", Qt).UserRole


class CategoryDialog(QDialog):
    def __init__(self, codes: Iterable[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Категорії об’єктів Visicom")
        self.setWindowIcon(plugin_icon())
        self.resize(820, 600)
        self.chosen = list(codes)
        codes = set(self.chosen)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук за назвою, кодом або ключовими словами")
        self.search.setAccessibleName("Пошук категорій")
        self.only_selected = QCheckBox("Лише позначені")
        row.addWidget(self.search, 1)
        row.addWidget(self.only_selected)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Категорія", "Код"])
        self.tree.setAccessibleName("Категорії з прапорцями; пробіл змінює вибір")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 270)
        self.groups = {name: QTreeWidgetItem(self.tree, [name]) for name in GROUPS}
        for group in self.groups.values():
            group.setFlags(group.flags() | FLAGS.ItemIsUserCheckable)
            group.setCheckState(0, CHECK.Unchecked)
            group.setToolTip(
                0, "Позначити або зняти всі доступні категорії групи, також приховані."
            )
        self.items = {}
        self.search_text = {}
        known = set()
        for record in sorted(
            category_catalog(), key=lambda item: (item["name"].casefold(), item["id"])
        ):
            code = record["id"]
            known.add(code)
            item = QTreeWidgetItem(self.groups[category_group(code)], [record["name"], code])
            item.setData(0, ROLE, code)
            item.setToolTip(0, record["name"])
            item.setToolTip(1, code)
            item.setFlags(item.flags() | FLAGS.ItemIsUserCheckable)
            item.setCheckState(
                0, CHECK.Checked if code in codes and valid_code(code) else CHECK.Unchecked
            )
            if not valid_code(code):
                item.setFlags(item.flags() & ~FLAGS.ItemIsEnabled)
                item.setToolTip(
                    0, "Код у джерелі містить непідтверджений формат; вибір недоступний."
                )
            self.items[code] = item
            self.search_text[code] = " ".join(
                str(record.get(key, "")) for key in ("name", "id", "keywords")
            ).casefold()
        self.tree.expandAll()
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.select_all = QPushButton("Позначити всі")
        self.clear_all = QPushButton("Зняти всі")
        self.count = QLabel()
        row.addWidget(self.select_all)
        row.addWidget(self.clear_all)
        row.addStretch()
        row.addWidget(self.count)
        layout.addLayout(row)
        self.extra_toggle = QToolButton()
        self.extra_toggle.setText("Додаткові коди")
        self.extra_toggle.setCheckable(True)
        self.extra_toggle.setToolButtonStyle(
            getattr(Qt, "ToolButtonStyle", Qt).ToolButtonTextBesideIcon
        )
        self.extra = QPlainTextEdit()
        self.extra.setAccessibleName("Додаткові коди категорій через кому або з нового рядка")
        self.extra.setPlaceholderText("Коди, яких немає у каталозі; через кому або з нового рядка")
        self.extra.setMaximumHeight(75)
        self.extra.setPlainText(",".join(code for code in codes if code not in known))
        layout.addWidget(self.extra_toggle)
        layout.addWidget(self.extra)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        standard = QDialogButtonBox.StandardButton
        self.buttons = QDialogButtonBox(standard.Apply | standard.Cancel)
        self.buttons.button(standard.Apply).setText("Застосувати")
        self.buttons.button(standard.Cancel).setText("Скасувати")
        self.buttons.button(standard.Apply).clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.tree.itemChanged.connect(self.item_changed)
        self.search.textChanged.connect(self.filter_items)
        self.only_selected.toggled.connect(self.filter_items)
        self.extra.textChanged.connect(self.refresh)
        self.extra_toggle.toggled.connect(self.toggle_extra)
        self.extra_toggle.setChecked(bool(self.extra.toPlainText()))
        self.toggle_extra(self.extra_toggle.isChecked())
        self.select_all.clicked.connect(lambda: self.set_visible(True))
        self.clear_all.clicked.connect(lambda: self.set_visible(False))
        self.refresh()

    def toggle_extra(self, expanded: bool) -> None:
        self.extra.setVisible(expanded)
        arrows = getattr(Qt, "ArrowType", Qt)
        self.extra_toggle.setArrowType(arrows.DownArrow if expanded else arrows.RightArrow)

    def selected_codes(self) -> List[str]:
        selected = {
            code
            for code, item in self.items.items()
            if valid_code(code) and item.checkState(0) == CHECK.Checked
        }
        extra = split_codes(self.extra.toPlainText())
        if any(not valid_code(code) for code in extra):
            raise ValueError("Додаткові коди: лише латинські літери нижнього регістру, цифри й _.")
        return sorted(selected | set(extra))

    def item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None:
            blocker = QSignalBlocker(self.tree)
            checked = item.checkState(0) != CHECK.Unchecked
            for index in range(item.childCount()):
                child = item.child(index)
                if valid_code(child.data(0, ROLE)):
                    child.setCheckState(0, CHECK.Checked if checked else CHECK.Unchecked)
            del blocker
        self.refresh()

    def refresh(self, *args) -> None:
        blocker = QSignalBlocker(self.tree)
        for group in self.groups.values():
            states = [
                group.child(i).checkState(0) == CHECK.Checked
                for i in range(group.childCount())
                if valid_code(group.child(i).data(0, ROLE))
            ]
            state = (
                CHECK.Checked
                if all(states)
                else CHECK.PartiallyChecked
                if any(states)
                else CHECK.Unchecked
            )
            group.setCheckState(0, state)
        del blocker
        try:
            selected = self.selected_codes()
            self.count.setText(f"Позначено: {len(selected)}")
            self.error.clear()
            valid = True
        except ValueError as exc:
            self.error.setText(str(exc))
            valid = False
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(valid)
        self.filter_items()

    def filter_items(self, *args) -> None:
        query = self.search.text().strip().casefold()
        for code, item in self.items.items():
            visible = query in self.search_text[code]
            if self.only_selected.isChecked():
                visible = visible and item.checkState(0) == CHECK.Checked
            item.setHidden(not visible)
        for group in self.groups.values():
            group.setHidden(all(group.child(i).isHidden() for i in range(group.childCount())))
        filtered = bool(query) or self.only_selected.isChecked()
        self.select_all.setText("Позначити знайдені" if filtered else "Позначити всі")
        self.clear_all.setText("Зняти знайдені" if filtered else "Зняти всі")

    def set_visible(self, checked: bool) -> None:
        blocker = QSignalBlocker(self.tree)
        for code, item in self.items.items():
            if not item.isHidden() and valid_code(code):
                item.setCheckState(0, CHECK.Checked if checked else CHECK.Unchecked)
        del blocker
        if not checked and not self.search.text().strip() and not self.only_selected.isChecked():
            self.extra.clear()
        self.refresh()

    def accept(self) -> None:
        try:
            self.chosen = self.selected_codes()
        except ValueError:
            self.refresh()
            return
        super().accept()


class CategoryPicker(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.codes = ["adm_settlement"]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Категорії…")
        self.button.setIcon(QgsApplication.getThemeIcon("/search.svg"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(getattr(Qt, "TextFormat", Qt).PlainText)
        row.addWidget(self.button)
        row.addWidget(self.summary, 1)
        self.button.clicked.connect(self.choose)
        self.update_summary()

    def currentText(self) -> str:
        return ",".join(self.codes)

    def setEditText(self, text: str) -> None:
        codes = split_codes(text)
        if codes != self.codes:
            self.codes = codes
            self.update_summary()
            self.changed.emit()

    def update_summary(self) -> None:
        self.summary.setText(category_summary(self.codes))
        self.summary.setToolTip(self.currentText())

    def choose(self) -> None:
        dialog = CategoryDialog(self.codes, self)
        run = getattr(dialog, "exec", None) or dialog.exec_
        if run():
            self.setEditText(",".join(dialog.chosen))
        dialog.deleteLater()
