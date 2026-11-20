"""Non-modal guidance when shared access reaches its daily quota."""

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
from ..core.styles import plugin_icon

REGISTRATION_URL = "https://api.visicom.ua/accounts/forms?action=register_form&lang=uk"


class QuotaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UA Geocoder — добову квоту вичерпано")
        self.setWindowIcon(plugin_icon())
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.message = QLabel(
            "Добову квоту спільного доступу вичерпано. Ви можете дочекатися наступної доби "
            "або отримати власний ключ Visicom на вкладці «Налаштування» плагіна."
        )
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.registration = QLabel(
            '<a href="' + REGISTRATION_URL.replace("&", "&amp;") + '">'
            "Зареєструватися та отримати ключ Visicom</a>"
        )
        self.registration.setWordWrap(True)
        self.registration.setOpenExternalLinks(False)
        self.registration.linkActivated.connect(self.open_registration)
        layout.addWidget(self.registration)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        standard = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
        buttons = QDialogButtonBox(standard.Close)
        buttons.button(standard.Close).setText("Закрити")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.adjustSize()

    def open_registration(self, link):
        if not QDesktopServices.openUrl(QUrl(REGISTRATION_URL)):
            self.status.setText("Не вдалося відкрити сайт Visicom у браузері.")
