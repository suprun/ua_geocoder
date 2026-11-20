"""Choose shared access or a privately held, direct Visicom key."""

from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QSizePolicy,
    QPushButton,
    QWidget,
)
from ..core.styles import plugin_icon
from ..core.settings import PREFIX
from .quota_dialog import REGISTRATION_URL
from qgis.core import QgsApplication

API_HELP_URL = "https://api.visicom.ua/uk/products/data-api/data-api-references"


class SettingsPage(QWidget):
    saved = pyqtSignal()
    operation = "settings"

    def __init__(self, settings, parent=None, initial_mode=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowIcon(plugin_icon())
        outer = QVBoxLayout(self)
        layout = QFormLayout()
        outer.addLayout(layout)
        layout.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        wrapping = getattr(QFormLayout, "RowWrapPolicy", QFormLayout)
        layout.setRowWrapPolicy(wrapping.WrapLongRows)
        self.mode = QComboBox()
        self.mode.addItem("Спільний доступ", "railway")
        self.mode.addItem("Власний ключ Visicom API", "visicom")
        self.mode.setCurrentIndex(1 if (initial_mode or settings.mode()) == "visicom" else 0)
        layout.addRow("Режим доступу", self.mode)
        self.railway_info = QLabel(
            "Добова квота обмежена до 100 запитів до API, ключ або токен вводити не потрібно."
        )
        self.railway_info.setWordWrap(True)
        layout.addRow(self.railway_info)
        self.visicom_info = QLabel(
            "Запити надсилаються безпосередньо до Visicom із вашим власним ключем API."
        )
        self.visicom_info.setWordWrap(True)
        layout.addRow(self.visicom_info)
        self.direct = QWidget()
        form = QFormLayout(self.direct)
        form.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        form.setRowWrapPolicy(wrapping.WrapLongRows)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(2)
        self.key_link = QLabel(f'<a href="{REGISTRATION_URL}">Отримати ключ Visicom</a>')
        self.key_link.setOpenExternalLinks(True)
        form.addRow("", self.key_link)
        self.key = QLineEdit()
        echo = getattr(QLineEdit, "EchoMode", QLineEdit)
        self.key.setEchoMode(echo.Password)
        self.key.setPlaceholderText("Введіть ключ або залиште збережений")
        form.addRow("Ключ Visicom API", self.key)
        self.key_label = form.labelForField(self.key)
        self.status = QLabel(
            "Секрети захищає QGIS Authentication Manager."
        )
        self.status.setWordWrap(True)
        form.addRow("", self.status)
        policies = getattr(QSizePolicy, "Policy", QSizePolicy)
        for label in (self.status,):
            # Let wrapped text use the available field width without stretching rows.
            policy = label.sizePolicy()
            policy.setHorizontalPolicy(policies.Ignored)
            policy.setVerticalPolicy(policies.Ignored)
            label.setSizePolicy(policy)
        layout.addRow(self.direct)
        self.direct_quota = QWidget()
        form = QFormLayout(self.direct_quota)
        form.setLabelAlignment(getattr(Qt, "AlignmentFlag", Qt).AlignRight)
        form.setRowWrapPolicy(wrapping.WrapLongRows)
        form.setContentsMargins(0, 0, 0, 0)
        self.show_quota = QCheckBox("Показувати залишок добової квоти")
        self.show_quota.setChecked(settings.show_quota())
        form.addRow(self.show_quota)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1_000_000_000)
        self.limit.setValue(settings.quota_limit())
        self.limit.setEnabled(self.show_quota.isChecked())
        self.show_quota.toggled.connect(self.limit.setEnabled)
        form.addRow("Запитів на добу", self.limit)
        info = QLabel("Локальна оцінка цього плагіна на комп’ютері. Перевищення не блокує запити.")
        info.setWordWrap(True)
        form.addRow(info)
        layout.addRow(self.direct_quota)
        self.show_request_counts = QCheckBox("Показувати кількість запитів на кнопках")
        self.show_request_counts.setChecked(settings.show_request_counts())
        layout.addRow(self.show_request_counts)
        self.access_changed = False
        standard = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
        buttons = QDialogButtonBox(standard.Save | standard.Cancel)
        self.save_button = buttons.button(standard.Save)
        self.cancel_button = buttons.button(standard.Cancel)
        buttons.button(standard.Save).setText("Зберегти")
        buttons.button(standard.Cancel).setText("Скасувати зміни")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reset)
        layout.addRow(buttons)
        help_row = QHBoxLayout()
        self.plugin_help = QPushButton("Довідка плагіна")
        self.plugin_help.setAccessibleName("Довідка плагіна")
        self.plugin_help.setToolTip("Відкрити локальну довідку плагіна")
        self.plugin_help.setIcon(QgsApplication.getThemeIcon("/mActionHelpContents.svg"))
        self.api_help = QPushButton("Довідка Visicom Data API")
        self.api_help.setToolTip("Відкрити офіційний довідник Visicom Data API")
        self.api_help.setIcon(plugin_icon())
        self.api_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(API_HELP_URL)))
        help_row.addWidget(self.plugin_help, 1)
        help_row.addWidget(self.api_help, 1)
        outer.addStretch(1)
        outer.addLayout(help_row)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        for signal in (self.mode.currentIndexChanged, self.key.textChanged, self.limit.valueChanged,
                       self.show_quota.toggled, self.show_request_counts.toggled):
            signal.connect(self.update_dirty)
        self.mode_changed()
        self.update_dirty()

    def update_dirty(self, *args):
        dirty = (self.mode.currentData() != self.settings.mode()
                 or bool(self.key.text().strip())
                 or self.limit.value() != self.settings.quota_limit()
                 or self.show_quota.isChecked() != self.settings.show_quota()
                 or self.show_request_counts.isChecked() != self.settings.show_request_counts())
        self.save_button.setEnabled(dirty)
        self.cancel_button.setEnabled(dirty)

    def mode_changed(self, index=None):
        direct = self.mode.currentData() == "visicom"
        # The status row also carries save/reset feedback in shared access mode.
        self.key_label.setVisible(direct)
        self.key.setVisible(direct)
        self.key_link.setVisible(direct)
        self.direct_quota.setVisible(direct)
        self.railway_info.setVisible(not direct)
        self.visicom_info.setVisible(direct)

    def reload(self):
        self.key.clear()
        self.mode.setCurrentIndex(1 if self.settings.mode() == "visicom" else 0)
        self.limit.setValue(self.settings.quota_limit())
        self.show_quota.setChecked(self.settings.show_quota())
        self.show_request_counts.setChecked(self.settings.show_request_counts())
        self.mode_changed()
        self.update_dirty()
        self.status.setText("Секрети захищає QGIS Authentication Manager.")

    def reset(self):
        self.reload()
        self.status.setText("Незбережені зміни скасовано.")

    def save(self):
        try:
            self.access_changed = (
                self.mode.currentData() != self.settings.mode() or bool(self.key.text().strip())
                or self.limit.value() != self.settings.quota_limit()
                or self.show_quota.isChecked() != self.settings.show_quota()
            )
            if self.access_changed:
                self.settings.save_mode(
                    self.mode.currentData(), self.key.text().strip(), self.limit.value(),
                    self.show_quota.isChecked(),
                )
            self.settings.values.setValue(
                PREFIX + "show_request_counts", self.show_request_counts.isChecked()
            )
        except ValueError as exc:
            box = QMessageBox(self)
            box.setWindowIcon(plugin_icon())
            box.setWindowTitle("Налаштування")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(str(exc))
            run = getattr(box, "exec", None) or box.exec_
            run()
            box.deleteLater()
            return
        self.key.clear()
        self.update_dirty()
        self.status.setText("Налаштування збережено.")
        self.saved.emit()
