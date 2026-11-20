"""Persistent, nonmodal plugin window and shared footer."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtSignal, QSignalBlocker, QTimer, QUrl
from qgis.PyQt.QtGui import QKeySequence, QIcon, QDesktopServices

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)
from qgis.core import QgsApplication
from qgis.gui import QgsFilterLineEdit
from .function_tabs import FunctionPage, TITLES, OPERATIONS
from .settings_page import SettingsPage
from .parameter_history import ParameterHistory
from ..core.styles import plugin_icon
from ..core.settings import PREFIX
from ..core.models import DEFAULT_REVERSE_RADIUS, MAX_REVERSE_RADIUS
from .operation_modes import OperationModes
from .operation_status import OperationStatus
from .result_table import AddressResultTable
from ..core.categories import category_alias


ADDRESS_SEARCH_DELAY_MS = 1000


class PluginWindow(QDialog):
    operation_changed = pyqtSignal()
    visibilityChanged = pyqtSignal(bool)
    search_requested = pyqtSignal(str)
    selection_requested = pyqtSignal(int)
    reverse_requested = pyqtSignal(bool)
    cancel_requested = pyqtSignal()
    help_requested = pyqtSignal()
    geometry_toggled = pyqtSignal(bool)
    quota_changed = pyqtSignal()
    zoom_requested = pyqtSignal()
    access_error = pyqtSignal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("UA Geocoder")
        self.setWindowIcon(plugin_icon())
        self.picking = False
        self.search_busy = False
        self.setObjectName("UaGeocoderWindow")
        self.setModal(False)
        flags = getattr(Qt, "WindowType", Qt)
        self.setWindowFlags(
            flags.Window | flags.WindowCloseButtonHint | flags.WindowMinMaxButtonsHint
        )
        self.resize(850, 650)
        outer = QVBoxLayout(self)
        self.config_message = QLabel()
        self.config_message.setWordWrap(True)
        self.config_message.hide()
        outer.addWidget(self.config_message)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs)
        self.address_page = QWidget()
        layout = QVBoxLayout(self.address_page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.search_row = row
        self.reverse_button = self.button(
            "Знайти адресу за координатами на карті", "mActionIdentify.svg", True
        )
        self.reverse_button.setCheckable(True)
        self.reverse_radius = QSpinBox()
        self.reverse_radius.setRange(1, MAX_REVERSE_RADIUS)
        self.reverse_radius.setSingleStep(10)
        self.reverse_radius.setSuffix(" м")
        self.reverse_radius.setValue(
            settings.values.value(PREFIX + "reverse_radius", DEFAULT_REVERSE_RADIUS, type=int)
        )
        self.reverse_radius.setAccessibleName("Радіус пошуку адреси, м")
        self.reverse_radius.setToolTip("Радіус пошуку найближчої адреси від кліку на карті")
        self.query = QgsFilterLineEdit()
        self.query.setShowClearButton(False)
        self.query.setPlaceholderText("Київ, Хрещатик, 26 • Locator: укр адреса")
        self.query.setAccessibleName("Адреса для пошуку")
        self.query.setToolTip("Введіть адресу від 3 символів. Enter — пошук одразу.")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(ADDRESS_SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.search_after_typing)
        self.query.textEdited.connect(self.schedule_search)
        self.search_button = QPushButton("Знайти")
        # Enter is handled by returnPressed; an auto-default button submits it twice.
        self.search_button.setAutoDefault(False)
        self.search_button.setIcon(QgsApplication.getThemeIcon("/mActionSearch.svg"))
        row.addWidget(self.query)
        self.live_search_button = QToolButton()
        self.live_search_button.setIcon(QIcon(":/qt-project.org/shared/images/mac/searchfind.png"))
        self.live_search_button.setToolButtonStyle(
            getattr(Qt, "ToolButtonStyle", Qt).ToolButtonIconOnly
        )
        self.live_search_button.setCheckable(True)
        self.live_search_button.setChecked(
            settings.values.value(PREFIX + "live_search", True, type=bool)
        )
        self.live_search_button.setAccessibleName("Live-пошук адреси")
        self.live_search_button.setToolTip(
            "Live-пошук: автоматично шукати після паузи 1 секунда (від 3 символів)."
        )
        self.live_search_button.toggled.connect(self.live_search_toggled)
        row.addWidget(self.live_search_button)
        self.search_history_button = QToolButton()
        self.search_history_button.setIcon(QIcon(":/images/themes/default/mIconHistory.svg"))
        self.search_history_button.setToolTip("Історія пошуку")
        self.search_history_button.setAccessibleName("Історія пошуку")
        self.search_history_menu = QMenu(self.search_history_button)
        self.search_history_menu.aboutToShow.connect(self.populate_search_history)
        self.search_history_button.setMenu(self.search_history_menu)
        self.search_history_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.search_history_button)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.results = AddressResultTable()
        self.results.setAccessibleName("Результати адресного пошуку")
        layout.addWidget(self.results)
        self.status = OperationStatus("Введіть адресу для пошуку (від 3 символів).")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.auto_geometry = QCheckBox("Автоматично показувати геометрію")
        self.auto_geometry.setChecked(settings.auto_geometry())
        self.auto_geometry.setToolTip(
            "Завантажувати повну геометрію вибраного результату. "
            "Перше завантаження може витратити додатковий запит API."
        )
        layout.addWidget(self.auto_geometry)
        self.auto_zoom = QCheckBox("Наближати до об’єкта")
        self.auto_zoom.setChecked(
            settings.values.value(PREFIX + "auto_zoom/addresses", True, type=bool)
        )
        layout.addWidget(self.auto_zoom)
        row = QHBoxLayout()
        self.action_row = row
        self.copy_button = self.button("Копіювати адресу", "mActionEditCopy.svg")
        self.copy_coordinates_button = self.button(
            "Копіювати координати", "mIconVertexCoordinates.svg"
        )
        copy_icons = Path(__file__).resolve().parents[1] / "resources" / "icons"
        self.copy_button.setIcon(QIcon(str(copy_icons / "copy_address.svg")))
        self.copy_coordinates_button.setIcon(QIcon(str(copy_icons / "copy_coordinates.svg")))
        self.zoom_button = self.button("Наблизити до об’єкта", "mActionZoomToSelected.svg")
        row.addWidget(self.zoom_button)
        row.addWidget(self.copy_button)
        row.addWidget(self.copy_coordinates_button)
        row.addStretch()
        layout.addLayout(row)
        self.copy_button.setEnabled(False)
        self.copy_coordinates_button.setEnabled(False)
        self.zoom_button.setEnabled(False)
        self.quota = QLineEdit("Квота: ще немає даних")
        self.quota.setReadOnly(True)
        self.quota.setFrame(False)
        self.quota.setAccessibleName("Використання та залишок квоти")
        self.pages = {}
        for operation, title in zip(OPERATIONS[1:], TITLES[1:]):
            page = FunctionPage(operation, title, settings=settings)
            self.pages[operation] = page
        self.search_modes = OperationModes(
            [
                ("addresses", "Адреса", self.address_page),
                ("objects", "Об’єкти", self.pages["objects"]),
            ]
        )
        self.search_modes.choices.layout().setContentsMargins(12, 8, 0, 0)
        self.tabs.addTab(self.search_modes, "Пошук")
        self.settings_page = SettingsPage(settings)
        self.help_button = self.settings_page.plugin_help
        self.tabs.addTab(self.settings_page, "Налаштування")
        self.attribution = QLabel(
            'Картографічні дані © АТ «<a href="https://api.visicom.ua/">Візіком</a>»'
        )
        self.attribution.setObjectName("VisicomAttribution")
        self.attribution.setAccessibleName("Картографічні дані © АТ «Візіком»")
        self.attribution.setWordWrap(False)
        self.attribution.setTextFormat(getattr(Qt, "TextFormat", Qt).RichText)
        alignment = getattr(Qt, "AlignmentFlag", Qt)
        self.attribution.setAlignment(alignment.AlignRight | alignment.AlignVCenter)
        interaction = getattr(Qt, "TextInteractionFlag", Qt)
        self.attribution.setTextInteractionFlags(
            interaction.LinksAccessibleByMouse | interaction.LinksAccessibleByKeyboard
        )
        self.attribution.setFocusPolicy(getattr(Qt, "FocusPolicy", Qt).StrongFocus)
        self.attribution.setOpenExternalLinks(False)
        self.attribution.linkActivated.connect(
            lambda _link: QDesktopServices.openUrl(QUrl("https://api.visicom.ua/"))
        )
        self.footer = QHBoxLayout()
        self.footer.addWidget(self.quota, 1)
        self.footer.addWidget(self.attribution, 0)
        outer.addLayout(self.footer)
        self.search_button.clicked.connect(self.submit)
        self.query.returnPressed.connect(self.submit)
        self.results.currentCellChanged.connect(
            lambda row, column, previous_row, previous_column:
            self.row_changed(row) if row != previous_row else None
        )
        self.results.itemActivated.connect(
            lambda item: self.selection_requested.emit(item.row())
        )
        self.reverse_button.toggled.connect(self.reverse_requested.emit)
        self.zoom_button.clicked.connect(self.zoom_requested.emit)
        self.help_button.clicked.connect(self.help_requested.emit)
        self.copy_button.clicked.connect(self.copy_address)
        self.copy_action = QAction(self.copy_button.icon(), "Копіювати адресу", self.results)
        keys = getattr(QKeySequence, "StandardKey", QKeySequence)
        self.copy_action.setShortcuts(QKeySequence.keyBindings(keys.Copy))
        shortcut = getattr(Qt, "ShortcutContext", Qt)
        self.copy_action.setShortcutContext(shortcut.WidgetShortcut)
        self.copy_action.triggered.connect(self.copy_address)
        self.results.addAction(self.copy_action)
        self.copy_coordinates_action = QAction(
            self.copy_coordinates_button.icon(), "Копіювати координати", self.results
        )
        self.copy_coordinates_action.triggered.connect(self.copy_coordinates_button.click)
        self.results.addAction(self.copy_coordinates_action)
        policy = getattr(Qt, "ContextMenuPolicy", Qt)
        self.results.setContextMenuPolicy(policy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.context_menu)
        self.copy_action.setEnabled(False)
        self.copy_coordinates_action.setEnabled(False)
        self.address_history = ParameterHistory(
            self.address_page, self.address_snapshot, self.restore_address
        )
        reverse_group = QGroupBox()
        toolbar = QHBoxLayout(reverse_group)
        toolbar.setContentsMargins(6, 6, 6, 6)
        toolbar.addWidget(self.reverse_button)
        toolbar.addStretch()
        radius_label = QLabel("Радіус пошуку:")
        radius_label.setBuddy(self.reverse_radius)
        toolbar.addWidget(radius_label)
        toolbar.addWidget(self.reverse_radius)
        self.address_history.undo_button.setParent(self.address_page)
        self.address_history.redo_button.setParent(self.address_page)
        self.address_history.undo_button.hide()
        self.address_history.redo_button.hide()
        layout.insertWidget(0, reverse_group)
        self.query.editingFinished.connect(self.address_history.record)
        self.reverse_radius.valueChanged.connect(self.address_history.record)
        self.auto_geometry.toggled.connect(self.address_history.record)
        self.auto_geometry.toggled.connect(self.geometry_toggled.emit)
        self.auto_zoom.toggled.connect(self.address_history.record)
        self._last_operation = self.active_operation()
        self.tabs.currentChanged.connect(self.notify_operation)
        self.search_modes.changed.connect(self.notify_operation)

    def notify_operation(self, *args):
        operation = self.active_operation()
        if operation == "settings" and operation != self._last_operation:
            self.settings_page.reload()
        if operation != self._last_operation:
            self._last_operation = operation
            self.operation_changed.emit()

    def active_page(self):
        page = self.tabs.currentWidget()
        return page.active_page() if isinstance(page, OperationModes) else page

    def address_snapshot(self):
        return {
            "query": self.query.text(),
            "reverse_radius": self.reverse_radius.value(),
            "auto_geometry": self.auto_geometry.isChecked(),
            "auto_zoom": self.auto_zoom.isChecked(),
        }

    def restore_address(self, state):
        self.search_timer.stop()
        blocker = QSignalBlocker(self.reverse_radius)
        self.reverse_radius.setValue(state.get("reverse_radius", DEFAULT_REVERSE_RADIUS))
        del blocker
        blocker = QSignalBlocker(self.auto_geometry)
        self.query.setText(state["query"])
        self.auto_geometry.setChecked(state["auto_geometry"])
        del blocker
        blocker = QSignalBlocker(self.auto_zoom)
        self.auto_zoom.setChecked(state["auto_zoom"])
        del blocker

    def active_operation(self):
        page = self.active_page()
        return "addresses" if page is self.address_page else getattr(page, "operation", "")

    def activate(self, operation):
        page = self.settings_page
        for modes in (self.search_modes,):
            if operation in modes.operations:
                if operation not in modes.enabled or self.tabs.indexOf(modes) < 0:
                    return False
                previous = self.active_operation()
                blocker = QSignalBlocker(self)
                modes.activate(operation)
                self.tabs.setCurrentWidget(modes)
                del blocker
                # Emit once after both the parent tab and child form are selected.
                self._last_operation = previous
                self.notify_operation()
                return True
        if operation not in ("settings",):
            return False
        index = self.tabs.indexOf(page) if page is not None else -1
        if index >= 0:
            self.tabs.setCurrentIndex(index)
            return True
        return False

    def apply_config(self, enabled, error="", preferred=""):
        previous = self.active_operation()
        current = preferred or self.active_operation()
        window_blocker = QSignalBlocker(self)
        blocker = QSignalBlocker(self.tabs)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for modes, title in ((self.search_modes, "Пошук"),):
            modes.apply_config(enabled)
            if modes.enabled:
                self.tabs.addTab(modes, title)
        self.tabs.addTab(self.settings_page, "Налаштування")
        self.tabs.setVisible(True)
        self.config_message.setText(error or "Режими пошуку вимкнено в config.json.")
        self.config_message.setVisible(bool(error) or not enabled)
        available = self.search_modes.enabled
        if not self.activate(current):
            fallback = next(
                (op for op in ("addresses", "objects") if op in self.search_modes.enabled),
                "settings",
            )
            self.activate(fallback if available else "settings")
        del blocker
        del window_blocker
        self._last_operation = previous
        self.notify_operation()

    def clamp_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        # Include native title bar/borders when fitting a small screen.
        border_w = max(0, frame.width() - self.width())
        border_h = max(0, frame.height() - self.height())
        self.resize(
            min(self.width(), available.width() - border_w),
            min(self.height(), available.height() - border_h),
        )
        frame = self.frameGeometry()
        frame.moveLeft(
            max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
        )
        frame.moveTop(
            max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
        )
        self.move(self.pos() + frame.topLeft() - self.frameGeometry().topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        self.clamp_geometry()
        self.visibilityChanged.emit(True)

    def hideEvent(self, event):
        self.search_timer.stop()
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def closeEvent(self, event):
        # QDialog hides on close; it is owned and deleted only on plugin unload.
        event.accept()

    def reject(self):
        self.close()

    @staticmethod
    def button(title, icon, show_text=False):
        item = QToolButton()
        item.setText(title)
        item.setToolTip(title)
        item.setAccessibleName(title)
        item.setIcon(QgsApplication.getThemeIcon("/" + icon))
        style = getattr(Qt, "ToolButtonStyle", Qt)
        item.setToolButtonStyle(
            style.ToolButtonTextBesideIcon if show_text else style.ToolButtonIconOnly
        )
        return item

    def set_reverse_active(self, active):
        blocker = QSignalBlocker(self.reverse_button)
        self.reverse_button.setChecked(active)
        del blocker

    def context_menu(self, position):
        item = self.results.itemAt(position)
        if item is not None:
            self.results.setCurrentItem(item)
        menu = QMenu(self.results)
        menu.addAction(self.copy_action)
        menu.addAction(self.copy_coordinates_action)
        run = getattr(menu, "exec", None) or menu.exec_
        run(self.results.viewport().mapToGlobal(position))

    def copy_address(self):
        item = self.results.item(self.results.currentRow(), 0)
        if item is not None:
            QApplication.clipboard().setText(item.text())

    def row_changed(self, row):
        for item in (
            self.copy_coordinates_button,
            self.zoom_button,
            self.copy_button,
            self.copy_action,
            self.copy_coordinates_action,
        ):
            item.setEnabled(row >= 0)
        self.selection_requested.emit(row)

    def populate_search_history(self) -> None:
        """Rebuild the menu from profile settings without starting a request."""
        self.search_history_menu.clear()
        history = self.settings.address_search_history()
        for text in history:
            action = self.search_history_menu.addAction(text.replace("&", "&&"))
            action.setData(text)
            action.triggered.connect(
                lambda checked=False, query=text: self.restore_search_query(query)
            )
        if not history:
            self.search_history_menu.addAction("Історія пошуку порожня").setEnabled(False)

    def restore_search_query(self, text: str) -> None:
        """Fill the address field for editing without starting a request."""
        self.search_timer.stop()
        self.query.setText(text)
        self.address_history.record()
        self.query.setFocus()

    def live_search_toggled(self, enabled: bool) -> None:
        """Persist live search in the current profile and stop any pending delay."""
        self.settings.values.setValue(PREFIX + "live_search", enabled)
        self.settings.values.sync()
        self.search_timer.stop()
        if enabled:
            self.schedule_search(self.query.text())

    def schedule_search(self, text: str) -> None:
        """Restart the delay only for user edits to a valid address."""
        self.search_timer.stop()
        if (
            self.live_search_button.isChecked()
            and self.isVisible()
            and not self.picking
            and self.active_operation() == "addresses"
            and 3 <= len(text.strip()) <= 500
        ):
            self.search_timer.start()

    def search_after_typing(self) -> None:
        """Submit the current address after typing has paused."""
        if (
            self.live_search_button.isChecked()
            and self.isVisible()
            and not self.picking
            and not self.search_busy
            and self.active_operation() == "addresses"
            and 3 <= len(self.query.text().strip()) <= 500
        ):
            self.submit()

    def submit(self):
        self.search_timer.stop()
        if self.search_busy:
            self.cancel_requested.emit()
        else:
            # Record before starting: editingFinished must not cancel this search later.
            self.address_history.record()
            text = self.query.text().strip()
            self.settings.remember_address_search(text)
            self.search_requested.emit(text)

    def show_results(self, records, nearest=False):
        self.results.setRowCount(0)
        self.results.setRowCount(len(records))
        for row, record in enumerate(records):
            alias = category_alias(record.category)
            for column, text in enumerate((record.label, alias)):
                item = QTableWidgetItem(text)
                item.setToolTip(f"{alias}\n{record.category}\n{record.attribution}")
                self.results.setItem(row, column, item)
        prefix = "Найближча адреса: " if nearest else "Знайдено: "
        message = prefix + str(len(records)) if records else "Нічого не знайдено поруч з точкою."
        self.status.set_status(message, "success" if records else "warning")
