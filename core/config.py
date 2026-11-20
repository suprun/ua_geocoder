"""Strict local search feature switches."""

import json
from pathlib import Path

OPERATIONS = ("addresses", "objects")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


def load_config(path=None):
    try:
        value = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
    except (OSError, ValueError):
        return set(), "Не вдалося прочитати config.json. Перевірте файл конфігурації плагіна."
    return {key for key in OPERATIONS if value.get(key) is True}, ""
