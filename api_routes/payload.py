from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import request


def dict_payload(value: Any) -> dict:
    """Return a dict payload or an empty dict for malformed optional settings."""
    return value if isinstance(value, dict) else {}


def bool_payload(value: Any, default: bool = False) -> bool:
    """Parse bool-ish JSON/form values without treating every string as truthy."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return default


def request_json_object(*, force: bool = True) -> dict:
    """Read a JSON object request body without throwing on malformed input."""
    return dict_payload(request.get_json(force=force, silent=True))


def parse_video_mode_payload(
    payload: dict,
    *,
    default_video_mode: str,
    video_modes: dict,
    normalize_video_mode: Callable[[str], str],
) -> str:
    payload = dict_payload(payload)
    requested_mode = str(
        payload.get("mode")
        or payload.get("video_mode")
        or payload.get("videoMode")
        or default_video_mode
    ).strip().lower()
    if requested_mode not in video_modes:
        expected = ", ".join(video_modes.keys())
        raise ValueError(f"Invalid mode '{requested_mode}'. Expected one of: {expected}")
    return normalize_video_mode(requested_mode)
