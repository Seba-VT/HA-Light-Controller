"""File-backed controller storage."""

from __future__ import annotations

import json
import os

from .const import (
    CONF_BRIGHTNESS_MAX_PCT,
    CONF_BRIGHTNESS_MIN_PCT,
    CONF_CT_MAX_KELVIN,
    CONF_CT_MIN_KELVIN,
    CONF_INPUT_LIGHTS,
    CONF_LIMITS,
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_WEATHER_MIN_KELVIN,
    CONFIG_PATH,
)


def _normalize_controller(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None

    name = raw.get(CONF_NAME)
    unique_id = raw.get(CONF_UNIQUE_ID)
    input_lights = raw.get(CONF_INPUT_LIGHTS)

    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(unique_id, str) or not unique_id.strip():
        return None
    if not isinstance(input_lights, list):
        input_lights = []

    cleaned_inputs = [item for item in input_lights if isinstance(item, str) and item.strip()]

    controller = {
        CONF_NAME: name.strip(),
        CONF_UNIQUE_ID: unique_id.strip(),
        CONF_INPUT_LIGHTS: cleaned_inputs,
    }

    circadian = raw.get("circadian")
    if isinstance(circadian, dict):
        controller["circadian"] = {
            "enabled": bool(circadian.get("enabled", True)),
            "brightness_enabled": bool(circadian.get("brightness_enabled", True)),
            "color_temp_enabled": bool(circadian.get("color_temp_enabled", True)),
        }

    limits = raw.get(CONF_LIMITS)
    if isinstance(limits, dict):
        brightness_min = limits.get(CONF_BRIGHTNESS_MIN_PCT)
        brightness_max = limits.get(CONF_BRIGHTNESS_MAX_PCT)
        ct_min = limits.get(CONF_CT_MIN_KELVIN)
        ct_max = limits.get(CONF_CT_MAX_KELVIN)
        weather_min = limits.get(CONF_WEATHER_MIN_KELVIN)
        if isinstance(brightness_min, (int, float)) and isinstance(brightness_max, (int, float)):
            controller[CONF_LIMITS] = {
                CONF_BRIGHTNESS_MIN_PCT: int(brightness_min),
                CONF_BRIGHTNESS_MAX_PCT: int(brightness_max),
            }
        if isinstance(ct_min, (int, float)) and isinstance(ct_max, (int, float)):
            controller.setdefault(CONF_LIMITS, {})
            controller[CONF_LIMITS].update(
                {
                    CONF_CT_MIN_KELVIN: int(ct_min),
                    CONF_CT_MAX_KELVIN: int(ct_max),
                }
            )
        if isinstance(weather_min, (int, float)):
            controller.setdefault(CONF_LIMITS, {})
            controller[CONF_LIMITS][CONF_WEATHER_MIN_KELVIN] = int(weather_min)

    return controller


def _load_controllers_sync() -> list[dict]:
    if not os.path.exists(CONFIG_PATH):
        return []

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, dict):
        controllers = data.get("controllers", [])
    elif isinstance(data, list):
        controllers = data
    else:
        return []

    normalized = []
    for item in controllers:
        controller = _normalize_controller(item)
        if controller:
            normalized.append(controller)

    return normalized


async def async_load_controllers(hass) -> list[dict]:
    """Load controllers from /config/svtlc_controllers.json."""
    return await hass.async_add_executor_job(_load_controllers_sync)
