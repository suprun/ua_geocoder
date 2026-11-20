"""Offline provider category names; no QGIS imports or runtime networking."""

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Iterable, List, Tuple

CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources/categories_uk.json"
GROUPS = ("Адреси й вулиці", "Адміністративні території", "Дороги", "Точки інтересу")


def valid_code(code: str) -> bool:
    """Accept provider-style identifiers without guessing corrections."""
    return isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) is not None


def split_codes(value: str) -> List[str]:
    """Parse a comma/newline list while preserving unknown identifiers."""
    return sorted({code.strip() for code in re.split(r"[,\n\r]+", value) if code.strip()})


@lru_cache(maxsize=1)
def category_catalog() -> Tuple[dict, ...]:
    """Read the bundled, attributed snapshot once per plugin load."""
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return tuple(payload["categories"])


@lru_cache(maxsize=1)
def _category_labels() -> dict:
    """Cache both display forms independently of Qt and the worker thread."""
    return {
        item["id"]: (
            item.get("singlename") or item.get("name") or item["id"],
            item.get("name") or item["id"],
        )
        for item in category_catalog()
    }


def category_alias(value: str, singular: bool = True) -> str:
    """Format every component without changing the provider's category codes."""
    if not isinstance(value, str):
        return ""
    codes = dict.fromkeys(code.strip() for code in re.split(r"[,\n\r]+", value) if code.strip())
    names = _category_labels()
    column = 0 if singular else 1
    return ", ".join(names.get(code, (code, code))[column] for code in codes)


def category_group(code: str) -> str:
    """Group the flat catalog for presentation only."""
    if code.startswith("adr_"):
        return GROUPS[0]
    if code.startswith(("adm_", "hst_")):
        return GROUPS[1]
    return GROUPS[2] if code.startswith("roa_") else GROUPS[3]


def category_summary(codes: Iterable[str]) -> str:
    """Summarize selected labels, keeping duplicate names distinguishable in the tree."""
    values = list(codes)
    if not values:
        return "Нічого не позначено"
    labels = [category_alias(code, singular=False) for code in values[:2]]
    return ", ".join(labels) + (f" та ще {len(values) - 2}" if len(values) > 2 else "")
