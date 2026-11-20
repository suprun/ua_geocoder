"""Read-only request forecasts. No authentication, networking or LRU mutation."""

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsCsException
from .core.operations import validate_request


class RequestCosts:
    def __init__(self, plugin):
        self.plugin = plugin
        self.timer = QTimer(plugin.dock)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        plugin.dock.query.textChanged.connect(self.refresh)
        for page in plugin.dock.pages.values():
            page.parameters_changed.connect(self.refresh)
        plugin.dock.operation_changed.connect(self.refresh)
        self.timer.start()
        self.stamp = None
        self.refresh()

    def poll(self):
        stamp = (id(self.plugin.cache), self.plugin.cache.revision)
        if stamp != self.stamp:
            self.refresh()

    def inspect(self, operation, value):
        return self.plugin.cache.inspect(self.plugin.cache.identity, operation, value)

    def count(self, operation, value):
        if operation in ("objects", "features"):
            value = validate_request(operation, value)
        return int(self.inspect(operation, value)[0] == "missing")

    def label(self, button, text, minimum, maximum=None, per_click=False):
        maximum = minimum if maximum is None else maximum
        amount = str(minimum) if minimum == maximum else f"{minimum}–{maximum}"
        suffix = (
            "запит"
            if maximum % 10 == 1 and maximum % 100 != 11
            else "запити"
            if maximum % 10 in (2, 3, 4) and maximum % 100 not in (12, 13, 14)
            else "запитів"
        )
        if per_click:
            suffix += "/клік"
        button.setText(
            f"{text} · {amount} {suffix}" if self.plugin.settings.show_request_counts() else text
        )
        button.setToolTip(
            f"{text}. Нових запитів Visicom: {amount}"
            + (" на один клік." if per_click else ".")
            + " Оцінка враховує кеш; скасування відправленого запиту не повертає квоту."
        )

    def address_cost(self):
        window = self.plugin.dock
        text = window.query.text().strip()
        if not 3 <= len(text) <= 500:
            return 0, 0
        state, results = self.inspect("search", text)
        base = int(state == "missing")
        if not window.auto_geometry.isChecked():
            return base, base
        if state == "cached":
            extra = (
                self.count("feature", results[0]["id"])
                if results and not results[0].get("geometry")
                else 0
            )
            return extra, extra
        return base, base + 1

    def refresh(self, *args):
        plugin, window = self.plugin, self.plugin.dock
        if not plugin.active or window is None:
            return
        self.stamp = (id(plugin.cache), plugin.cache.revision)
        if not window.search_busy:
            self.label(window.search_button, "Знайти", *self.address_cost())
        self.label(
            window.reverse_button,
            "Знайти адресу за координатами на карті",
            0,
            2 if window.auto_geometry.isChecked() else 1,
            per_click=True,
        )
        for page in window.pages.values():
            if page.busy:
                continue
            try:
                operation, value, _ = page.parameters()
                if operation == "objects" and page.scope.currentIndex() in (2, 3):
                    value["area"] = plugin.functions.search_area(page)
                count = self.count(operation, value)
            except (ValueError, RuntimeError, QgsCsException):
                count = 0
            self.label(page.execute_button, page.execute_title, count)

    def close(self):
        self.timer.stop()
