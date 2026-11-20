"""An accessible operation message with an explicit state icon."""

from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QStyle, QWidget, QSizePolicy
from qgis.core import QgsApplication


class OperationStatus(QWidget):
    """Retain the label text API while exposing operation state separately."""

    ICONS = {
        "idle": ("/mIconInfo.svg", "SP_MessageBoxInformation"),
        "running": ("/mTaskInProgress.svg", "SP_BrowserReload"),
        "success": ("/algorithms/mAlgorithmCheckGeometry.svg", "SP_DialogApplyButton"),
        "warning": ("/mIconWarning.svg", "SP_MessageBoxWarning"),
        "error": ("/mIconWarning.svg", "SP_MessageBoxCritical"),
        "cancelled": ("/mTaskCancel.svg", "SP_DialogCancelButton"),
    }

    def __init__(self, message="", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.icon_label = QLabel()
        self.message = QLabel()
        self.message.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.message, 1)
        self.set_status(message)

    def set_status(self, message, state="idle"):
        self.state = state
        path, fallback = self.ICONS[state]
        icon = QgsApplication.getThemeIcon(path)
        if icon.isNull():
            standard = getattr(QStyle, "StandardPixmap", QStyle)
            icon = self.style().standardIcon(getattr(standard, fallback))
        self.icon_label.setPixmap(icon.pixmap(16, 16))
        self.icon_label.setToolTip({
            "idle": "Очікування", "running": "Виконується", "success": "Завершено",
            "warning": "Попередження", "error": "Помилка", "cancelled": "Скасовано",
        }[state])
        self.message.setText(message)
        self.setAccessibleName(message)

    def setText(self, message):
        self.set_status(message, self.state)

    def text(self):
        return self.message.text()

    def setWordWrap(self, enabled):
        self.message.setWordWrap(enabled)

    def heightForWidth(self, width):
        return self.layout().totalHeightForWidth(width)
