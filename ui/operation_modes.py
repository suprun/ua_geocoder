"""Persistent operation forms selected by exclusive radio buttons."""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from .radio_choices import RadioChoices


class OperationModes(QWidget):
    changed = pyqtSignal()

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.operations = [operation for operation, title, page in entries]
        self.enabled = set(self.operations)
        self.choices = RadioChoices([(title, operation) for operation, title, page in entries])
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.choices)
        layout.addWidget(self.stack, 1)
        for operation, title, page in entries:
            self.stack.addWidget(page)
        self.choices.currentIndexChanged.connect(self.select)

    def select(self, index):
        self.stack.setCurrentIndex(index)
        self.changed.emit()

    def active_page(self):
        return self.stack.currentWidget()

    def active_operation(self):
        return self.choices.currentData()

    def activate(self, operation):
        if operation not in self.enabled:
            return False
        self.choices.setCurrentIndex(self.operations.index(operation))
        return True

    def apply_config(self, enabled):
        self.enabled = set(self.operations) & enabled
        for operation, button in zip(self.operations, self.choices.buttons):
            button.setVisible(operation in self.enabled)
            button.setEnabled(operation in self.enabled)
        if self.active_operation() not in self.enabled and self.enabled:
            operation = next(op for op in self.operations if op in self.enabled)
            self.activate(operation)

