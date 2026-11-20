"""Bounded snapshots of raw inputs, independent of results and credentials."""

from copy import deepcopy
from qgis.PyQt.QtCore import QObject, pyqtSignal, QSignalBlocker
from qgis.PyQt.QtWidgets import QHBoxLayout, QToolButton
from qgis.core import QgsApplication


class ParameterHistory(QObject):
    changed = pyqtSignal()

    def __init__(self, owner, capture, restore):
        super().__init__(owner)
        self.owner = owner
        self.capture = capture
        self.restore = restore
        self.busy = False
        self.states = [deepcopy(capture())]
        self.position = 0
        self.undo_button = QToolButton()
        self.redo_button = QToolButton()
        for button, name, icon, action in (
            (self.undo_button, "Скасувати зміну параметрів", "mActionUndo.svg", self.undo),
            (self.redo_button, "Повторити зміну параметрів", "mActionRedo.svg", self.redo),
        ):
            button.setIcon(QgsApplication.getThemeIcon("/" + icon))
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(action)
        self.update_buttons()

    def toolbar(self):
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        return row

    def record(self, *args):
        if self.busy:
            return
        state = deepcopy(self.capture())
        if state == self.states[self.position]:
            return
        self.states = self.states[: self.position + 1] + [state]
        self.states = self.states[-101:]
        self.position = len(self.states) - 1
        self.update_buttons()
        self.changed.emit()

    def group(self, action):
        self.record()
        self.busy = True
        blocker = QSignalBlocker(self.owner)
        try:
            action()
        finally:
            del blocker
            self.busy = False
        self.record()

    def apply(self, state):
        if self.capture() != state:
            self.group(lambda: self.restore(deepcopy(state)))

    def move(self, delta):
        self.record()
        target = self.position + delta
        if not 0 <= target < len(self.states):
            return
        self.busy = True
        blocker = QSignalBlocker(self.owner)
        try:
            self.restore(deepcopy(self.states[target]))
            self.position = target
        finally:
            del blocker
            self.busy = False
        self.update_buttons()
        self.changed.emit()

    def undo(self):
        self.move(-1)

    def redo(self):
        self.move(1)

    def update_buttons(self):
        self.undo_button.setEnabled(self.position > 0)
        self.redo_button.setEnabled(self.position < len(self.states) - 1)
