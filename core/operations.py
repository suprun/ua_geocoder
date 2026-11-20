"""Validated, QGIS-independent Visicom operation contracts."""

import math
import json
import re
from typing import Any, List

from .models import InvalidProviderData, geometry, normalize, point

OPERATIONS = ("objects", "features")
MAX_OBJECT_REQUEST_BYTES = 65_536
PATHS = {
    "objects": "/v1/objects/search",
    "features": "/v1/features",
}


def limited(items: Any, maximum: int, label: str, minimum: int = 1) -> list:
    """Reject oversized jobs before any network activity; never split them."""
    if not isinstance(items, (list, tuple)):
        raise ValueError(label + ": потрібен список.")
    if not minimum <= len(items) <= maximum:
        raise ValueError(
            f"{label}: отримано {len(items)}, дозволено {minimum}–{maximum}. "
            "Автоматичного розбиття немає."
        )
    return list(items)


def _number(value: Any, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + ": потрібне число.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label}: дозволено {minimum}–{maximum}.")
    return value


def polygon(value: Any) -> dict:
    result = geometry(value)
    if not result or result["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError("Область пошуку має бути полігоном.")
    polygons = [result["coordinates"]] if result["type"] == "Polygon" else result["coordinates"]
    total = 0
    for rings in polygons:
        for ring in rings:
            total += len(ring)
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Кільце полігона має бути замкненим і містити від 4 вершин.")
    limited([None] * total, 250, "Вершини області пошуку", 4)
    return result


def validate_request(operation: str, value: Any) -> dict:
    """Return a canonical request shared by QGIS and the proxy."""
    if operation not in OPERATIONS or not isinstance(value, dict):
        raise ValueError("Невідома операція або некоректні параметри.")
    allowed = {
        "objects": {
            "categories",
            "categories_exclude",
            "text",
            "word_text",
            "limit",
            "near",
            "radius",
            "area",
            "order",
            "spatial_relation",
        },
        "features": {"ids"},
    }[operation]
    if set(value) - allowed:
        raise ValueError("Зайві параметри запиту.")
    result = {}
    if operation == "objects":
        if value.get("categories") is not None and value.get("categories_exclude") is not None:
            raise ValueError("Виберіть включення або виключення категорій.")
        for name in ("categories", "categories_exclude"):
            cats = value.get(name)
            if cats is None:
                continue
            if not isinstance(cats, list) or any(
                not isinstance(c, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", c) for c in cats
            ):
                raise ValueError("Некоректний ідентифікатор категорії.")
            if not cats and name == "categories":
                raise ValueError("Позначте хоча б одну категорію або виберіть «Усі».")
            if cats:
                result[name] = sorted(set(cats))
        if "text" in value and not isinstance(value["text"], str):
            raise ValueError("Текст пошуку має бути рядком.")
        if value.get("word_text") is not None and value.get("text", ""):
            raise ValueError("Виберіть частину тексту або цілі слова.")
        name = "word_text" if value.get("word_text") is not None else "text"
        text = value.get(name, "")
        if not isinstance(text, str) or len(text) > 500:
            raise ValueError("Текст пошуку: максимум 500 символів.")
        # Empty whole-word searches are identical to an unfiltered text search.
        result["word_text" if name == "word_text" and text.strip() else "text"] = text.strip()
        limit = value.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 250:
            raise ValueError("Ліміт результатів: дозволено 1–250.")
        result["limit"] = limit
        if value.get("near") is not None:
            if value.get("area") is not None:
                raise ValueError("Виберіть радіус або полігон, а не обидва.")
            result["near"] = list(point(value["near"]))
            result["radius"] = _number(value.get("radius"), 1, 20_000_000, "Радіус, м")
        elif "radius" in value:
            raise ValueError("Для радіуса потрібна центральна точка.")
        if value.get("area") is not None:
            result["area"] = polygon(value["area"])
        relation = value.get("spatial_relation", "contains")
        if relation not in ("contains", "intersect"):
            raise ValueError("Непідтримувана просторова умова.")
        if relation != "contains":
            if "area" not in result:
                raise ValueError("Для перетину потрібна область пошуку.")
            result["spatial_relation"] = relation
        default_order = "distance" if "near" in result else "relevance"
        order = value.get("order", default_order)
        if order not in ("relevance", "distance") or (order == "distance" and "near" not in result):
            raise ValueError("Сортування за відстанню потребує центра радіуса.")
        if order != default_order:
            result["order"] = order
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_OBJECT_REQUEST_BYTES:
            raise ValueError("Параметри пошуку завеликі; зменшіть список категорій або область.")
    elif operation == "features":
        ids = limited(value.get("ids", []), 250, "Ідентифікатори")
        if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", i) for i in ids):
            raise ValueError("Некоректний ідентифікатор об’єкта.")
        result["ids"] = list(dict.fromkeys(ids))
    return result


def requires_objects_v2(value: dict) -> bool:
    """Identify requests the original proxy contract cannot represent."""
    return (
        "categories" not in value
        or len(value["categories"]) > 100
        or any(
            name in value
            for name in (
                "categories_exclude",
                "word_text",
                "order",
                "spatial_relation",
            )
        )
    )


def object_filters(
    categories: List[str],
    category_mode: int,
    text: str,
    text_mode: int,
    order: int,
    relation: int,
    scope: int,
) -> dict:
    """Map search form choices without changing legacy default payloads."""
    result = {}
    if text_mode not in (0, 1) or order not in (0, 1, 2) or relation not in (0, 1):
        raise ValueError("Невідомий режим фільтра пошуку.")
    if category_mode == 0:
        result["categories"] = categories
    elif category_mode == 2 and categories:
        result["categories_exclude"] = categories
    elif category_mode not in (1, 2):
        raise ValueError("Невідомий режим категорій.")
    result["word_text" if text_mode == 1 else "text"] = text
    if order:
        result["order"] = {1: "relevance", 2: "distance"}[order]
    if relation == 1 and scope in (2, 3):
        result["spatial_relation"] = "intersect"
    return result


def _coordinates(items: list) -> str:
    return "|".join(f"{x:.12g},{y:.12g}" for x, y in items)


def _wkt(value: dict) -> str:
    def ring(items):
        return "(" + ",".join(f"{x:.12g} {y:.12g}" for x, y in items) + ")"

    def poly(items):
        return "(" + ",".join(ring(r) for r in items) + ")"

    if value["type"] == "Polygon":
        return "POLYGON" + poly(value["coordinates"])
    return "MULTIPOLYGON(" + ",".join(poly(p) for p in value["coordinates"]) + ")"


def upstream_request(operation: str, value: dict):
    """Return the fixed API branch, path and parameters, without credentials."""
    data = validate_request(operation, value)
    if operation == "objects":
        params = {
            "country": "ua",
            "limit": data["limit"],
        }
        for name in ("categories", "categories_exclude"):
            if name in data:
                params[name] = ",".join(data[name])
        for name in ("text", "word_text"):
            if data.get(name):
                params[name] = data[name]
        if "near" in data:
            params.update(
                near=_coordinates([data["near"]]), radius=data["radius"], order="distance"
            )
        if "area" in data:
            params[data.get("spatial_relation", "contains")] = _wkt(data["area"])
        if "order" in data:
            params["order"] = data["order"]
        return "uk", "geocode.json", params
    if operation == "features":
        return "uk", "feature/" + ",".join(data["ids"]) + ".json", {}


def normalize_response(operation: str, payload: Any, request: dict) -> Any:
    """Normalize search results from the provider."""
    validate_request(operation, request)
    if not isinstance(payload, dict):
        raise InvalidProviderData("Expected object")
    return [record.to_dict() for record in normalize(payload)]


def validate_result(operation: str, payload: Any, request: dict) -> Any:
    """Validate normalized search results received from the proxy."""
    from .models import SearchResult

    validate_request(operation, request)
    if not isinstance(payload, list):
        raise InvalidProviderData("Expected records")
    return [SearchResult.from_dict(item).to_dict() for item in payload]
