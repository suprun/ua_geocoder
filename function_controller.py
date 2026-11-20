"""Interactive function pages and their asynchronous task lifecycle."""

import json
from copy import deepcopy
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer
from qgis.core import (
    QgsCsException,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsPointXY,
)
from .core.client import RequestTask
from .core.operations import validate_request
from .core.qgis_io import result_records
from .core.qgis_io import make_feature, output_fields
from .core.models import SearchResult
from .core.settings import PREFIX
from .map_tools import PointPickMapTool, RectanglePickMapTool
from .ui.search_area import search_geometry
from .input_overlays import InputOverlayManager, page_points, legend_text, editor_roles
from .search_area_preview import SearchAreaPreview
from .core.styles import appearance
from .ui.table_tools import zoom_geometries


class FunctionController:
    def __init__(self, plugin):
        self.plugin = plugin
        self.tasks = set()
        self.generation = 0
        self.active_tab = None
        self.pick_editor = None
        self.pick_area = False
        self.previous_tool = None
        self.tool = PointPickMapTool(plugin.iface.mapCanvas())
        self.tool.coordinates_selected.connect(self.picked)
        self.tool.finished.connect(self.finish_pick)
        self.area_tool = RectanglePickMapTool(plugin.iface.mapCanvas())
        self.area_tool.area_selected.connect(self.area_picked)
        self.area_tool.finished.connect(self.finish_pick)
        self.inputs = InputOverlayManager(plugin.iface.mapCanvas())
        self.pages = plugin.dock.pages
        self.area_preview = SearchAreaPreview(plugin.iface.mapCanvas())
        self.preview_timer = QTimer(plugin.dock)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(150)
        self.preview_timer.timeout.connect(self.refresh_previews)
        center = self.pages["objects"].editors["near"]
        center.longitude.textChanged.connect(self.update_inputs)
        center.latitude.textChanged.connect(self.update_inputs)
        self.pages["objects"].radius.valueChanged.connect(self.update_inputs)
        for page in self.pages.values():
            page.execute_requested.connect(self.execute)
            page.cancel_requested.connect(self.cancel)
            page.pick_requested.connect(self.activate_pick)
            page.zoom_requested.connect(lambda tab=page.operation: self.zoom_result(tab))
            for editor in page.editors.values():
                editor.zoom_requested.connect(self.zoom)
            page.parameters_changed.connect(self.parameters_changed)
            page.points_selection_changed.connect(self.update_inputs)
            if hasattr(page, "results"):
                page.results.itemSelectionChanged.connect(
                    lambda tab=page.operation: self.update_zoom(tab)
                )
                page.results.currentCellChanged.connect(
                    lambda row, column, old_row, old_column, tab=page.operation: self.preview(
                        tab, self.pages[tab].results.source_row(row)
                    )
                    if row != old_row
                    else None
                )
        options = self.pages["objects"].area_options
        options.pick_requested.connect(self.activate_area_pick)
        project = QgsProject.instance()
        project.layersAdded.connect(options.refresh_layers)
        project.layersRemoved.connect(options.refresh_layers)
        if hasattr(plugin.iface, "currentLayerChanged"):
            plugin.iface.currentLayerChanged.connect(self.active_layer_changed)
        self.active_layer_changed()
        plugin.dock.operation_changed.connect(self.tab_changed)

    def tab_changed(self):
        self.plugin.cancel(silent=True)
        self.plugin.restore_tool()
        operation = self.plugin.dock.active_operation()
        if operation:
            self.plugin.settings.values.setValue(PREFIX + "active_tab", operation)
        self.update_inputs()
        self.plugin.refresh_result_display()

    def active_layer_changed(self, *args):
        layer = getattr(self.plugin.iface, "activeLayer", lambda: None)()
        self.pages["objects"].area_options.set_active_layer(layer)

    def activate_area_pick(self):
        self.cancel()
        self.plugin.cancel_tasks()
        self.plugin.restore_tool()
        canvas = self.plugin.iface.mapCanvas()
        self.previous_tool = canvas.mapTool()
        self.pick_area = True
        self.preview_timer.stop()
        self.area_preview.clear()
        self.plugin.dock.picking = True
        canvas.setMapTool(self.area_tool)
        self.plugin.dock.hide()

    def area_picked(self, geometry):
        page = self.pages["objects"]
        try:
            geometry.transform(
                QgsCoordinateTransform(
                    self.plugin.iface.mapCanvas().mapSettings().destinationCrs(),
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance(),
                )
            )
            page.area_options.manual_area = json.loads(geometry.asJson())
            page.history.record()
            page.status.set_status("Область пошуку вибрано.", "success")
        except (ValueError, RuntimeError, QgsCsException):
            page.status.set_status("Не вдалося перетворити область у WGS84.", "error")

    def update_inputs(self, *args):
        if self.area_preview.closed:
            return
        page = self.plugin.dock.active_page()
        radius = (
            getattr(page, "operation", None) == "objects"
            and page.get_mode.currentIndex() == 0
            and page.scope.currentIndex() == 1
        )
        if radius and (self.plugin.dock.isVisible() or self.plugin.dock.picking):
            if self.area_preview.key and self.area_preview.key[0] != "radius":
                self.area_preview.clear()
            if any(item.role != "near" for item in self.inputs.items):
                self.inputs.clear()
            self.preview_timer.start()
        else:
            self.preview_timer.stop()
            self.refresh_previews()

    def refresh_previews(self):
        """Render the local draft without validating filters or changing undo history."""
        if not self.plugin.dock.isVisible() and not self.plugin.dock.picking:
            self.inputs.clear()
            self.area_preview.clear()
            return
        page = self.plugin.dock.active_page()
        if hasattr(page, "editors"):
            for key, editor in page.editors.items():
                editor.set_symbols(editor_roles(page, key))
        points = page_points(page)
        self.inputs.show(points)
        if hasattr(page, "legend"):
            page.legend.setText(legend_text(points))
            page.legend.setVisible(bool(points))
        if (
            getattr(page, "operation", None) != "objects"
            or page.get_mode.currentIndex() != 0
            or self.pick_area
        ):
            self.area_preview.clear()
            return
        try:
            if page.scope.currentIndex() == 1:
                center = page.editors["near"].preview_coordinates()
                if center is None:
                    self.area_preview.clear()
                else:
                    self.area_preview.show_radius(center, page.radius.value())
            elif (
                page.scope.currentIndex() == 2
                and page.area_options.extent_mode.currentData() == "rectangle"
            ):
                self.area_preview.show_rectangle(page.area_options.manual_area)
            else:
                self.area_preview.clear()
        except (ValueError, RuntimeError, QgsCsException):
            self.area_preview.clear()

    def parameters_changed(self):
        if self.tasks:
            self.cancel(restore_pick=False)
        page = self.pages["objects"]
        self.plugin.settings.values.setValue(
            PREFIX + "auto_zoom/objects", page.auto_zoom.isChecked()
        )
        self.plugin.settings.set_object_search_categories(page.categories.codes)
        self.update_inputs()

    def restore_tool(self, show=True):
        canvas = self.plugin.iface.mapCanvas()
        was_picking = self.pick_editor is not None or self.pick_area
        if was_picking:
            self.plugin.dock.picking = False
        previous = self.previous_tool
        self.previous_tool = None
        self.pick_editor = None
        self.pick_area = False
        pick_tool = canvas.mapTool()
        if pick_tool in (self.tool, self.area_tool):
            if previous is None or sip.isdeleted(previous):
                canvas.unsetMapTool(pick_tool)
            else:
                try:
                    canvas.setMapTool(previous)
                except RuntimeError:
                    if not sip.isdeleted(previous):
                        raise
                    if canvas.mapTool() == pick_tool:
                        canvas.unsetMapTool(pick_tool)
        if was_picking and show and self.plugin.active:
            self.plugin.dock.show()
            self.plugin.dock.raise_()
            self.update_inputs()
            self.plugin.refresh_result_display()

    def finish_pick(self, show=True):
        self.restore_tool(show=show)

    def external_tool_changed(self, current):
        if (self.pick_editor is not None and current != self.tool) or (
            self.pick_area and current != self.area_tool
        ):
            self.finish_pick()

    def activate_pick(self, editor):
        self.cancel()
        self.plugin.cancel_tasks()
        self.plugin.restore_tool()
        canvas = self.plugin.iface.mapCanvas()
        self.pick_editor = editor
        self.plugin.dock.picking = True
        if canvas.mapTool() != self.tool:
            self.previous_tool = canvas.mapTool()
            canvas.setMapTool(self.tool)
        self.plugin.dock.hide()
        self.update_inputs()

    def picked(self, position):
        if self.pick_editor is None:
            return
        editor = self.pick_editor
        single = editor is self.pages["objects"].editors["near"]
        try:
            coords = self.plugin.display.wgs84(QgsPointXY(position))
            editor.append(coords)
        except (ValueError, RuntimeError, QgsCsException):
            page = self.pages[self.plugin.dock.active_operation()]
            page.status.set_status("Не вдалося перетворити координати кліку у WGS84.", "error")
        finally:
            if single:
                self.finish_pick()

    def cancel(self, restore_pick=True):
        self.generation += 1
        for task in self.tasks:
            task.callback = None
            task.cancel()
        self.tasks.clear()
        for page in self.pages.values():
            if page.busy:
                page.status.set_status(
                    "Запит скасовано; попередній результат збережено.", "cancelled"
                )
            page.set_busy(False)
        self.active_tab = None
        if restore_pick:
            self.restore_tool()

    def search_area(self, page):
        layer = getattr(self.plugin.iface, "activeLayer", lambda: None)()
        return search_geometry(self.plugin.iface.mapCanvas(), page, layer)

    def execute(self, tab, override=None):
        if tab not in self.plugin.enabled_operations:
            return
        page = self.pages[tab]
        page.history.record()
        snapshot = deepcopy(page.snapshot())
        try:
            operation, value, ids = override or page.parameters()
            if operation == "objects" and page.scope.currentIndex() in (2, 3):
                value["area"] = self.search_area(page)
            value = validate_request(operation, value)
            credentials = self.plugin.refresh_credentials()
            if not credentials.token:
                raise ValueError("Налаштуйте доступ до API.")
        except (ValueError, RuntimeError, QgsCsException) as exc:
            page.status.set_status(str(exc), "error")
            return
        self.cancel()
        generation = self.generation
        self.active_tab = tab
        page.set_busy(True, operation)
        page.status.set_status("Виконується запит…", "running")

        def completed(task):
            self.tasks.discard(task)
            if generation != self.generation or not self.plugin.active:
                return
            if task.feedback.isCanceled():
                self.cancel()
                return
            # Compare immutable input too, including uncommitted text edits.
            if snapshot != page.snapshot():
                self.cancel()
                return
            self.active_tab = None
            page.set_busy(False)
            self.plugin.update_quota()
            if task.error:
                page.status.set_status(task.error + " Попередній результат збережено.", "error")
                return
            records = list(result_records(operation, task.result, value, ids))
            page.last_result = task.result
            page.show_records(records)
            self.plugin.refresh_result_display()
            if tab == "objects" and page.output_records:
                page.results.setCurrentCell(0, 0)
                page.results.scrollToTop()
            self.update_zoom(tab)
            status = f"Результатів: {len(page.output_records)}."
            if operation == "objects" and len(task.result) >= value["limit"]:
                status += " Досягнуто ліміту; вибірка може бути неповною."
            if task.source != "network":
                status += " З кешу сесії."
            limited = operation == "objects" and len(task.result) >= value["limit"]
            page.status.set_status(status, "warning" if limited or not records else "success")

        task = RequestTask(credentials, operation, value, completed, self.plugin.cache)
        self.tasks.add(task)
        QgsApplication.taskManager().addTask(task)

    def preview(self, tab, row, recenter=True):
        page = self.pages[tab]
        if not 0 <= row < len(page.output_records):
            return
        record = page.output_records[row]
        if not record.get("geometry"):
            return
        try:
            geom = make_feature(record, output_fields()).geometry()
            box = geom.boundingBox()
            center = box.center()
            result = SearchResult(
                str(row),
                str(record["attributes"].get("label") or page.title),
                "",
                tab,
                (center.x(), center.y()),
                (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()),
                geometry=record["geometry"],
            )
            self.plugin.display.show(
                result,
                recenter=recenter and (tab != "objects" or page.auto_zoom.isChecked()),
                style=appearance(tab, record["geometry"], record["attributes"]),
            )
        except (ValueError, RuntimeError, QgsCsException):
            page.status.set_status("Не вдалося відобразити геометрію результату.", "error")

    def zoom(self, geometries):
        try:
            return zoom_geometries(self.plugin.iface.mapCanvas(), geometries)
        except (ValueError, RuntimeError, QgsCsException):
            return False

    def result_geometries(self, tab):
        page = self.pages[tab]
        geometries = []
        rows = page.selected_rows() if tab == "objects" else range(len(page.output_records))
        for row in rows:
            record = page.output_records[row]
            if record.get("geometry"):
                geometries.append(record["geometry"])
        return geometries

    def update_zoom(self, tab):
        self.pages[tab].zoom_button.setEnabled(bool(self.result_geometries(tab)))

    def zoom_result(self, tab):
        self.zoom(self.result_geometries(tab))

    def unload(self):
        self.preview_timer.stop()
        self.preview_timer.timeout.disconnect(self.refresh_previews)
        center = self.pages["objects"].editors["near"]
        center.longitude.textChanged.disconnect(self.update_inputs)
        center.latitude.textChanged.disconnect(self.update_inputs)
        self.pages["objects"].radius.valueChanged.disconnect(self.update_inputs)
        self.area_preview.close()
        options = self.pages["objects"].area_options
        QgsProject.instance().layersAdded.disconnect(options.refresh_layers)
        QgsProject.instance().layersRemoved.disconnect(options.refresh_layers)
        if hasattr(self.plugin.iface, "currentLayerChanged"):
            self.plugin.iface.currentLayerChanged.disconnect(self.active_layer_changed)
        self.cancel()
        self.inputs.close()
        self.tool.coordinates_selected.disconnect(self.picked)
        self.tool.finished.disconnect(self.finish_pick)
        self.tool.deleteLater()
        self.area_tool.area_selected.disconnect(self.area_picked)
        self.area_tool.finished.disconnect(self.finish_pick)
        self.area_tool.deleteLater()
