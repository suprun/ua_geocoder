"""Exclusive choices with stable values for parameter snapshots."""

from typing import Any, Iterable, Optional, Tuple
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QWidget, QGridLayout, QButtonGroup, QRadioButton


class RadioChoices(QWidget):
    currentIndexChanged = pyqtSignal(int)

    def __init__(
        self,
        choices: Iterable[Tuple[str, Any]],
        columns: int = 3,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.choices = list(choices)
        self.group = QButtonGroup(self)
        self.buttons = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(2)
        for index, (label, value) in enumerate(self.choices):
            button = QRadioButton(label)
            self.group.addButton(button, index)
            button.toggled.connect(
                lambda checked, i=index: self.currentIndexChanged.emit(i) if checked else None
            )
            layout.addWidget(button, index // columns, index % columns)
            self.buttons.append(button)
        self.setCurrentIndex(0)

    def currentIndex(self) -> int:
        return self.group.checkedId()

    def currentText(self) -> str:
        return self.choices[self.currentIndex()][0]

    def currentData(self) -> Any:
        return self.choices[self.currentIndex()][1]

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
