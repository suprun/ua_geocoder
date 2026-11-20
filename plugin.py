"""QGIS entry point, shared search flow and complete lifecycle cleanup."""

from pathlib import Path
from dataclasses import replace
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QUrl, QDate
from qgis.PyQt.QtGui import QIcon, QDesktopServices

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsCsException
from .core.client import BrowserRequestHeaders, NetworkClient, RequestTask
from .core.cache import SessionCache
from .core.models import SearchResult
from .core.settings import Credentials, Settings, PREFIX
from .core.config import load_config
from .locator import AddressLocatorFilter, migrate_default_prefix
from .map_tools import MapDisplay, PointPickMapTool
from .ui.plugin_window import PluginWindow
from .ui.quota_dialog import QuotaDialog
from .function_controller import FunctionController
from .request_costs import RequestCosts


class UaGeocoderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.settings = Settings()
        self.dock = None
        self.action = None
        self.locator = None
        self.display = None
        self.tool = None
        self.previous_tool = None
        self.reverse_picking = False
        self.records = []
        self.result_status = ""
        self.tasks = set()
        self.generations = {"search": 0, "feature": 0}
        self.active = False
        self.cache = SessionCache()
        self.quota_dialog = None
        self.quota_notices = set()
        self.functions = None
        self.enabled_operations = None
        self.config_error = ""
        self.costs = None
        self.browser_headers = BrowserRequestHeaders()

    def initGui(self):
        if self.active:
            return
        self.active = True
        self.browser_headers.install()
        if self.cache.closed:
            self.cache = SessionCache()
        self.dock = PluginWindow(self.settings, self.iface.mainWindow())
        geometry = self.settings.values.value(PREFIX + "window_geometry")
        if geometry is not None:
            self.dock.restoreGeometry(geometry)
        self.dock.auto_geometry.setChecked(self.settings.auto_geometry())
        self.dock.geometry_toggled.connect(self.geometry_toggled)
        self.dock.quota_changed.connect(self.update_quota)
        self.cache.on_quota = self.dock.quota_changed.emit
        self.dock.access_error.connect(self.access_error)
        self.cache.on_error = self.dock.access_error.emit
        self.display = MapDisplay(self.iface.mapCanvas(), self.update_controls)
        self.iface.mapCanvas().destinationCrsChanged.connect(self.refresh_result_display)
        self.tool = PointPickMapTool(self.iface.mapCanvas())
        self.tool.coordinates_selected.connect(self.reverse_at)
        self.tool.finished.connect(self.restore_tool)
        self.iface.mapCanvas().mapToolSet.connect(self.map_tool_changed)
        self.dock.search_requested.connect(self.search)
        self.dock.query.textEdited.connect(self.address_query_edited)
        self.dock.selection_requested.connect(self.select)
        self.dock.reverse_requested.connect(self.set_reverse_enabled)
        self.dock.settings_page.saved.connect(self.settings_saved)
        self.dock.address_history.changed.connect(self.address_parameters_changed)
        self.dock.cancel_requested.connect(self.cancel)
        self.dock.help_requested.connect(self.show_help)
        self.dock.copy_coordinates_button.clicked.connect(self.copy_coordinates)
        self.dock.zoom_requested.connect(self.zoom_selected)
        icon = QIcon(str(Path(__file__).parent / "resources" / "icon.svg"))
        self.action = QAction(icon, "UA Geocoder", self.iface.mainWindow())
        self.action.triggered.connect(self.open_panel)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("UA Geocoder", self.action)
        self.functions = FunctionController(self)
        # Unlock only when the user requests search; loading QGIS must never prompt.
        self.dock.visibilityChanged.connect(self.visibility_changed)
        self.refresh_config(initial=True)
        self.dock.setVisible(self.settings.visible())
        self.costs = RequestCosts(self)
        self.update_controls()

    def refresh_config(self, initial=False):
        enabled, error = load_config()
        if initial or enabled != self.enabled_operations or error != self.config_error:
            if initial or self.dock.active_operation() not in enabled:
                self.cancel(silent=True)
            self.enabled_operations, self.config_error = enabled, error
            preferred = self.settings.values.value(PREFIX + "active_tab", "addresses", type=str)
            self.dock.apply_config(enabled, error, preferred)
        if "addresses" in enabled and self.locator is None:
            migrate_default_prefix()
            self.locator = AddressLocatorFilter(
                activate=self.locator_activate,
                credentials_provider=self.refresh_credentials,
                cache=self.cache,
            )
            self.iface.registerLocatorFilter(self.locator)
        elif "addresses" not in enabled and self.locator is not None:
            self.locator.activate = None
            self.iface.deregisterLocatorFilter(self.locator)
            self.locator = None

    def update_controls(self):
        if self.dock is None:
            return
        reverse = self.tool is not None and self.iface.mapCanvas().mapTool() == self.tool
        self.dock.set_reverse_active(reverse)
        self.dock.search_busy = bool(self.tasks)
        self.dock.query.setShowSpinner(
            any(task.operation in ("search", "reverse") for task in self.tasks)
        )
        self.dock.search_button.setText("Скасувати" if self.dock.search_busy else "Знайти")
        self.dock.search_button.setIcon(
            QgsApplication.getThemeIcon(
                "/mTaskCancel.svg" if self.dock.search_busy else "/mActionSearch.svg"
            )
        )
        if self.costs is not None:
            self.costs.refresh()

    def copy_coordinates(self):
        from qgis.PyQt.QtWidgets import QApplication

        row = self.dock.results.currentRow()
        if 0 <= row < len(self.records):
            x, y = self.records[row].center
            QApplication.clipboard().setText(f"{x:.8f}, {y:.8f}")

    def zoom_selected(self):
        row = self.dock.results.currentRow()
        if 0 <= row < len(self.records):
            record = self.records[row]
            self.functions.zoom(
                [record.geometry or {"type": "Point", "coordinates": record.center}]
            )

    def map_tool_changed(self, current, previous):
        if not self.active:
            return
        if current != self.tool:
            self.previous_tool = None
            if self.reverse_picking:
                self.restore_tool()
        if self.functions is not None:
            self.functions.external_tool_changed(current)
        self.update_controls()

    def show_help(self):
        path = Path(__file__).parent / "resources" / "help.html"
        page = self.dock.active_page()
        status = getattr(page, "status", self.dock.status)
        if not path.is_file():
            status.setText("Файл довідки відсутній. Перевстановіть плагін із ZIP.")
        else:
            url = QUrl.fromLocalFile(str(path.resolve()))
            operation = getattr(page, "operation", "addresses")
            url.setFragment("access" if operation == "settings" else operation)
            if not QDesktopServices.openUrl(url):
                status.setText("Не вдалося відкрити довідку в браузері.")

    def visibility_changed(self, visible):
        if self.dock.picking:
            return
        self.settings.set_visible(visible)
        self.settings.values.setValue(PREFIX + "window_geometry", self.dock.saveGeometry())
        if not visible:
            self.cancel(silent=True)
            self.restore_tool()
            self.display.clear()
            self.functions.update_inputs()
            self.dock.settings_page.key.clear()
        else:
            self.functions.update_inputs()
            self.refresh_result_display()

    def refresh_result_display(self, *args):
        """Rebuild the active search overlay from local data only."""
        if not self.active or self.display is None or self.dock is None:
            return
        self.display.clear_selected()
        if not self.dock.isVisible() and not self.dock.picking:
            self.display.clear_results()
            return
        operation = self.dock.active_operation()
        if operation == "addresses":
            records = []
            for record in self.records:
                found, full = self.cache.peek(self.cache.identity, "feature", record.id)
                records.append(
                    replace(record, geometry=full[0]["geometry"])
                    if found and full and full[0].get("geometry")
                    else record
                )
            current = self.dock.results.currentRow()
        elif operation == "objects":
            page = self.dock.pages["objects"]
            records = [SearchResult.from_dict(record) for record in page.last_result or []]
            current = page.results.source_row(page.results.currentRow())
        else:
            self.display.clear_results()
            return
        try:
            self.display.set_results(records)
            if 0 <= current < len(records):
                self.display.show(records[current], recenter=False)
        except (ValueError, RuntimeError, QgsCsException):
            target = self.dock if operation == "addresses" else self.dock.pages[operation]
            target.status.set_status("Не вдалося відобразити результати на карті.", "error")

    def open_panel(self, checked=False):
        if self.dock.picking:
            self.functions.finish_pick(show=False)
            self.restore_tool(show=False)
        self.refresh_config()
        self.dock.show()
        self.dock.clamp_geometry()
        self.dock.raise_()
        self.dock.activateWindow()
        if self.dock.active_operation() == "addresses":
            self.dock.query.setFocus()
        self.functions.update_inputs()

    def refresh_credentials(self):
        try:
            credentials = self.settings.credentials()
        except ValueError as exc:
            self.dock.status.set_status(str(exc), "error")
            credentials = Credentials()
        changed = self.cache.identity != credentials.identity
        self.cache.set_identity(credentials.identity)
        if changed:
            self.update_quota()
        if self.locator is not None:
            self.locator.credentials = credentials
        return credentials

    def configure(self, mode=None):
        self.open_panel()
        self.dock.activate("settings")
        if mode in ("railway", "visicom"):
            self.dock.settings_page.mode.setCurrentIndex(1 if mode == "visicom" else 0)

    def settings_saved(self):
        if self.dock.settings_page.access_changed:
            self.cancel(silent=True)
            self.refresh_credentials()
            self.update_quota()
        self.update_controls()

    def address_query_edited(self, text: str) -> None:
        """Invalidate pending results as soon as the user changes the address."""
        self.cancel_tasks()

    def address_parameters_changed(self):
        self.cancel_tasks()
        self.settings.values.setValue(PREFIX + "reverse_radius", self.dock.reverse_radius.value())
        self.settings.set_auto_geometry(self.dock.auto_geometry.isChecked())
        self.settings.values.setValue(
            PREFIX + "auto_zoom/addresses", self.dock.auto_zoom.isChecked()
        )

    def access_error(self, notice):
        feedback = notice["feedback"]
        if (
            not self.active
            or self.cache.closed
            or notice["identity"] != self.cache.identity
            or notice["code"] != "daily_quota"
            or self.settings.mode() != "railway"
            or sip.isdeleted(feedback)
            or feedback.isCanceled()
        ):
            return
        day = notice.get("day")
        if not isinstance(day, str) or not QDate.fromString(day, "yyyy-MM-dd").isValid():
            day = NetworkClient.kyiv_day()
        identity = (notice["identity"], day)
        if identity in self.quota_notices:
            return
        self.quota_notices.add(identity)
        if self.quota_dialog is None:
            self.quota_dialog = QuotaDialog(self.iface.mainWindow())
        self.quota_dialog.show()
        self.quota_dialog.raise_()

    def search(self, text):
        if not 3 <= len(text.strip()) <= 500:
            self.dock.status.set_status("Введіть адресу від 3 до 500 символів.", "warning")
            return
        self.start("search", text.strip())

    def cancel_tasks(self, channel=None):
        channels = [channel] if channel else list(self.generations)
        for current in channels:
            self.generations[current] += 1
        for task in list(self.tasks):
            if task.channel in channels:
                task.callback = None
                task.cancel()
                self.tasks.discard(task)
        self.update_controls()

    def cancel(self, silent=False):
        if self.dock is not None:
            self.dock.search_timer.stop()
        if self.functions is not None:
            self.functions.cancel()
        pending = bool(self.tasks)
        active = (
            pending
            or (self.display is not None and self.display.has_overlays())
            or (self.tool is not None and self.iface.mapCanvas().mapTool() == self.tool)
        )
        self.cancel_tasks()
        if self.tool is not None:
            self.restore_tool()
        if self.display is not None:
            self.display.clear_selected()
        if self.dock is not None:
            self.update_controls()
            if active and not silent:
                self.dock.status.set_status(
                    "Запит скасовано." if pending else "Підсвічування очищено.",
                    "cancelled",
                )

    def start(self, operation, value=None):
        credentials = self.refresh_credentials()
        identity = credentials.identity
        channel = "feature" if operation == "feature" else "search"
        key = self.cache.key(identity, operation, value)
        for pending in self.tasks:
            pending_identity = pending.credentials.identity
            if (
                not pending.feedback.isCanceled()
                and self.cache.key(pending_identity, pending.operation, pending.value) == key
            ):
                return
        if operation == "feature":
            self.cancel_tasks("feature")
        else:
            found, cached_results = self.cache.peek(identity, operation, value)
            keep_geometry = (
                found
                and cached_results
                and any(
                    task.channel == "feature" and task.value == cached_results[0]["id"]
                    for task in self.tasks
                )
            )
            if keep_geometry:
                self.cancel_tasks("search")
            else:
                self.cancel_tasks()
        if not credentials.url or not credentials.token:
            if credentials.url:
                self.dock.status.set_status(
                    "Відкрийте налаштування й введіть власний ключ Visicom API.",
                    "warning",
                )
            return
        generation = self.generations[channel]
        if operation != "feature":
            self.dock.status.set_status("Пошук…", "running")
        else:
            self.dock.status.set_status("Отримання повної геометрії…", "running")

        def completed(task):
            self.tasks.discard(task)
            if not self.active or generation != self.generations[channel]:
                return
            self.update_controls()
            self.update_quota()
            if task.error:
                self.dock.status.set_status(task.error, "error")
                return
            if operation == "quota":
                remaining = task.result.get("remaining", "?")
                self.dock.status.set_status(
                    f"Доступно запитів сьогодні: {remaining} (Europe/Kyiv).", "success"
                )
            elif operation == "feature":
                if task.result and task.result[0].geometry:
                    self.refresh_result_display()
                    if self.show_record(task.result[0], cached=False):
                        self.dock.status.set_status(
                            self.result_status + " • Геометрію показано.", "success"
                        )
                else:
                    self.dock.status.set_status("Геометрію не знайдено.", "warning")
            else:
                first_id = task.result[0].id if task.result else None
                if any(t.channel == "feature" and t.value != first_id for t in self.tasks):
                    self.cancel_tasks("feature")
                self.records = task.result
                self.display.clear()
                self.dock.show_results(self.records, operation == "reverse")
                self.refresh_result_display()
                self.result_status = self.dock.status.text()
                if self.records:
                    self.dock.results.setCurrentCell(0, 0)
            if task.source != "network":
                self.dock.status.setText(self.dock.status.text() + " • З кешу сесії")

        task = RequestTask(credentials, operation, value, completed, self.cache)
        task.channel = channel
        self.tasks.add(task)
        self.update_controls()
        QgsApplication.taskManager().addTask(task)

    def select(self, index):
        if 0 <= index < len(self.records):
            record = self.records[index]
            if any(t.channel == "feature" and t.value != record.id for t in self.tasks):
                self.cancel_tasks("feature")
            self.show_record(record)
            if self.dock.auto_geometry.isChecked() and not record.geometry:
                found, cached = self.cache.peek(self.cache.identity, "feature", record.id)
                if found:
                    self.dock.status.set_status(self.result_status + " • З кешу сесії", "success")
                else:
                    self.start("feature", record.id)

    def show_record(self, record, cached=True, recenter=True):
        try:
            if cached and self.dock.auto_geometry.isChecked() and self.cache.identity is not None:
                found, records = self.cache.peek(self.cache.identity, "feature", record.id)
                if found and records:
                    record = SearchResult.from_dict(records[0])
            if cached and not self.dock.auto_geometry.isChecked():
                record = replace(record, geometry=None)
            self.display.show(record, recenter=recenter and self.dock.auto_zoom.isChecked())
            return True
        except (QgsCsException, ValueError) as exc:
            self.dock.status.set_status("Не вдалося показати об’єкт: " + str(exc), "error")
            return False

    def geometry_toggled(self, enabled):
        self.settings.set_auto_geometry(enabled)
        if not enabled:
            self.cancel_tasks("feature")
            index = self.dock.results.currentRow()
            if 0 <= index < len(self.records):
                self.show_record(self.records[index])
        else:
            self.select(self.dock.results.currentRow())

    def update_quota(self):
        if self.dock is None:
            return
        with self.cache.lock:
            quota = dict(self.cache.quota) if self.cache.quota else None
        if not quota:
            self.dock.quota.setText("Квота: ще немає даних")
            return
        if quota.get("local") and not self.settings.show_quota():
            text = f"Виконано запитів сьогодні: {quota.get('used', 0)}"
        else:
            prefix = "Оцінка залишку запитів до API" if quota.get("local") else "Доступно сьогодні"
            text = (
                f"{prefix}: {quota.get('remaining', '?')} / {quota.get('token_daily_limit', '?')}"
            )
            if quota.get("exceeded"):
                text += f" • Перевищення: {quota['exceeded']}"
        self.dock.quota.setText(text)
        self.dock.quota.setToolTip(
            "Europe/Kyiv • "
            + str(quota.get("day", ""))
            + (
                " • Лише цей плагін на цьому комп’ютері; перевищення не блокує запити."
                if quota.get("local")
                else " • З урахуванням спільного ліміту сервера."
            )
        )

    def show_geometry(self, index):
        if 0 <= index < len(self.records):
            self.start("feature", self.records[index].id)

    def activate_reverse(self):
        self.functions.cancel()
        self.cancel_tasks()
        canvas = self.iface.mapCanvas()
        self.reverse_picking = True
        self.dock.picking = True
        if canvas.mapTool() != self.tool:
            self.previous_tool = canvas.mapTool()
            canvas.setMapTool(self.tool)
        self.update_controls()
        self.dock.status.set_status(
            f"Клацніть на карті: найближча адреса в радіусі {self.dock.reverse_radius.value()} м.",
            "idle",
        )
        self.dock.hide()

    def set_reverse_enabled(self, enabled):
        if enabled:
            self.activate_reverse()
        else:
            self.restore_tool()
            self.update_controls()

    def restore_tool(self, show=True):
        was_picking = self.reverse_picking
        self.reverse_picking = False
        if was_picking and self.dock is not None:
            self.dock.picking = False
        previous_tool = self.previous_tool
        self.previous_tool = None
        if self.dock is not None:
            self.dock.set_reverse_active(False)
        canvas = self.iface.mapCanvas()
        if self.tool is None or canvas.mapTool() != self.tool:
            if was_picking and show and self.active:
                self.dock.show()
                self.dock.raise_()
            return
        if previous_tool is None or sip.isdeleted(previous_tool):
            canvas.unsetMapTool(self.tool)
        else:
            try:
                canvas.setMapTool(previous_tool)
            except RuntimeError:
                # Another tool can delete the previous one during map-tool signals.
                if not sip.isdeleted(previous_tool):
                    raise
                if canvas.mapTool() == self.tool:
                    canvas.unsetMapTool(self.tool)
        if was_picking and show and self.active:
            self.dock.show()
            self.dock.raise_()

    def reverse_at(self, map_point):
        try:
            coordinates = self.display.wgs84(map_point)
        except (QgsCsException, ValueError, RuntimeError):
            self.restore_tool()
            self.dock.status.set_status("Не вдалося перетворити координати кліку у WGS84.", "error")
            return
        self.restore_tool()
        self.start("reverse", (*coordinates, self.dock.reverse_radius.value()))

    def locator_activate(self, data):
        if not self.active or "addresses" not in self.enabled_operations:
            return
        self.open_panel()
        if not self.dock.activate("addresses"):
            return
        if data.get("error"):
            self.configure()
            return
        try:
            record = SearchResult.from_dict(data)
        except ValueError:
            self.dock.status.set_status("Некоректний результат Locator.", "error")
            return
        self.cancel_tasks()
        self.records = [record]
        self.dock.show_results(self.records)
        self.refresh_result_display()
        self.result_status = self.dock.status.text()
        self.dock.results.setCurrentCell(0, 0)

    def unload(self):
        if not self.active:
            return
        self.active = False
        if self.costs is not None:
            self.costs.close()
            self.costs = None
        self.cancel(silent=True)
        if self.functions is not None:
            self.functions.unload()
            self.functions = None
        self.cache.on_quota = None
        self.cache.on_error = None
        self.cache.close()
        self.browser_headers.remove()
        self.quota_notices.clear()
        if self.quota_dialog is not None:
            self.quota_dialog.close()
            self.quota_dialog.deleteLater()
            self.quota_dialog = None
        self.restore_tool()
        self.display.on_change = None
        self.display.clear()
        self.iface.mapCanvas().mapToolSet.disconnect(self.map_tool_changed)
        self.iface.mapCanvas().destinationCrsChanged.disconnect(self.refresh_result_display)
        if self.locator is not None:
            self.locator.activate = None
            self.iface.deregisterLocatorFilter(self.locator)
            self.locator = None
        self.iface.removePluginMenu("UA Geocoder", self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action.triggered.disconnect()
        self.action.deleteLater()
        self.dock.visibilityChanged.disconnect(self.visibility_changed)
        self.settings.values.setValue(PREFIX + "window_geometry", self.dock.saveGeometry())
        self.dock.close()
        self.dock.deleteLater()
        self.tool.coordinates_selected.disconnect(self.reverse_at)
        self.tool.finished.disconnect(self.restore_tool)
        self.tool.deleteLater()
        self.dock = None
        self.action = None
        self.tool = None
        self.display = None
        self.records = []
