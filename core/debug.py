"""Console diagnostics shared by API requests, without QGIS dependencies."""

import json
import re
import threading
import traceback
from typing import Optional, Sequence
from urllib.parse import quote, quote_plus

_OUTPUT_LOCK = threading.Lock()
_SECRET_FIELD = re.compile(
    r"""(?ix)(?<![\w-])(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|
    authorization|upstream[_-]?url|key)["']?\s*[:=]\s*)
    ("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&<>{}"']+)"""
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s\"'<>,;]+")
_PROVIDER_URL = re.compile(r"""https?:(?:\\?/){2}api\.visicom\.ua[^\s"'<>]*""", re.IGNORECASE)


def redact_debug_text(text: str, secrets: Sequence[str] = ()) -> str:
    """Mask credentials and provider URLs while preserving the response text."""
    text = _PROVIDER_URL.sub("[REDACTED URL]", text)
    text = _BEARER.sub("[REDACTED]", text)
    text = _SECRET_FIELD.sub(lambda match: match.group(1) + '"[REDACTED]"', text)
    variants = set()
    for secret in secrets:
        if secret:
            variants.update((
                secret, quote(secret, safe=""), quote_plus(secret),
                json.dumps(secret, ensure_ascii=True)[1:-1],
                secret.replace("/", r"\/"),
            ))
    # Replace longer values first, so a base URL cannot leave its full variant behind.
    for secret in sorted(variants, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def write_debug(
    message: str,
    secrets: Sequence[str] = (),
    exception: Optional[BaseException] = None,
) -> None:
    """Write one serialized diagnostic block, including a sanitized traceback."""
    try:
        if exception is not None:
            message += "\n" + "".join(traceback.format_exception(
                type(exception), exception, exception.__traceback__
            ))
        message = redact_debug_text(message, secrets)
        with _OUTPUT_LOCK:
            print("[UA Geocoder API] " + message, flush=True)
    except (OSError, ValueError, RuntimeError):
        # A closed QGIS console or an encoding failure must not break the API request.
        return
