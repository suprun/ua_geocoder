"""Sortable result cells with stable source identity and local clipboard actions."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QTableWidget, QTableWidgetItem, QMenu, QApplication, QHeaderView
from qgis.core import QgsApplication

SOURCE_ROLE = int(getattr(Qt, "ItemDataRole", Qt).UserRole)
VALUE_ROLE = SOURCE_ROLE + 1


class ResultItem(QTableWidgetItem):
    def __lt__(self, other):
        left, right = self.data(VALUE_ROLE), other.data(VALUE_ROLE)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return self.text().casefold() < other.text().casefold()


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(getattr(Qt, "ContextMenuPolicy", Qt).CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.horizontalHeader().setSortIndicator(-1, getattr(Qt, "SortOrder", Qt).AscendingOrder)
        self.setSortingEnabled(True)

    def source_row(self, row):
        item = self.item(row, 0)
        return item.data(SOURCE_ROLE) if item is not None else -1

    def copy_action(self, position):
        item = self.itemAt(position)
        if item is None or item.column() == 0:
            return None
        header = self.horizontalHeaderItem(item.column()).text()
        menu = QMenu(self)
        action = menu.addAction(QgsApplication.getThemeIcon("/mActionEditCopy.svg"),
                                "Копіювати значення " + header)
        value = item.text()
        action.triggered.connect(lambda: QApplication.clipboard().setText(value))
        return menu

    def context_menu(self, position):
        menu = self.copy_action(position)
        if menu is not None:
            run = getattr(menu, "exec", None) or menu.exec_
            run(self.viewport().mapToGlobal(position))
            menu.deleteLater()


class AddressResultTable(QTableWidget):
    """Two read-only columns retaining the provider's relevance order."""

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Знайдений результат", "Категорія"])
        self.setAccessibleName("Результати адресного пошуку")
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setSortingEnabled(False)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setMinimumSectionSize(80)
        self.horizontalHeader().setStretchLastSection(True)
        self._columns_initialized = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._columns_initialized:
            self.setColumnWidth(0, max(160, self.viewport().width() * 2 // 3))
            self._columns_initialized = True
