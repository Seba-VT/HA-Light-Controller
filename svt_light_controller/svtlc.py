"""SVT Light Controller add-on MQTT bridge."""

import json
import logging
import math
import os
import random
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
CONFIG_PATH = "/config/svtlc_controllers.json"
RUNTIME_PATH = "/config/svtlc_runtime.json"
TOPIC_INPUTS = "svtlc/+/inputs"
TOPIC_EVENTS = "svtlc/+/event"
TOPIC_CIRCADIAN_SET = "svtlc/+/circadian/set"
TOPIC_CIRCADIAN_STATE = "svtlc/{}/circadian"
TOPIC_LIMITS_SET = "svtlc/+/limits/set"
TOPIC_LIMITS_STATE = "svtlc/{}/limits"
TOPIC_MODE_SET = "svtlc/+/mode/set"
TOPIC_MODE_STATE = "svtlc/{}/mode"
TOPIC_AWAY_STATE = "svtlc/{}/away"
TOPIC_INPUTS_STATUS = "svtlc/{}/inputs/status"
SUN_ENTITY_ID = "sun.sun"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")
HA_CONFIG_URL = "http://supervisor/core/api/config"
RETRY_COMMANDS = {
    "turn_off_inputs",
    "turn_on_inputs",
    "set_brightness_inputs",
    "set_color_inputs",
    "set_effect_inputs",
}
RETRY_CONFIG = {"enabled": True, "delay_seconds": 2, "max_retries": 3}
RETRY_PENDING: dict[str, dict] = {}
RETRY_TOLERANCES = {
    "brightness": 2,
    "ct_kelvin": 25,
    "hs": 3.0,
    "rgb": 3,
    "xy": 0.01,
}


def _load_options() -> dict:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def _parse_payload(payload: bytes | str):
    if isinstance(payload, (bytes, bytearray)):
        text = payload.decode("utf-8", "ignore")
    else:
        text = str(payload)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text



def _normalize_controller_id(value: str) -> str:
    return f"svtlc_{value.strip().lower().replace(' ', '_')}"


def _load_controllers_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"controllers": [], "master": {}}
    except json.JSONDecodeError:
        return {"controllers": [], "master": {}}

    if isinstance(payload, list):
        return {"controllers": payload, "master": {}}

    if not isinstance(payload, dict):
        return {"controllers": [], "master": {}}

    controllers = payload.get("controllers")
    master = payload.get("master") if isinstance(payload.get("master"), dict) else {}
    return {
        "controllers": controllers if isinstance(controllers, list) else [],
        "master": master,
    }


def _write_config_payload(payload: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = f"{CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp_path, CONFIG_PATH)


def _read_runtime_payload() -> dict:
    if not os.path.exists(RUNTIME_PATH):
        return {"circadian_interval": 60, "wakeup_interval": 2, "modes": {}}
    try:
        with open(RUNTIME_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"circadian_interval": 60, "wakeup_interval": 2, "modes": {}}
    if not isinstance(data, dict):
        return {"circadian_interval": 60, "wakeup_interval": 2, "modes": {}}

    interval = data.get("circadian_interval")
    if not isinstance(interval, int) or not (1 <= interval <= 3600):
        interval = 60
    wakeup_interval = data.get("wakeup_interval")
    if not isinstance(wakeup_interval, int) or not (1 <= wakeup_interval <= 3600):
        wakeup_interval = 2
    modes = data.get("modes")
    if not isinstance(modes, dict):
        modes = {}
    return {"circadian_interval": interval, "wakeup_interval": wakeup_interval, "modes": modes}


def _write_runtime_payload(payload: dict) -> None:
    current = _read_runtime_payload()
    if "modes" in payload and isinstance(payload.get("modes"), dict):
        modes = current.get("modes", {})
        if not isinstance(modes, dict):
            modes = {}
        modes.update(payload["modes"])
        current["modes"] = modes
        payload = {k: v for k, v in payload.items() if k != "modes"}
    current.update(payload)
    os.makedirs(os.path.dirname(RUNTIME_PATH), exist_ok=True)
    tmp_path = f"{RUNTIME_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2)
    os.replace(tmp_path, RUNTIME_PATH)


def _update_circadian_settings(controller_id: str, brightness_enabled: bool | None, color_temp_enabled: bool | None) -> bool:
    payload = _load_controllers_config()
    updated = False

    for controller in payload.get("controllers", []):
        if not isinstance(controller, dict):
            continue
        unique_id = controller.get("unique_id") or controller.get("name")
        if not isinstance(unique_id, str) or not unique_id:
            continue
        if _normalize_controller_id(unique_id) != controller_id:
            continue

        circadian = controller.get("circadian")
        if not isinstance(circadian, dict):
            circadian = {}
            controller["circadian"] = circadian

        if brightness_enabled is not None:
            circadian["brightness_enabled"] = bool(brightness_enabled)
            updated = True
        if color_temp_enabled is not None:
            circadian["color_temp_enabled"] = bool(color_temp_enabled)
            updated = True

    if updated:
        _write_config_payload(payload)

    return updated


def _normalize_limits(limits: dict | None) -> dict:
    if not isinstance(limits, dict):
        limits = {}

    def _to_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _clamp(value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, int(value)))

    brightness_min = _clamp(_to_int(limits.get("brightness_min_pct"), 1), 1, 100)
    brightness_max = _clamp(_to_int(limits.get("brightness_max_pct"), 100), 1, 100)
    if brightness_min > brightness_max:
        brightness_min, brightness_max = brightness_max, brightness_min

    ct_min = _clamp(_to_int(limits.get("ct_min_kelvin"), 2000), 1500, 8000)
    ct_max = _clamp(_to_int(limits.get("ct_max_kelvin"), 6500), 1500, 8000)
    if ct_min > ct_max:
        ct_min, ct_max = ct_max, ct_min

    weather_min = _clamp(_to_int(limits.get("weather_min_kelvin"), 2300), 1500, 8000)

    return {
        "brightness_min_pct": brightness_min,
        "brightness_max_pct": brightness_max,
        "ct_min_kelvin": ct_min,
        "ct_max_kelvin": ct_max,
        "weather_min_kelvin": weather_min,
    }


def _update_limits(controller_id: str, payload: dict) -> bool:
    config = _load_controllers_config()
    updated = False

    for controller in config.get("controllers", []):
        if not isinstance(controller, dict):
            continue
        unique_id = controller.get("unique_id") or controller.get("name")
        if not isinstance(unique_id, str) or not unique_id:
            continue
        if _normalize_controller_id(unique_id) != controller_id:
            continue

        current_limits = _normalize_limits(controller.get("limits"))
        merged_limits = dict(current_limits)

        for key in ("brightness_min_pct", "brightness_max_pct", "ct_min_kelvin", "ct_max_kelvin", "weather_min_kelvin"):
            if key in payload and isinstance(payload[key], (int, float)):
                merged_limits[key] = int(round(payload[key]))

        normalized = _normalize_limits(merged_limits)
        if normalized != current_limits:
            controller["limits"] = normalized
            updated = True

    if updated:
        _write_config_payload(config)

    return updated


def _normalize_mode(value: str | None) -> str:
    if not isinstance(value, str):
        return "Circadian"
    cleaned = value.strip().lower()
    modes = {
        "circadian": "Circadian",
        "manual": "Manual",
        "wakeup": "WakeUp",
        "sleep": "Sleep",
        "away": "Away",
    }
    return modes.get(cleaned, "Circadian")


def _update_mode(controller_id: str, mode: str) -> bool:
    payload = _load_controllers_config()
    updated = False
    normalized = _normalize_mode(mode)

    for controller in payload.get("controllers", []):
        if not isinstance(controller, dict):
            continue
        unique_id = controller.get("unique_id") or controller.get("name")
        if not isinstance(unique_id, str) or not unique_id:
            continue
        if _normalize_controller_id(unique_id) != controller_id:
            continue

        if controller.get("mode") != normalized:
            controller["mode"] = normalized
            updated = True

    if updated:
        _write_config_payload(payload)

    return updated


def _set_mode_local(controller_id: str, mode: str, last_modes: dict[str, dict]) -> None:
    normalized = _normalize_mode(mode)
    last_modes[controller_id] = {"mode": normalized}
    _write_runtime_payload({"modes": {controller_id: normalized}})


def _publish_mode_state(client, controller_id: str, mode: str) -> None:
    state_topic = TOPIC_MODE_STATE.format(controller_id)
    payload = {"mode": _normalize_mode(mode)}
    client.publish(state_topic, json.dumps(payload), qos=0, retain=True)


def _publish_away_state(client, controller_id: str, payload: dict) -> None:
    state_topic = TOPIC_AWAY_STATE.format(controller_id)
    client.publish(state_topic, json.dumps(payload), qos=0, retain=True)


def _sync_mode_with_switches(
    controller_id: str,
    controller_cfg: dict | None,
    brightness_enabled: bool,
    color_temp_enabled: bool,
    current_mode: str | None = None,
) -> str:
    raw_mode = current_mode
    if raw_mode is None and isinstance(controller_cfg, dict):
        raw_mode = controller_cfg.get("mode")
    has_mode = isinstance(raw_mode, str)
    mode_value = _normalize_mode(raw_mode)

    if mode_value in ("Away", "Sleep", "WakeUp") and has_mode:
        return mode_value

    desired = "Circadian" if (brightness_enabled or color_temp_enabled) else "Manual"
    if desired != mode_value:
        _update_mode(controller_id, desired)
    return desired


def _publish_circadian_state(client, controller_id: str, brightness_enabled: bool, color_temp_enabled: bool) -> None:
    state_topic = TOPIC_CIRCADIAN_STATE.format(controller_id)
    payload = {
        "brightness_enabled": bool(brightness_enabled),
        "color_temp_enabled": bool(color_temp_enabled),
    }
    client.publish(state_topic, json.dumps(payload), qos=0, retain=True)


def _set_circadian_flags(
    client,
    controller_id: str,
    last_settings: dict[str, dict],
    brightness_enabled: bool | None = None,
    color_temp_enabled: bool | None = None,
    persist: bool = False,
) -> None:
    current = last_settings.get(controller_id, {"brightness_enabled": True, "color_temp_enabled": True})
    next_state = {
        "brightness_enabled": current.get("brightness_enabled", True),
        "color_temp_enabled": current.get("color_temp_enabled", True),
    }

    if brightness_enabled is not None:
        next_state["brightness_enabled"] = bool(brightness_enabled)
    if color_temp_enabled is not None:
        next_state["color_temp_enabled"] = bool(color_temp_enabled)

    if next_state == current:
        return

    if persist:
        _update_circadian_settings(controller_id, brightness_enabled, color_temp_enabled)

    last_settings[controller_id] = next_state
    _publish_circadian_state(
        client,
        controller_id,
        next_state["brightness_enabled"],
        next_state["color_temp_enabled"],
    )


def _parse_iso(ts: str) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_sun_times() -> dict | None:
    if not SUPERVISOR_TOKEN:
        return None
    url = f"http://supervisor/core/api/states/{SUN_ENTITY_ID}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    return data.get("attributes") if isinstance(data.get("attributes"), dict) else None


def _fetch_ha_config() -> dict | None:
    if not SUPERVISOR_TOKEN:
        return None
    req = Request(HA_CONFIG_URL)
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _fetch_entity_state(entity_id: str) -> dict | None:
    if not SUPERVISOR_TOKEN or not entity_id:
        return None
    url = f"http://supervisor/core/api/states/{entity_id}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_visibility_km(state: dict | None) -> float | None:
    if not state:
        return None
    value = _parse_float(state.get("state"))
    if value is None:
        return None
    unit = None
    attrs = state.get("attributes")
    if isinstance(attrs, dict):
        unit = attrs.get("unit_of_measurement")
    if isinstance(unit, str) and unit.lower() in {"m", "meter", "meters"}:
        return value / 1000.0
    if isinstance(unit, str) and unit.lower() in {"km", "kilometer", "kilometers"}:
        return value
    return value / 1000.0 if value > 1000 else value


def _normalize_weather_config(master: dict) -> dict:
    weather = master.get("weather") if isinstance(master, dict) else {}
    if not isinstance(weather, dict):
        weather = {}
    def _weight(value: object, fallback: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return fallback
    return {
        "cloud_sensor": str(weather.get("cloud_sensor") or ""),
        "uv_sensor": str(weather.get("uv_sensor") or ""),
        "visibility_sensor": str(weather.get("visibility_sensor") or ""),
        "weather_code_sensor": str(weather.get("weather_code_sensor") or ""),
        "uv_max": max(1.0, float(weather.get("uv_max", 8))),
        "visibility_max_km": max(1.0, float(weather.get("visibility_max_km", 10))),
        "max_reduction_pct": max(0.0, min(100.0, float(weather.get("max_reduction_pct", 60)))),
        "cloud_weight": _weight(weather.get("cloud_weight", 0.55), 0.55),
        "uv_weight": _weight(weather.get("uv_weight", 0.3), 0.3),
        "visibility_weight": _weight(weather.get("visibility_weight", 0.15), 0.15),
    }


def _normalize_away_config(master: dict) -> dict:
    away = master.get("away") if isinstance(master, dict) else {}
    if not isinstance(away, dict):
        away = {}

    def _to_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    start_minutes = max(0, min(1439, _to_int(away.get("start_minutes"), 360)))
    end_minutes = max(0, min(1439, _to_int(away.get("end_minutes"), 1350)))
    min_minutes = max(1, min(1440, _to_int(away.get("min_minutes"), 30)))
    max_minutes = max(min_minutes, min(1440, _to_int(away.get("max_minutes"), 180)))
    offset_minutes = max(0, min(180, _to_int(away.get("offset_minutes"), 30)))

    return {
        "start_minutes": start_minutes,
        "end_minutes": end_minutes,
        "min_minutes": min_minutes,
        "max_minutes": max_minutes,
        "offset_minutes": offset_minutes,
    }


def _normalize_sleep_config(master: dict, controller: dict | None) -> dict:
    master_sleep = master.get("sleep") if isinstance(master, dict) else {}
    if not isinstance(master_sleep, dict):
        master_sleep = {}
    controller_sleep = controller.get("sleep") if isinstance(controller, dict) else {}
    if not isinstance(controller_sleep, dict):
        controller_sleep = {}

    use_master = controller_sleep.get("use_master") is not False

    def _pick_value(key: str, default):
        if not use_master:
            value = controller_sleep.get(key)
            if value is not None:
                return value
        value = master_sleep.get(key)
        return value if value is not None else default

    def _to_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _to_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    brightness_pct = max(1, min(100, _to_int(_pick_value("brightness_pct", 10), 10)))
    color_temp_kelvin = max(1500, min(8000, _to_int(_pick_value("color_temp_kelvin", 2200), 2200)))

    hs_value = _pick_value("hs_color", [30, 70])
    if isinstance(hs_value, list) and len(hs_value) >= 2:
        hue = _to_float(hs_value[0], 30.0)
        sat = _to_float(hs_value[1], 70.0)
    else:
        hue = 30.0
        sat = 70.0
    hue = max(0.0, min(360.0, hue))
    sat = max(0.0, min(100.0, sat))

    return {
        "use_master": use_master,
        "brightness_pct": brightness_pct,
        "color_temp_kelvin": color_temp_kelvin,
        "hs_color": [hue, sat],
    }

def _normalize_retry_config(master: dict) -> dict:
    retry = master.get("retry") if isinstance(master, dict) else {}
    if not isinstance(retry, dict):
        retry = {}

    def _to_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _to_float(value, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    enabled = retry.get("enabled") is not False
    delay_seconds = max(1, min(60, _to_int(retry.get("delay_seconds"), 2)))
    max_retries = max(1, min(10, _to_int(retry.get("max_retries"), 3)))
    tolerance_brightness = max(0, min(10, _to_int(retry.get("tolerance_brightness"), 2)))
    tolerance_ct_k = max(0, min(500, _to_int(retry.get("tolerance_ct_k"), 25)))
    tolerance_hs = max(0.0, min(30.0, _to_float(retry.get("tolerance_hs"), 3.0)))
    tolerance_rgb = max(0, min(20, _to_int(retry.get("tolerance_rgb"), 3)))
    tolerance_xy = max(0.0, min(0.2, _to_float(retry.get("tolerance_xy"), 0.01)))
    return {
        "enabled": enabled,
        "delay_seconds": delay_seconds,
        "max_retries": max_retries,
        "tolerance_brightness": tolerance_brightness,
        "tolerance_ct_k": tolerance_ct_k,
        "tolerance_hs": tolerance_hs,
        "tolerance_rgb": tolerance_rgb,
        "tolerance_xy": tolerance_xy,
    }


def _retry_key(controller_id: str, command: str, targets: list[str]) -> str:
    normalized = ",".join(sorted(targets))
    return f"{controller_id}:{command}:{normalized}"


def _queue_retry_entry(
    controller_id: str,
    command: str,
    targets: list[str],
    brightness: int | None,
    color_payload: dict | None,
    effect: str | None,
) -> None:
    if not RETRY_CONFIG.get("enabled"):
        return
    if command not in RETRY_COMMANDS:
        return
    if not targets:
        return
    key = _retry_key(controller_id, command, targets)
    RETRY_PENDING[key] = {
        "controller_id": controller_id,
        "command": command,
        "targets": list(targets),
        "brightness": brightness,
        "color_payload": color_payload or {},
        "effect": effect,
        "attempts": 0,
        "next_ts": time.time() + float(RETRY_CONFIG.get("delay_seconds", 2)),
        "created_ts": time.time(),
    }


def _is_unavailable(value: dict) -> bool:
    return str(value.get("state", "")).strip().lower() in {"unknown", "unavailable"}


def _value_close(a: float | int | None, b: float | int | None, tol: float) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def _state_color_temp_kelvin(value: dict) -> int | None:
    ct_k = value.get("color_temp_kelvin")
    if isinstance(ct_k, (int, float)):
        return int(round(ct_k))
    ct_mireds = value.get("color_temp")
    if isinstance(ct_mireds, (int, float)) and ct_mireds > 0:
        return int(round(1000000.0 / float(ct_mireds)))
    return None


def _extract_rgb(value: dict) -> list[int] | None:
    rgb = value.get("rgb_color")
    if isinstance(rgb, list) and len(rgb) == 3:
        return rgb
    rgbw = value.get("rgbw_color")
    if isinstance(rgbw, list) and len(rgbw) >= 3:
        return rgbw[:3]
    rgbww = value.get("rgbww_color")
    if isinstance(rgbww, list) and len(rgbww) >= 3:
        return rgbww[:3]
    return None


def _color_payload_matches(value: dict, payload: dict) -> bool:
    if not payload:
        return True
    desired = {
        key: payload[key]
        for key in (
            "hs_color",
            "rgb_color",
            "rgbw_color",
            "rgbww_color",
            "xy_color",
            "color_temp",
            "color_temp_kelvin",
        )
        if key in payload
    }
    if not desired:
        return True

    if "color_temp" in desired or "color_temp_kelvin" in desired:
        desired_k = None
        if isinstance(desired.get("color_temp_kelvin"), (int, float)):
            desired_k = int(round(desired["color_temp_kelvin"]))
        elif isinstance(desired.get("color_temp"), (int, float)) and desired["color_temp"] > 0:
            desired_k = int(round(1000000.0 / float(desired["color_temp"])))
        actual_k = _state_color_temp_kelvin(value)
        if desired_k is None or actual_k is None or not _value_close(
            actual_k,
            desired_k,
            RETRY_TOLERANCES.get("ct_kelvin", 25),
        ):
            return False

    hs = desired.get("hs_color")
    if isinstance(hs, (list, tuple)) and len(hs) >= 2:
        actual_hs = value.get("hs_color")
        if not (isinstance(actual_hs, (list, tuple)) and len(actual_hs) >= 2):
            return False
        if not _value_close(actual_hs[0], hs[0], RETRY_TOLERANCES.get("hs", 3.0)):
            return False
        if not _value_close(actual_hs[1], hs[1], RETRY_TOLERANCES.get("hs", 3.0)):
            return False

    rgb = desired.get("rgb_color")
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
        actual_rgb = _extract_rgb(value)
        if not actual_rgb or len(actual_rgb) != 3:
            return False
        if any(
            abs(int(actual_rgb[idx]) - int(rgb[idx])) > RETRY_TOLERANCES.get("rgb", 3) for idx in range(3)
        ):
            return False

    rgbw = desired.get("rgbw_color")
    if isinstance(rgbw, (list, tuple)) and len(rgbw) == 4:
        actual_rgbw = value.get("rgbw_color")
        if not (isinstance(actual_rgbw, (list, tuple)) and len(actual_rgbw) == 4):
            return False
        if any(
            abs(int(actual_rgbw[idx]) - int(rgbw[idx])) > RETRY_TOLERANCES.get("rgb", 3) for idx in range(4)
        ):
            return False

    rgbww = desired.get("rgbww_color")
    if isinstance(rgbww, (list, tuple)) and len(rgbww) == 5:
        actual_rgbww = value.get("rgbww_color")
        if not (isinstance(actual_rgbww, (list, tuple)) and len(actual_rgbww) == 5):
            return False
        if any(
            abs(int(actual_rgbww[idx]) - int(rgbww[idx])) > RETRY_TOLERANCES.get("rgb", 3) for idx in range(5)
        ):
            return False

    xy = desired.get("xy_color")
    if isinstance(xy, (list, tuple)) and len(xy) == 2:
        actual_xy = value.get("xy_color")
        if not (isinstance(actual_xy, (list, tuple)) and len(actual_xy) == 2):
            return False
        if not _value_close(actual_xy[0], xy[0], RETRY_TOLERANCES.get("xy", 0.01)):
            return False
        if not _value_close(actual_xy[1], xy[1], RETRY_TOLERANCES.get("xy", 0.01)):
            return False

    return True


def _command_satisfied(entry: dict, states: dict) -> bool:
    command = entry.get("command")
    targets = entry.get("targets") or []
    brightness = entry.get("brightness")
    color_payload = entry.get("color_payload") if isinstance(entry.get("color_payload"), dict) else {}
    effect = entry.get("effect")

    for target in targets:
        value = states.get(target)
        if not isinstance(value, dict):
            return False
        if _is_unavailable(value):
            return False
        state = str(value.get("state", "")).strip().lower()
        if command == "turn_on_inputs":
            if state != "on":
                return False
            continue
        if command == "turn_off_inputs":
            if state != "off":
                return False
            continue
        if state != "on":
            return False
        if command == "set_brightness_inputs":
            if not _value_close(
                value.get("brightness"),
                brightness,
                RETRY_TOLERANCES.get("brightness", 2),
            ):
                return False
            continue
        if command == "set_color_inputs":
            if brightness is not None and not _value_close(
                value.get("brightness"),
                brightness,
                RETRY_TOLERANCES.get("brightness", 2),
            ):
                return False
            if not _color_payload_matches(value, color_payload):
                return False
            continue
        if command == "set_effect_inputs":
            if isinstance(effect, str) and effect and value.get("effect") != effect:
                return False
            continue

    return True

def _normalize_wakeup_config(master: dict, controller: dict | None) -> dict:
    master_wakeup = master.get("wakeup") if isinstance(master, dict) else {}
    if not isinstance(master_wakeup, dict):
        master_wakeup = {}
    controller_wakeup = controller.get("wakeup") if isinstance(controller, dict) else {}
    if not isinstance(controller_wakeup, dict):
        controller_wakeup = {}

    use_master = controller_wakeup.get("use_master") is not False

    def _pick_value(key: str, default):
        if not use_master:
            value = controller_wakeup.get(key)
            if value is not None:
                return value
        value = master_wakeup.get(key)
        return value if value is not None else default

    def _to_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    duration_minutes = max(1, min(240, _to_int(_pick_value("duration_minutes", 30), 30)))
    start_brightness_pct = max(1, min(100, _to_int(_pick_value("start_brightness_pct", 1), 1)))

    return {
        "use_master": use_master,
        "duration_minutes": duration_minutes,
        "start_brightness_pct": start_brightness_pct,
    }

def _normalize_smoothing_config(master: dict) -> dict:
    smoothing = master.get("smoothing") if isinstance(master, dict) else {}
    if not isinstance(smoothing, dict):
        smoothing = {}
    try:
        brightness_rate = float(smoothing.get("brightness_rate_pct", 0.11))
    except (TypeError, ValueError):
        brightness_rate = 0.11
    try:
        ct_rate = float(smoothing.get("ct_rate_k", 2.67))
    except (TypeError, ValueError):
        ct_rate = 2.67
    return {
        "brightness_rate_pct": max(0.0, min(100.0, brightness_rate)),
        "ct_rate_k": max(0.0, ct_rate),
    }


def _compute_clarity(weather_values: dict, config: dict) -> tuple[float | None, bool]:
    uv = _parse_float(weather_values.get("uv_index"))
    cloud = _parse_float(weather_values.get("cloud_coverage"))
    visibility_km = weather_values.get("visibility_km")
    code = _parse_float(weather_values.get("weather_code"))

    precip = code is not None and code < 800

    weights = {
        "uv": max(0.0, float(config.get("uv_weight", 0.3))),
        "cloud": max(0.0, float(config.get("cloud_weight", 0.55))),
        "visibility": max(0.0, float(config.get("visibility_weight", 0.15))),
    }
    total = 0.0
    value = 0.0

    if uv is not None:
        uv_norm = max(0.0, min(1.0, uv / config["uv_max"]))
        value += uv_norm * weights["uv"]
        total += weights["uv"]

    if cloud is not None:
        cloud_norm = max(0.0, min(1.0, 1.0 - (cloud / 100.0)))
        value += cloud_norm * weights["cloud"]
        total += weights["cloud"]

    if visibility_km is not None:
        vis_norm = max(0.0, min(1.0, visibility_km / config["visibility_max_km"]))
        value += vis_norm * weights["visibility"]
        total += weights["visibility"]

    if total == 0:
        return None, precip

    return value / total, precip


def _apply_weather_ct_with_reduction(
    color_temp: int | None, limits: dict, weather: dict
) -> tuple[int | None, float | None]:
    if color_temp is None:
        return None, None

    weather_min = limits.get("weather_min_kelvin")
    if not isinstance(weather_min, int):
        weather_min = limits.get("ct_min_kelvin")
    if not isinstance(weather_min, int):
        return color_temp, None

    weather_min = max(limits.get("ct_min_kelvin", weather_min), min(limits.get("ct_max_kelvin", weather_min), weather_min))
    span = color_temp - weather_min
    if span <= 0:
        return color_temp, 0.0

    if weather.get("precip"):
        return weather_min, 100.0

    clarity = weather.get("clarity")
    if clarity is None:
        return color_temp, 0.0

    cloudiness = max(0.0, min(1.0, 1.0 - clarity))
    reduction_pct = cloudiness * weather.get("max_reduction_pct", 0.0)
    if reduction_pct <= 0:
        return color_temp, 0.0
    adjusted = color_temp - (span * reduction_pct / 100.0)
    adjusted = max(weather_min, min(color_temp, adjusted))
    actual_reduction = max(0.0, min(100.0, ((color_temp - adjusted) / span) * 100.0))
    return int(round(adjusted)), actual_reduction


def _sun_day_fraction(now: datetime, sun_attrs: dict | None) -> float:
    if sun_attrs:
        next_rising = _parse_iso(sun_attrs.get("next_rising"))
        if next_rising:
            if next_rising > now:
                last_rising = next_rising - timedelta(days=1)
            else:
                last_rising = next_rising
            span = (next_rising - last_rising).total_seconds()
            if span > 0:
                elapsed = (now - last_rising).total_seconds()
                return max(0.0, min(1.0, elapsed / span))

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - midnight).total_seconds() / 86400.0


def _today_sun_times(now: datetime, sun_attrs: dict | None) -> tuple[float | None, float | None]:
    if not sun_attrs:
        return None, None
    next_rising = _parse_iso(sun_attrs.get("next_rising"))
    next_setting = _parse_iso(sun_attrs.get("next_setting"))
    if not next_rising or not next_setting:
        return None, None

    sunrise = next_rising if next_rising.date() == now.date() else next_rising - timedelta(days=1)
    sunset = next_setting if next_setting.date() == now.date() else next_setting - timedelta(days=1)
    return (
        sunrise.hour * 60 + sunrise.minute + sunrise.second / 60.0,
        sunset.hour * 60 + sunset.minute + sunset.second / 60.0,
    )


def _dst_offset_minutes(now: datetime, tz: ZoneInfo) -> int:
    base_offset = datetime(now.year, 1, 15, 12, tzinfo=tz).utcoffset() or timedelta(0)
    today_offset = datetime(now.year, now.month, now.day, 12, tzinfo=tz).utcoffset() or timedelta(0)
    return int((today_offset - base_offset).total_seconds() // 60)


def _normalize_signed_delta(value: float, center: float) -> float:
    delta = value - center
    if delta > 720:
        delta -= 1440
    elif delta < -720:
        delta += 1440
    return delta


def _smoothstep(value: float) -> float:
    t = max(0.0, min(1.0, value))
    return t * t * (3 - 2 * t)


def _mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _unscale_time(actual_t: float, base_sunrise: float, base_sunset: float, sunrise: float, sunset: float) -> float:
    if not all(isinstance(val, (int, float)) for val in (base_sunrise, base_sunset, sunrise, sunset)):
        return actual_t

    day_base = base_sunset - base_sunrise
    day_actual = sunset - sunrise
    night_base = 1440 - day_base
    night_actual = 1440 - day_actual
    base_noon = 720
    actual_noon = 720
    base_midnight = 0
    actual_midnight = 0
    transition = 60
    warp_strength = 1

    t = actual_t % 1440

    def day_map() -> float:
        if day_actual <= 0 or day_base <= 0:
            return t
        delta = t - actual_noon
        return base_noon + (delta * day_base) / day_actual

    def night_map() -> float:
        if night_actual <= 0 or night_base <= 0:
            return t
        night_delta = _normalize_signed_delta(t, actual_midnight)
        return (base_midnight + (night_delta * night_base) / night_actual + 1440) % 1440

    sunrise_blend = sunrise - transition <= t <= sunrise + transition
    sunset_blend = sunset - transition <= t <= sunset + transition

    if sunrise_blend:
        alpha = _smoothstep((t - (sunrise - transition)) / (2 * transition))
        return _mix(night_map(), day_map(), alpha)
    if sunset_blend:
        alpha = _smoothstep((t - (sunset - transition)) / (2 * transition))
        return _mix(day_map(), night_map(), alpha)

    mapped = day_map() if sunrise <= t < sunset else night_map()
    return _mix(t, mapped, warp_strength)


def _evaluate_solar_curve(
    points: list[dict],
    t_minutes: float,
    base_sunrise: float,
    base_sunset: float,
    sunrise: float,
    sunset: float,
    dst_offset: int,
) -> float | None:
    if not all(isinstance(val, (int, float)) for val in (base_sunrise, base_sunset, sunrise, sunset)):
        return _evaluate_curve(points, t_minutes)
    shifted = (t_minutes - dst_offset + 1440) % 1440
    base_t = _unscale_time(shifted, base_sunrise, base_sunset, sunrise, sunset)
    return _evaluate_curve(points, base_t)


def _monotone_hermite(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
    span: float,
) -> float:
    d0 = (p2[1] - p0[1]) / (p2[0] - p0[0] or 1)
    d1 = (p3[1] - p1[1]) / (p3[0] - p1[0] or 1)
    m1 = d0
    m2 = d1
    delta = (p2[1] - p1[1]) / (p2[0] - p1[0] or 1)

    if abs(delta) < 1e-6:
        m1 = 0.0
        m2 = 0.0
    else:
        if m1 / delta < 0:
            m1 = 0.0
        if m2 / delta < 0:
            m2 = 0.0
        limit = 3.0 * abs(delta)
        if abs(m1) > limit:
            m1 = math.copysign(limit, m1)
        if abs(m2) > limit:
            m2 = math.copysign(limit, m2)

    t2 = t * t
    t3 = t2 * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return h00 * p1[1] + h10 * m1 * span + h01 * p2[1] + h11 * m2 * span


def _prepare_curve(points: list[dict]) -> list[tuple[float, float]]:
    cleaned = []
    for point in points:
        if not isinstance(point, dict):
            continue
        t = point.get("t")
        v = point.get("v")
        if not isinstance(t, (int, float)) or not isinstance(v, (int, float)):
            continue
        cleaned.append((max(0.0, min(1440.0, float(t))), float(v)))

    cleaned.sort(key=lambda item: item[0])
    return cleaned


def _evaluate_curve(points: list[dict], t_minutes: float) -> float | None:
    curve = _prepare_curve(points)
    if len(curve) < 2:
        return None

    t = t_minutes % 1440.0
    extended = [(t_val - 1440.0, v) for t_val, v in curve] + curve + [(t_val + 1440.0, v) for t_val, v in curve]
    start = len(curve)
    end = len(curve) * 2

    idx = start
    while idx < end - 1 and t > extended[idx + 1][0]:
        idx += 1

    p0 = extended[max(idx - 1, 0)]
    p1 = extended[idx]
    p2 = extended[idx + 1]
    p3 = extended[min(idx + 2, len(extended) - 1)]

    span = p2[0] - p1[0]
    if span <= 0:
        return p1[1]

    local_t = (t - p1[0]) / span
    return _monotone_hermite(p0, p1, p2, p3, local_t, span)
def _state_from_inputs(states: dict) -> tuple[str, int | None]:
    on_brightness = []
    for value in states.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() != "on":
            continue
        brightness = value.get("brightness")
        if isinstance(brightness, int):
            on_brightness.append(brightness)

    if not on_brightness:
        return "off", None

    median_value = int(statistics.median(on_brightness))
    return "on", median_value


def _union_color_modes(states: dict) -> list[str]:
    modes: set[str] = set()
    for value in states.values():
        if not isinstance(value, dict):
            continue
        supported = value.get("supported_color_modes")
        if isinstance(supported, list):
            for mode in supported:
                if isinstance(mode, str):
                    modes.add(mode)
    return sorted(modes)


def _union_mireds(states: dict) -> tuple[int | None, int | None]:
    mins = []
    maxs = []
    for value in states.values():
        if not isinstance(value, dict):
            continue
        min_mireds = value.get("min_mireds")
        max_mireds = value.get("max_mireds")
        if isinstance(min_mireds, int):
            mins.append(min_mireds)
        if isinstance(max_mireds, int):
            maxs.append(max_mireds)

    min_out = min(mins) if mins else None
    max_out = max(maxs) if maxs else None
    return min_out, max_out


def _union_effect_list(states: dict) -> list[str]:
    effects: set[str] = set()
    for value in states.values():
        if not isinstance(value, dict):
            continue
        effect_list = value.get("effect_list")
        if isinstance(effect_list, list):
            for effect in effect_list:
                if isinstance(effect, str) and effect:
                    effects.add(effect)
    return sorted(effects)


def _most_common_effect(states: dict) -> str | None:
    effects = []
    for value in states.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() != "on":
            continue
        effect = value.get("effect")
        if isinstance(effect, str) and effect:
            effects.append(effect)

    if not effects:
        return None

    counter = Counter(effects)
    return counter.most_common(1)[0][0]


def _ct_to_rgb_kelvin(kelvin: float) -> tuple[int, int, int]:
    """Approximate RGB from color temperature (Kelvin)."""
    temp = max(1000.0, min(40000.0, kelvin)) / 100.0

    if temp <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temp) - 161.1195681661
        if temp <= 19.0:
            blue = 0.0
        else:
            blue = 138.5177312231 * math.log(temp - 10.0) - 305.0447927307
    else:
        red = 329.698727446 * ((temp - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temp - 60.0) ** -0.0755148492)
        blue = 255.0

    red = max(0, min(255, int(round(red))))
    green = max(0, min(255, int(round(green))))
    blue = max(0, min(255, int(round(blue))))
    return red, green, blue


def _ct_to_rgb_from_inputs(value: dict) -> tuple[int, int, int] | None:
    ct_kelvin = value.get("color_temp_kelvin")
    if isinstance(ct_kelvin, (int, float)):
        return _ct_to_rgb_kelvin(float(ct_kelvin))

    ct_mireds = value.get("color_temp")
    if isinstance(ct_mireds, (int, float)) and ct_mireds > 0:
        return _ct_to_rgb_kelvin(1000000.0 / float(ct_mireds))

    return None


def _median_color_from_inputs(states: dict) -> dict:
    hs_hues = []
    hs_sats = []
    rgb_r = []
    rgb_g = []
    rgb_b = []
    rgbw_r = []
    rgbw_g = []
    rgbw_b = []
    rgbw_w = []
    rgbww_r = []
    rgbww_g = []
    rgbww_b = []
    rgbww_cw = []
    rgbww_ww = []
    xy_x = []
    xy_y = []
    ct_mireds = []
    ct_kelvin = []

    color_group = {"hs", "rgb", "rgbw", "rgbww", "xy"}
    has_color_input = False
    has_color_temp_mode = False

    for value in states.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() != "on":
            continue
        mode = value.get("color_mode")
        if isinstance(mode, str) and mode in color_group:
            has_color_input = True
        if isinstance(mode, str) and mode == "color_temp":
            has_color_temp_mode = True

    for value in states.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() != "on":
            continue

        mode = value.get("color_mode") if isinstance(value.get("color_mode"), str) else None

        if mode in color_group:
            hs = value.get("hs_color")
            if isinstance(hs, (list, tuple)) and len(hs) == 2:
                hs_hues.append(hs[0])
                hs_sats.append(hs[1])

            rgb = value.get("rgb_color")
            if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
                rgb_r.append(rgb[0])
                rgb_g.append(rgb[1])
                rgb_b.append(rgb[2])

            rgbw = value.get("rgbw_color")
            if isinstance(rgbw, (list, tuple)) and len(rgbw) == 4:
                rgbw_r.append(rgbw[0])
                rgbw_g.append(rgbw[1])
                rgbw_b.append(rgbw[2])
                rgbw_w.append(rgbw[3])
                rgb_r.append(rgbw[0])
                rgb_g.append(rgbw[1])
                rgb_b.append(rgbw[2])

            rgbww = value.get("rgbww_color")
            if isinstance(rgbww, (list, tuple)) and len(rgbww) == 5:
                rgbww_r.append(rgbww[0])
                rgbww_g.append(rgbww[1])
                rgbww_b.append(rgbww[2])
                rgbww_cw.append(rgbww[3])
                rgbww_ww.append(rgbww[4])
                rgb_r.append(rgbww[0])
                rgb_g.append(rgbww[1])
                rgb_b.append(rgbww[2])

            xy = value.get("xy_color")
            if isinstance(xy, (list, tuple)) and len(xy) == 2:
                xy_x.append(xy[0])
                xy_y.append(xy[1])

        if mode == "color_temp":
            ct = value.get("color_temp")
            if isinstance(ct, (int, float)):
                ct_mireds.append(ct)

            ct_k = value.get("color_temp_kelvin")
            if isinstance(ct_k, (int, float)):
                ct_kelvin.append(ct_k)

            if has_color_input:
                ct_rgb = _ct_to_rgb_from_inputs(value)
                if ct_rgb is not None:
                    rgb_r.append(ct_rgb[0])
                    rgb_g.append(ct_rgb[1])
                    rgb_b.append(ct_rgb[2])
                    rgbw_r.append(ct_rgb[0])
                    rgbw_g.append(ct_rgb[1])
                    rgbw_b.append(ct_rgb[2])
                    rgbw_w.append(0)
                    rgbww_r.append(ct_rgb[0])
                    rgbww_g.append(ct_rgb[1])
                    rgbww_b.append(ct_rgb[2])
                    rgbww_cw.append(0)
                    rgbww_ww.append(0)

    payload: dict = {}
    if hs_hues and hs_sats:
        payload["hs_color"] = [statistics.median(hs_hues), statistics.median(hs_sats)]
    if rgb_r and rgb_g and rgb_b:
        payload["rgb_color"] = [
            int(statistics.median(rgb_r)),
            int(statistics.median(rgb_g)),
            int(statistics.median(rgb_b)),
        ]
    if rgbw_r and rgbw_g and rgbw_b and rgbw_w:
        payload["rgbw_color"] = [
            int(statistics.median(rgbw_r)),
            int(statistics.median(rgbw_g)),
            int(statistics.median(rgbw_b)),
            int(statistics.median(rgbw_w)),
        ]
    if rgbww_r and rgbww_g and rgbww_b and rgbww_cw and rgbww_ww:
        payload["rgbww_color"] = [
            int(statistics.median(rgbww_r)),
            int(statistics.median(rgbww_g)),
            int(statistics.median(rgbww_b)),
            int(statistics.median(rgbww_cw)),
            int(statistics.median(rgbww_ww)),
        ]
    if xy_x and xy_y:
        payload["xy_color"] = [statistics.median(xy_x), statistics.median(xy_y)]
    if ct_mireds:
        payload["color_temp"] = int(statistics.median(ct_mireds))
    if ct_kelvin:
        payload["color_temp_kelvin"] = int(statistics.median(ct_kelvin))

    if has_color_temp_mode and ("color_temp" in payload or "color_temp_kelvin" in payload):
        payload["__prefer_color_temp"] = True

    return payload

def _targets_all(states: dict) -> list[str]:
    return [entity_id for entity_id in states.keys()]


def _targets_on(states: dict) -> list[str]:
    targets = []
    for entity_id, value in states.items():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() == "on":
            targets.append(entity_id)
    return targets


def _targets_with_mode(states: dict, color_mode: str | None, only_on: bool) -> list[str]:
    if not color_mode:
        return _targets_on(states) if only_on else _targets_all(states)

    normalized = "color_temp" if color_mode == "color_temp_kelvin" else color_mode
    color_group = {"hs", "rgb", "rgbw", "rgbww", "xy"}

    targets = []
    for entity_id, value in states.items():
        if not isinstance(value, dict):
            continue
        if only_on and str(value.get("state", "")).strip().lower() != "on":
            continue
        supported = value.get("supported_color_modes")
        if supported is None:
            targets.append(entity_id)
            continue
        if not isinstance(supported, list):
            continue

        if normalized == "color_temp":
            if "color_temp" in supported:
                targets.append(entity_id)
            continue

        if normalized in color_group:
            if any(mode in supported for mode in color_group):
                targets.append(entity_id)
            continue

        if normalized in supported:
            targets.append(entity_id)

    return targets


def _warmest_kelvin_from_states(states: dict, limits: dict) -> int:
    candidates = []
    for value in states.values():
        if not isinstance(value, dict):
            continue
        max_mireds = value.get("max_mireds")
        if isinstance(max_mireds, (int, float)) and max_mireds > 0:
            candidates.append(int(1000000 / max_mireds))

    warmest = min(candidates) if candidates else int(limits.get("ct_min_kelvin", 2000))
    min_k = int(limits.get("ct_min_kelvin", 2000))
    max_k = int(limits.get("ct_max_kelvin", 6500))
    if min_k > max_k:
        min_k, max_k = max_k, min_k
    return int(max(min_k, min(max_k, warmest)))


def _publish_input_command(
    client,
    controller_id: str,
    command: str,
    targets: list[str],
    brightness: int | None = None,
    color_payload: dict | None = None,
    effect: str | None = None,
    track: bool = True,
) -> None:
    if not targets:
        return

    output_topic = f"svtlc/{controller_id}/command"
    payload = {"command": command, "targets": targets}
    if brightness is not None:
        payload["brightness"] = brightness
    if color_payload:
        payload.update(color_payload)
    if effect is not None:
        payload["effect"] = effect
    client.publish(output_topic, json.dumps(payload), qos=0, retain=False)
    if track:
        # Cancel any pending retries for this controller when a new command is issued.
        for key, entry in list(RETRY_PENDING.items()):
            if entry.get("controller_id") == controller_id:
                RETRY_PENDING.pop(key, None)
        _queue_retry_entry(controller_id, command, targets, brightness, color_payload, effect)


def _publish_light_command(
    client,
    controller_id: str,
    states: dict,
    brightness: int | None,
    color_payload: dict | None,
    only_on: bool,
) -> None:
    if color_payload:
        color_mode = None
        if isinstance(color_payload.get("color_mode"), str):
            color_mode = color_payload["color_mode"]
        color_targets = _targets_with_mode(states, color_mode, only_on=only_on)
        if not color_targets:
            return
        _publish_input_command(
            client,
            controller_id,
            "set_color_inputs",
            color_targets,
            brightness,
            color_payload=color_payload,
        )
        return

    targets = _targets_on(states) if only_on else _targets_all(states)
    if targets and brightness is not None:
        _publish_input_command(client, controller_id, "set_brightness_inputs", targets, brightness)


def _select_color_mode(modes: list[str], color_payload: dict) -> str | None:
    if color_payload.get("__prefer_color_temp") and (
        "color_temp" in color_payload or "color_temp_kelvin" in color_payload
    ):
        return "color_temp"
    has_color = any(key in color_payload for key in ("rgb_color", "rgbw_color", "rgbww_color", "hs_color", "xy_color"))
    if has_color:
        if "rgbww" in modes and "rgbww_color" in color_payload:
            return "rgbww"
        if "rgbw" in modes:
            return "rgbw"
        if "rgb" in modes:
            return "rgb"
        if "hs" in modes:
            return "hs"
        if "xy" in modes:
            return "xy"

    if "color_temp" in color_payload or "color_temp_kelvin" in color_payload:
        return "color_temp" if "color_temp" in modes else "color_temp"

    return None


def _publish_output_state(
    client,
    controller_id: str,
    state: str,
    brightness: int | None,
    modes,
    min_mireds,
    max_mireds,
    color_payload: dict,
    effect_list: list[str],
    effect: str | None,
) -> dict:
    output_topic = f"svtlc/{controller_id}/output"
    payload = {"state": state}
    if brightness is not None:
        payload["brightness"] = brightness
    if modes:
        payload["supported_color_modes"] = modes
    if isinstance(min_mireds, int):
        payload["min_mireds"] = min_mireds
    if isinstance(max_mireds, int):
        payload["max_mireds"] = max_mireds
    if effect_list:
        payload["effect_list"] = effect_list
    if effect is not None:
        payload["effect"] = effect
    color_payload.pop("__prefer_color_temp", None)
    payload.update(color_payload)

    if "rgb_color" in payload and isinstance(payload["rgb_color"], list) and len(payload["rgb_color"]) == 3:
        r, g, b = payload["rgb_color"]
        if "rgbw" in (modes or []) and "rgbw_color" not in payload:
            payload["rgbw_color"] = [r, g, b, 0]
        if "rgbww" in (modes or []) and "rgbww_color" not in payload:
            payload["rgbww_color"] = [r, g, b, 0, 0]

    color_mode = _select_color_mode(modes or [], payload)
    if color_mode:
        payload["color_mode"] = color_mode
        if color_mode != "color_temp":
            payload.pop("color_temp", None)
            payload.pop("color_temp_kelvin", None)

    client.publish(output_topic, json.dumps(payload), qos=0, retain=True)
    return payload


def _extract_color_payload(payload: dict) -> tuple[str | None, dict]:
    color_payload = {}
    color_mode = payload.get("color_mode")
    if isinstance(color_mode, str):
        color_payload["color_mode"] = color_mode

    for key in (
        "hs_color",
        "rgb_color",
        "rgbw_color",
        "rgbww_color",
        "xy_color",
        "color_temp",
        "color_temp_kelvin",
    ):
        value = payload.get(key)
        if value is not None:
            color_payload[key] = value

    return color_mode if isinstance(color_mode, str) else None, color_payload


def _payload_equals(a: dict | None, b: dict | None) -> bool:
    if a is None or b is None:
        return False
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main() -> None:
    options = _load_options()

    log_level = options.get("log_level", "info").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
    logger = logging.getLogger("svtlc")

    host = options.get("mqtt_host", "core-mosquitto")
    port = int(options.get("mqtt_port", 1883))
    username = options.get("mqtt_username") or None
    password = options.get("mqtt_password") or None
    circadian_interval = max(1, int(options.get("circadian_interval", 60)))
    try:
        wakeup_interval = max(1, int(options.get("wakeup_interval", 2)))
    except (TypeError, ValueError):
        wakeup_interval = 2

    last_output: dict[str, dict] = {}
    last_inputs: dict[str, dict] = {}
    last_circadian: dict[str, dict] = {}
    last_circadian_settings: dict[str, dict] = {}
    last_circadian_state: dict[str, dict] = {}
    last_limits_state: dict[str, dict] = {}
    last_mode_state: dict[str, dict] = {}
    last_smoothed: dict[str, dict] = {}
    last_smooth_time: dict[str, float] = {}
    last_away_state: dict[str, dict] = {}
    away_state: dict[str, dict] = {}
    away_window_cache: dict[str, dict] = {}
    away_refresh: dict[str, float] = {}
    last_weather_debug: dict[str, dict] = {}
    last_sleep_state: dict[str, dict] = {}
    wakeup_state: dict[str, dict] = {}
    config_cache = {"mtime": None, "controllers": [], "master": {}, "controller_ids": set()}
    sun_cache = {"fetched": 0.0, "attrs": None}
    ha_config_cache = {"fetched": 0.0, "config": None}
    weather_cache = {"fetched": 0.0, "values": {}}
    runtime_cache = _read_runtime_payload()
    pending_retained_clear: set[str] = set()
    for controller_id, mode in runtime_cache.get("modes", {}).items():
        if isinstance(controller_id, str):
            last_mode_state[controller_id] = {"mode": _normalize_mode(mode)}


    def _clear_retained_topics(controller_id: str) -> None:
        topics = (
            f"svtlc/{controller_id}/inputs",
            f"svtlc/{controller_id}/inputs/status",
            f"svtlc/{controller_id}/output",
            f"svtlc/{controller_id}/mode",
            f"svtlc/{controller_id}/limits",
            f"svtlc/{controller_id}/circadian",
            f"svtlc/{controller_id}/away",
        )
        for topic in topics:
            client.publish(topic, payload=b"", qos=0, retain=True)

    def _flush_retained_clears() -> None:
        if not pending_retained_clear:
            return
        if not client or not client.is_connected():
            return
        for controller_id in list(pending_retained_clear):
            _clear_retained_topics(controller_id)
            pending_retained_clear.discard(controller_id)

    def _load_controller_cache() -> tuple[list[dict], dict]:
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except FileNotFoundError:
            mtime = None

        if mtime != config_cache.get("mtime"):
            config_cache["mtime"] = mtime
            payload = _load_controllers_config()
            config_cache["controllers"] = payload.get("controllers", [])
            config_cache["master"] = payload.get("master", {})
            new_ids = {
                _normalize_controller_id((controller.get("unique_id") or controller.get("name") or "").strip())
                for controller in config_cache["controllers"]
                if isinstance(controller, dict)
            }
            prev_ids = config_cache.get("controller_ids", set()) or set()
            removed = prev_ids - new_ids
            for controller_id in removed:
                pending_retained_clear.add(controller_id)
            config_cache["controller_ids"] = new_ids

        return config_cache.get("controllers", []), config_cache.get("master", {})

    def _request_startup_cleanup() -> None:
        pending_retained_clear.clear()

    def _get_sun_attrs() -> dict | None:
        now_ts = time.time()
        if now_ts - sun_cache.get("fetched", 0.0) > 300:
            sun_cache["attrs"] = _fetch_sun_times()
            sun_cache["fetched"] = now_ts
        return sun_cache.get("attrs")

    def _get_time_zone() -> ZoneInfo:
        now_ts = time.time()
        if now_ts - ha_config_cache.get("fetched", 0.0) > 300:
            ha_config_cache["config"] = _fetch_ha_config()
            ha_config_cache["fetched"] = now_ts
        config = ha_config_cache.get("config") or {}
        tz_name = config.get("time_zone") or "UTC"
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("UTC")

    def _get_weather_values(config: dict) -> dict:
        now_ts = time.time()
        if now_ts - weather_cache.get("fetched", 0.0) < 60 and weather_cache.get("values"):
            return weather_cache.get("values", {})

        values: dict = {}
        cloud_state = _fetch_entity_state(config.get("cloud_sensor"))
        uv_state = _fetch_entity_state(config.get("uv_sensor"))
        visibility_state = _fetch_entity_state(config.get("visibility_sensor"))
        code_state = _fetch_entity_state(config.get("weather_code_sensor"))

        values["cloud_coverage"] = _parse_float(cloud_state.get("state")) if cloud_state else None
        values["uv_index"] = _parse_float(uv_state.get("state")) if uv_state else None
        values["visibility_km"] = _parse_visibility_km(visibility_state)
        values["weather_code"] = _parse_float(code_state.get("state")) if code_state else None

        weather_cache["fetched"] = now_ts
        weather_cache["values"] = values
        return values

    def _process_retries() -> None:
        if not RETRY_CONFIG.get("enabled"):
            if RETRY_PENDING:
                RETRY_PENDING.clear()
            return

        now_ts = time.time()
        for key, entry in list(RETRY_PENDING.items()):
            next_ts = float(entry.get("next_ts", 0))
            if now_ts < next_ts:
                continue
            controller_id = entry.get("controller_id")
            if not isinstance(controller_id, str):
                RETRY_PENDING.pop(key, None)
                continue
            states = last_inputs.get(controller_id, {})
            if _command_satisfied(entry, states):
                RETRY_PENDING.pop(key, None)
                continue
            attempts = int(entry.get("attempts", 0))
            max_retries = int(RETRY_CONFIG.get("max_retries", 3))
            if attempts >= max_retries:
                logger.warning("Retry exhausted for %s/%s", controller_id, entry.get("command"))
                RETRY_PENDING.pop(key, None)
                continue
            entry["attempts"] = attempts + 1
            entry["next_ts"] = now_ts + float(RETRY_CONFIG.get("delay_seconds", 2))
            RETRY_PENDING[key] = entry
            _publish_input_command(
                client,
                controller_id,
                entry.get("command"),
                entry.get("targets", []),
                entry.get("brightness"),
                color_payload=entry.get("color_payload"),
                effect=entry.get("effect"),
                track=False,
            )

    def _get_away_window(now: datetime, cfg: dict) -> tuple[int, int, str]:
        key = now.date().isoformat()
        cache = away_window_cache.get("window")
        if cache and cache.get("date") == key and cache.get("cfg") == cfg:
            return cache["start"], cache["end"], cache["key"]

        offset = cfg.get("offset_minutes", 0)
        start_offset = random.randint(-offset, offset) if offset else 0
        end_offset = random.randint(-offset, offset) if offset else 0
        start = (cfg["start_minutes"] + start_offset) % 1440
        end = (cfg["end_minutes"] + end_offset) % 1440
        window_key = f"{key}:{start}:{end}"
        away_window_cache["window"] = {
            "date": key,
            "start": start,
            "end": end,
            "key": window_key,
            "cfg": dict(cfg),
        }
        return start, end, window_key

    def _window_end_ts(now: datetime, start: int, end: int) -> float:
        now_minutes = now.hour * 60 + now.minute + (now.second / 60.0)
        if start <= end:
            end_date = now.date()
            if now_minutes > end:
                end_date = (now + timedelta(days=1)).date()
        else:
            end_date = now.date() if now_minutes <= end else (now + timedelta(days=1)).date()
        end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=now.tzinfo) + timedelta(minutes=end)
        return end_dt.timestamp()

    def _is_in_window(now_minutes: float, start: int, end: int) -> bool:
        if start <= end:
            return start <= now_minutes <= end
        return now_minutes >= start or now_minutes <= end

    def _random_duration_seconds(cfg: dict) -> float:
        minutes = random.randint(cfg["min_minutes"], cfg["max_minutes"])
        return float(minutes * 60)

    def _handle_away_mode(
        controller_id: str,
        states: dict,
        master_cfg: dict,
        smooth_brightness: int | None,
        smooth_ct: int | None,
        brightness_enabled: bool,
        color_temp_enabled: bool,
        refresh_seconds: int,
    ) -> None:
        cfg = _normalize_away_config(master_cfg)
        now = datetime.now().astimezone()
        now_minutes = now.hour * 60 + now.minute + (now.second / 60.0)
        now_ts = time.time()
        start, end, window_key = _get_away_window(now, cfg)

        in_window = _is_in_window(now_minutes, start, end)
        if not in_window:
            away_state.pop(controller_id, None)
            targets = _targets_all(states)
            if targets:
                _publish_input_command(client, controller_id, "turn_off_inputs", targets)
            away_payload = {
                "active": True,
                "on": False,
                "next_ts": None,
                "next_iso": None,
                "window_start": start,
                "window_end": end,
                "now_minutes": now_minutes,
                "in_window": False,
            }
            if last_away_state.get(controller_id) != away_payload:
                last_away_state[controller_id] = away_payload
                _publish_away_state(client, controller_id, away_payload)
            return

        current = away_state.get(controller_id)
        if not current or current.get("window_key") != window_key:
            current_on = bool(random.getrandbits(1))
            next_ts = now_ts + _random_duration_seconds(cfg)
            away_state[controller_id] = {"on": current_on, "next_ts": next_ts, "window_key": window_key}
            state_changed = True
        elif now_ts >= float(current.get("next_ts", 0)):
            current_on = not bool(current.get("on"))
            next_ts = now_ts + _random_duration_seconds(cfg)
            away_state[controller_id] = {"on": current_on, "next_ts": next_ts, "window_key": window_key}
            state_changed = True
        else:
            current_on = bool(current.get("on"))
            state_changed = False

        targets = _targets_all(states)

        if current_on and state_changed and targets:
            brightness = smooth_brightness if brightness_enabled else None
            color_payload = (
                {"color_temp_kelvin": smooth_ct, "color_mode": "color_temp"}
                if color_temp_enabled and isinstance(smooth_ct, int)
                else None
            )
            if brightness is None and color_payload is None:
                _publish_input_command(client, controller_id, "turn_on_inputs", targets)
        elif not current_on and state_changed and targets:
            _publish_input_command(client, controller_id, "turn_off_inputs", targets)
        if current_on and targets:
            brightness = smooth_brightness if brightness_enabled else None
            color_payload = (
                {"color_temp_kelvin": smooth_ct, "color_mode": "color_temp"}
                if color_temp_enabled and isinstance(smooth_ct, int)
                else None
            )
            if brightness is not None or color_payload:
                last = last_circadian.get(controller_id, {})
                last_ts = away_refresh.get(controller_id, 0.0)
                refresh_due = (now_ts - float(last_ts)) >= float(refresh_seconds)
                if refresh_due or last.get("brightness") != brightness or last.get("color_temp") != smooth_ct:
                    _publish_light_command(
                        client,
                        controller_id,
                        states,
                        brightness,
                        color_payload,
                        only_on=False,
                    )
                    last_circadian[controller_id] = {"brightness": brightness, "color_temp": smooth_ct}
                    away_refresh[controller_id] = now_ts

        away_payload = {
            "active": True,
            "on": bool(current_on),
            "next_ts": int(round(away_state[controller_id]["next_ts"])),
            "next_iso": datetime.fromtimestamp(away_state[controller_id]["next_ts"], tz=now.tzinfo).isoformat(),
            "window_start": start,
            "window_end": end,
            "now_minutes": now_minutes,
            "in_window": True,
        }
        end_ts = _window_end_ts(now, start, end)
        next_ts = away_state[controller_id]["next_ts"]
        if end_ts <= next_ts:
            action_ts = end_ts
            action_type = "window_end"
        else:
            action_ts = next_ts
            action_type = "toggle"
        away_payload["next_action_ts"] = int(round(action_ts))
        away_payload["next_action_iso"] = datetime.fromtimestamp(action_ts, tz=now.tzinfo).isoformat()
        away_payload["next_action_type"] = action_type
        if last_away_state.get(controller_id) != away_payload:
            last_away_state[controller_id] = away_payload
            _publish_away_state(client, controller_id, away_payload)

    def _apply_sleep_targets(
        controller_id: str,
        controller_cfg: dict,
        master_cfg: dict,
        states: dict,
        only_on: bool = True,
    ) -> None:
        sleep_cfg = _normalize_sleep_config(master_cfg, controller_cfg)
        limits = _normalize_limits(controller_cfg.get("limits") if isinstance(controller_cfg, dict) else None)
        brightness = int(round(255.0 * (sleep_cfg["brightness_pct"] / 100.0)))
        brightness = _scale_brightness(brightness, limits)
        color_temp = _scale_color_temp(sleep_cfg["color_temp_kelvin"], [], limits)
        hs_color = sleep_cfg["hs_color"]

        targets = _targets_on(states) if only_on else _targets_all(states)
        if not targets:
            return

        color_targets = _targets_with_mode(states, "hs", only_on=only_on)
        ct_targets = _targets_with_mode(states, "color_temp", only_on=only_on)
        if color_targets and ct_targets:
            ct_targets = [target for target in ct_targets if target not in color_targets]

        if color_targets:
            _publish_input_command(
                client,
                controller_id,
                "set_color_inputs",
                color_targets,
                brightness,
                color_payload={"hs_color": hs_color, "color_mode": "hs"},
            )

        if ct_targets and color_temp is not None:
            _publish_input_command(
                client,
                controller_id,
                "set_color_inputs",
                ct_targets,
                brightness,
                color_payload={"color_temp_kelvin": color_temp, "color_mode": "color_temp"},
            )
            return

        if not color_targets and brightness is not None:
            _publish_input_command(
                client,
                controller_id,
                "set_brightness_inputs",
                targets,
                brightness,
            )

    def _handle_sleep_mode(
        controller_id: str,
        controller_cfg: dict,
        master_cfg: dict,
        states: dict,
        output_state: str | None,
    ) -> None:
        if output_state != "on":
            last_sleep_state[controller_id] = {"mode": "Sleep", "pending": True, "last_output": "off"}
            return

        sleep_state = last_sleep_state.get(controller_id) or {}
        pending = True
        if sleep_state.get("mode") == "Sleep":
            pending = bool(sleep_state.get("pending", True) or sleep_state.get("last_output") != "on")

        if not pending:
            return

        _apply_sleep_targets(controller_id, controller_cfg, master_cfg, states)
        last_sleep_state[controller_id] = {"mode": "Sleep", "pending": False, "last_output": "on"}

    def _handle_wakeup_mode(
        controller_id: str,
        controller_cfg: dict,
        master_cfg: dict,
        states: dict,
        output_state: str | None,
        target_brightness: int | None,
        target_ct: int | None,
    ) -> None:
        wakeup_cfg = _normalize_wakeup_config(master_cfg, controller_cfg)
        limits = _normalize_limits(controller_cfg.get("limits") if isinstance(controller_cfg, dict) else None)
        start_brightness = int(round(255.0 * (wakeup_cfg["start_brightness_pct"] / 100.0)))
        start_brightness = _scale_brightness(start_brightness, limits)
        start_ct = _warmest_kelvin_from_states(states, limits)

        now_ts = time.time()
        current = wakeup_state.get(controller_id)
        if (
            not current
            or current.get("duration_minutes") != wakeup_cfg["duration_minutes"]
            or current.get("start_brightness") != start_brightness
            or current.get("start_ct") != start_ct
        ):
            prev_mode = current.get("prev_mode") if isinstance(current, dict) else None
            if not isinstance(prev_mode, str) or not prev_mode:
                prev_mode = "Circadian"
            current = {
                "start_ts": now_ts,
                "duration_minutes": wakeup_cfg["duration_minutes"],
                "start_brightness": start_brightness,
                "start_ct": start_ct,
                "applied_start": False,
                "last_output": None,
                "had_on": False,
                "prev_mode": prev_mode,
            }
            wakeup_state[controller_id] = current

        if output_state != "on":
            if current.get("had_on"):
                prev_mode = current.get("prev_mode") if isinstance(current.get("prev_mode"), str) else "Circadian"
                _update_mode(controller_id, prev_mode)
                prev_payload = {"mode": prev_mode}
                if last_mode_state.get(controller_id) != prev_payload:
                    last_mode_state[controller_id] = prev_payload
                    _publish_mode_state(client, controller_id, prev_mode)
                _set_mode_local(controller_id, prev_mode, last_mode_state)
                if prev_mode == "Manual":
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=False,
                        color_temp_enabled=False,
                        persist=True,
                    )
                elif prev_mode == "Circadian":
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=True,
                        color_temp_enabled=True,
                        persist=True,
                    )
                wakeup_state.pop(controller_id, None)
                return
            targets = _targets_all(states)
            if targets:
                color_payload = {"color_temp_kelvin": start_ct, "color_mode": "color_temp"} if start_ct is not None else None
                if start_brightness is not None or color_payload:
                    _publish_light_command(
                        client,
                        controller_id,
                        states,
                        start_brightness,
                        color_payload,
                        only_on=False,
                    )
                else:
                    _publish_input_command(client, controller_id, "turn_on_inputs", targets)
            current["applied_start"] = False
            current["last_output"] = "off"
            return

        current["had_on"] = True
        targets = _targets_on(states)
        if not current.get("applied_start"):
            color_payload = {"color_temp_kelvin": start_ct, "color_mode": "color_temp"} if start_ct is not None else None
            if start_brightness is not None or color_payload:
                _publish_light_command(
                    client,
                    controller_id,
                    states,
                    start_brightness,
                    color_payload,
                    only_on=True,
                )
            current["applied_start"] = True

        elapsed = max(0.0, now_ts - float(current.get("start_ts", now_ts)))
        duration = max(1.0, float(wakeup_cfg["duration_minutes"]) * 60.0)
        progress = min(1.0, elapsed / duration)

        step_brightness = None
        step_ct = None
        if isinstance(target_brightness, int) and start_brightness is not None and targets:
            step_brightness = int(round(start_brightness + (target_brightness - start_brightness) * progress))
        if isinstance(target_ct, int):
            step_ct = int(round(start_ct + (target_ct - start_ct) * progress))
        color_payload = {"color_temp_kelvin": step_ct, "color_mode": "color_temp"} if step_ct is not None else None
        if step_brightness is not None or color_payload:
            _publish_light_command(
                client,
                controller_id,
                states,
                step_brightness,
                color_payload,
                only_on=True,
            )

        if progress >= 1.0:
            _update_mode(controller_id, "Circadian")
            prev_mode = last_mode_state.get(controller_id)
            _set_mode_local(controller_id, "Circadian", last_mode_state)
            _set_circadian_flags(
                client,
                controller_id,
                last_circadian_settings,
                brightness_enabled=True,
                color_temp_enabled=True,
                persist=True,
            )
            mode_payload = {"mode": "Circadian"}
            if prev_mode != mode_payload:
                last_mode_state[controller_id] = mode_payload
                _publish_mode_state(client, controller_id, "Circadian")
            wakeup_state.pop(controller_id, None)
        else:
            current["last_output"] = "on"

    def _get_curve_range(points: list[dict]) -> tuple[float | None, float | None]:
        values = [float(point.get("v")) for point in points if isinstance(point, dict) and isinstance(point.get("v"), (int, float))]
        if not values:
            return None, None
        return min(values), max(values)

    def _scale_brightness(brightness: int | None, limits: dict) -> int | None:
        if brightness is None:
            return None
        min_pct = max(1, min(100, int(limits.get("brightness_min_pct", 1))))
        max_pct = max(1, min(100, int(limits.get("brightness_max_pct", 100))))
        if min_pct > max_pct:
            min_pct, max_pct = max_pct, min_pct
        pct = (brightness / 255.0) * 100.0
        scaled_pct = min_pct + (pct / 100.0) * (max_pct - min_pct)
        return int(round((scaled_pct / 100.0) * 255.0))

    def _scale_color_temp(color_temp: int | None, points: list[dict], limits: dict) -> int | None:
        if color_temp is None:
            return None
        min_k = int(limits.get("ct_min_kelvin", 2000))
        max_k = int(limits.get("ct_max_kelvin", 6500))
        if min_k > max_k:
            min_k, max_k = max_k, min_k
        curve_min, curve_max = _get_curve_range(points)
        if curve_min is None or curve_max is None or curve_min == curve_max:
            return int(max(min_k, min(max_k, color_temp)))
        ratio = (color_temp - curve_min) / (curve_max - curve_min)
        ratio = max(0.0, min(1.0, ratio))
        scaled = min_k + ratio * (max_k - min_k)
        return int(round(scaled))

    def _rate_limit(prev: int | None, target: int | None, max_delta: float) -> int | None:
        if target is None:
            return None
        if prev is None:
            return int(round(target))
        if max_delta <= 0:
            return int(round(prev))
        delta = target - prev
        if abs(delta) <= max_delta:
            return int(round(target))
        step = max_delta if delta > 0 else -max_delta
        return int(round(prev + step))

    def _smooth_targets(
        controller_id: str,
        target_brightness: int | None,
        target_ct: int | None,
        smoothing: dict,
        apply_brightness: bool,
        apply_ct: bool,
    ) -> tuple[int | None, int | None]:
        now_ts = time.time()
        last_time = last_smooth_time.get(controller_id, now_ts)
        elapsed = max(0.0, now_ts - last_time)
        brightness_rate = smoothing.get("brightness_rate_pct", 1.6)
        ct_rate = smoothing.get("ct_rate_k", 40.0)
        max_brightness_delta = 255.0 * (brightness_rate / 100.0) * elapsed
        max_ct_delta = ct_rate * elapsed

        prev = last_smoothed.get(controller_id, {})
        if apply_brightness:
            smooth_brightness = (
                target_brightness
                if brightness_rate <= 0
                else _rate_limit(prev.get("brightness"), target_brightness, max_brightness_delta)
            )
        else:
            smooth_brightness = target_brightness
        if apply_ct:
            smooth_ct = (
                target_ct
                if ct_rate <= 0
                else _rate_limit(prev.get("color_temp"), target_ct, max_ct_delta)
            )
        else:
            smooth_ct = target_ct

        last_smoothed[controller_id] = {"brightness": smooth_brightness, "color_temp": smooth_ct}
        last_smooth_time[controller_id] = now_ts
        return smooth_brightness, smooth_ct

    def _compute_targets(
        controller_id: str,
        controller_cfg: dict,
        master: dict,
        states: dict | None = None,
        output_state_override: str | None = None,
        force_reset: bool = False,
    ) -> tuple[
        int | None,
        int | None,
        int | None,
        int | None,
        int | None,
        int | None,
        float | None,
        bool,
        bool,
        bool,
        str,
    ]:
        circadian = controller_cfg.get("circadian") or {}
        brightness_enabled = circadian.get("brightness_enabled", True)
        color_temp_enabled = circadian.get("color_temp_enabled", True)
        circadian_enabled = bool(circadian.get("enabled"))
        raw_brightness, raw_ct = _get_circadian_values(controller_cfg, master)

        output_state = output_state_override
        if output_state is None:
            use_states = states if states is not None else last_inputs.get(controller_id, {})
            output_state, _ = _state_from_inputs(use_states) if use_states else ("off", None)

        smoothing_cfg = _normalize_smoothing_config(master if isinstance(master, dict) else {})
        apply_smoothing = circadian_enabled and output_state == "on" and not force_reset

        weather_reduction_pct = None
        weather_brightness = raw_brightness
        weather_ct = raw_ct
        weather_cfg = _normalize_weather_config(master if isinstance(master, dict) else {})
        legacy_weather_enabled = False
        if isinstance(master, dict):
            legacy_weather = master.get("weather")
            if isinstance(legacy_weather, dict):
                legacy_weather_enabled = bool(legacy_weather.get("enabled", False))
        weather_enabled = controller_cfg.get("weather_enabled")
        if not isinstance(weather_enabled, bool):
            weather_enabled = legacy_weather_enabled
        if weather_enabled and raw_ct is not None:
            weather_values = _get_weather_values(weather_cfg)
            clarity, precip = _compute_clarity(weather_values, weather_cfg)
            weather_payload = {
                "clarity": clarity,
                "precip": precip,
                "max_reduction_pct": weather_cfg.get("max_reduction_pct", 0.0),
            }
            limits = _normalize_limits(controller_cfg.get("limits"))
            weather_ct, weather_reduction_pct = _apply_weather_ct_with_reduction(raw_ct, limits, weather_payload)
            if weather_reduction_pct is not None:
                weather_reduction_pct = float(weather_reduction_pct)
            debug_weather_min = limits.get("weather_min_kelvin")
            if not isinstance(debug_weather_min, int):
                debug_weather_min = limits.get("ct_min_kelvin")
            if isinstance(debug_weather_min, int):
                debug_weather_min = max(
                    limits.get("ct_min_kelvin", debug_weather_min),
                    min(limits.get("ct_max_kelvin", debug_weather_min), debug_weather_min),
                )
            debug_payload = {
                "weather_values": weather_values,
                "clarity": clarity,
                "precip": precip,
                "max_reduction_pct": weather_cfg.get("max_reduction_pct", 0.0),
                "cloud_weight": weather_cfg.get("cloud_weight"),
                "uv_weight": weather_cfg.get("uv_weight"),
                "visibility_weight": weather_cfg.get("visibility_weight"),
                "ct_min_kelvin": limits.get("ct_min_kelvin"),
                "ct_max_kelvin": limits.get("ct_max_kelvin"),
                "weather_min_kelvin": debug_weather_min,
                "raw_ct": raw_ct,
                "weather_ct": weather_ct,
                "weather_reduction_pct": weather_reduction_pct,
            }
            last_debug = last_weather_debug.get(controller_id)
            now_ts = time.time()
            if (
                last_debug is None
                or last_debug.get("payload") != debug_payload
                or now_ts - float(last_debug.get("ts", 0.0)) > 300
            ):
                last_weather_debug[controller_id] = {"ts": now_ts, "payload": debug_payload}
                logger.info("WeatherCalc %s %s", controller_id, json.dumps(debug_payload, sort_keys=True))

        if apply_smoothing:
            smooth_brightness, smooth_ct = _smooth_targets(
                controller_id,
                weather_brightness,
                weather_ct,
                smoothing_cfg,
                brightness_enabled,
                color_temp_enabled,
            )
        else:
            # Start at the current weather-adjusted targets so "turn on"
            # uses the correct values without a jump.
            smooth_brightness = weather_brightness if circadian_enabled else raw_brightness
            smooth_ct = weather_ct if circadian_enabled else raw_ct
            last_smoothed[controller_id] = {"brightness": smooth_brightness, "color_temp": smooth_ct}
            last_smooth_time[controller_id] = time.time()

        return (
            raw_brightness,
            raw_ct,
            weather_brightness,
            weather_ct,
            smooth_brightness,
            smooth_ct,
            weather_reduction_pct,
            brightness_enabled,
            color_temp_enabled,
            circadian_enabled,
            output_state,
        )

    def _publish_circadian_targets(
        controller_id: str,
        controller_cfg: dict,
        master: dict,
        states: dict | None = None,
        output_state_override: str | None = None,
        force_reset: bool = False,
    ) -> tuple[int | None, int | None, bool, str, bool, bool]:
        (
            raw_brightness,
            raw_ct,
            weather_brightness,
            weather_ct,
            smooth_brightness,
            smooth_ct,
            weather_reduction_pct,
            brightness_enabled,
            color_temp_enabled,
            circadian_enabled,
            output_state,
        ) = _compute_targets(
            controller_id,
            controller_cfg,
            master,
            states=states,
            output_state_override=output_state_override,
            force_reset=force_reset,
        )

        state_payload = {
            "brightness_enabled": bool(brightness_enabled),
            "color_temp_enabled": bool(color_temp_enabled),
            "brightness_target_raw": raw_brightness,
            "color_temp_target_raw": raw_ct,
            "brightness_target_weather": weather_brightness,
            "color_temp_target_weather": weather_ct,
            "brightness_target": smooth_brightness,
            "color_temp_target": smooth_ct,
            "weather_reduction_pct": weather_reduction_pct,
        }
        if last_circadian_state.get(controller_id) != state_payload:
            last_circadian_state[controller_id] = state_payload
            state_topic = TOPIC_CIRCADIAN_STATE.format(controller_id)
            client.publish(state_topic, json.dumps(state_payload), qos=0, retain=True)

        return smooth_brightness, smooth_ct, circadian_enabled, output_state, brightness_enabled, color_temp_enabled

    def _get_circadian_values(controller: dict, master: dict) -> tuple[int | None, int | None]:
        circadian = controller.get("circadian") or {}
        if not isinstance(circadian, dict) or not circadian.get("enabled"):
            return None, None

        brightness_enabled = circadian.get("brightness_enabled", True)
        color_temp_enabled = circadian.get("color_temp_enabled", True)

        brightness_points = circadian.get("brightness_curve", [])
        if circadian.get("use_master_brightness") and isinstance(master, dict):
            brightness_points = master.get("brightness_curve", brightness_points)
        color_temp_points = circadian.get("color_temp_curve", [])
        if circadian.get("use_master_color_temp") and isinstance(master, dict):
            color_temp_points = master.get("color_temp_curve", color_temp_points)

        now = datetime.now(_get_time_zone())
        t_minutes = now.hour * 60 + now.minute + (now.second / 60.0)

        sun_attrs = _get_sun_attrs()
        sunrise, sunset = _today_sun_times(now, sun_attrs)
        base_sunrise = circadian.get("base_sunrise")
        base_sunset = circadian.get("base_sunset")
        if not isinstance(base_sunrise, (int, float)):
            base_sunrise = sunrise
        if not isinstance(base_sunset, (int, float)):
            base_sunset = sunset
        dst_offset = _dst_offset_minutes(now, _get_time_zone())

        use_master_brightness = circadian.get("use_master_brightness") and isinstance(master, dict)
        use_master_color = circadian.get("use_master_color_temp") and isinstance(master, dict)
        solar_brightness = (
            master.get("solar_shift_brightness", True)
            if use_master_brightness and isinstance(master, dict)
            else circadian.get("solar_shift_brightness", True)
        )
        solar_color = (
            master.get("solar_shift_color_temp", True)
            if use_master_color and isinstance(master, dict)
            else circadian.get("solar_shift_color_temp", True)
        )

        brightness_val = (
            _evaluate_solar_curve(
                brightness_points,
                t_minutes,
                base_sunrise,
                base_sunset,
                sunrise,
                sunset,
                dst_offset if solar_brightness else 0,
            )
            if solar_brightness
            else _evaluate_curve(brightness_points, t_minutes)
        )

        color_temp_val = (
            _evaluate_solar_curve(
                color_temp_points,
                t_minutes,
                base_sunrise,
                base_sunset,
                sunrise,
                sunset,
                dst_offset if solar_color else 0,
            )
            if solar_color
            else _evaluate_curve(color_temp_points, t_minutes)
        )

        brightness = int(max(0, min(255, round(brightness_val)))) if brightness_val is not None else None
        color_temp = int(max(1500, min(8000, round(color_temp_val)))) if color_temp_val is not None else None

        limits = _normalize_limits(controller.get("limits"))
        brightness = _scale_brightness(brightness, limits)
        color_temp = _scale_color_temp(color_temp, color_temp_points, limits)
        return brightness, color_temp

    def _circadian_tick() -> bool:
        controllers, master = _load_controller_cache()
        if not controllers:
            return False

        retry_cfg = _normalize_retry_config(master)
        if retry_cfg != RETRY_CONFIG:
            RETRY_CONFIG.update(retry_cfg)
            RETRY_TOLERANCES.update(
                {
                    "brightness": retry_cfg.get("tolerance_brightness", 2),
                    "ct_kelvin": retry_cfg.get("tolerance_ct_k", 25),
                    "hs": retry_cfg.get("tolerance_hs", 3.0),
                    "rgb": retry_cfg.get("tolerance_rgb", 3),
                    "xy": retry_cfg.get("tolerance_xy", 0.01),
                }
            )
            if not RETRY_CONFIG.get("enabled") and RETRY_PENDING:
                RETRY_PENDING.clear()

        wakeup_active = False
        for controller in controllers:
            if not isinstance(controller, dict):
                continue
            circadian = controller.get("circadian") or {}
            if not isinstance(circadian, dict):
                circadian = {}

            unique_id = controller.get("unique_id") or controller.get("name")
            if not isinstance(unique_id, str) or not unique_id:
                continue

            controller_id = _normalize_controller_id(unique_id)
            limits_state = _normalize_limits(controller.get("limits"))
            if last_limits_state.get(controller_id) != limits_state:
                last_limits_state[controller_id] = limits_state
                limits_topic = TOPIC_LIMITS_STATE.format(controller_id)
                client.publish(limits_topic, json.dumps(limits_state), qos=0, retain=True)
            mode_value = _normalize_mode(last_mode_state.get(controller_id, {}).get("mode") or controller.get("mode"))
            settings = last_circadian_settings.get(controller_id, {})
            brightness_enabled = settings.get("brightness_enabled", circadian.get("brightness_enabled", True))
            color_temp_enabled = settings.get("color_temp_enabled", circadian.get("color_temp_enabled", True))
            if mode_value in ("Manual", "Sleep"):
                brightness_enabled = False
                color_temp_enabled = False
            mode_value = _sync_mode_with_switches(
                controller_id,
                controller,
                bool(brightness_enabled),
                bool(color_temp_enabled),
                current_mode=last_mode_state.get(controller_id, {}).get("mode"),
            )
            mode_payload = {"mode": mode_value}
            if last_mode_state.get(controller_id) != mode_payload:
                last_mode_state[controller_id] = mode_payload
                _publish_mode_state(client, controller_id, mode_value)
            _set_circadian_flags(
                client,
                controller_id,
                last_circadian_settings,
                brightness_enabled=brightness_enabled,
                color_temp_enabled=color_temp_enabled,
                persist=mode_value == "Manual",
            )
            states = last_inputs.get(controller_id, {})
            smooth_brightness, smooth_ct, circadian_enabled, output_state, brightness_enabled, color_temp_enabled = _publish_circadian_targets(
                controller_id,
                controller,
                master,
                states=states,
            )
            if mode_value == "Away":
                _handle_away_mode(
                    controller_id,
                    states,
                    master,
                    smooth_brightness,
                    smooth_ct,
                    bool(brightness_enabled),
                    bool(color_temp_enabled),
                    circadian_interval,
                )
                continue
            away_state.pop(controller_id, None)
            away_payload = {
                "active": False,
                "on": False,
                "next_ts": None,
                "next_iso": None,
                "window_start": None,
                "window_end": None,
            }
            if last_away_state.get(controller_id) != away_payload:
                last_away_state[controller_id] = away_payload
                _publish_away_state(client, controller_id, away_payload)
            if mode_value == "Sleep":
                _handle_sleep_mode(
                    controller_id,
                    controller,
                    master,
                    states,
                    output_state,
                )
                continue
            if mode_value == "WakeUp":
                _handle_wakeup_mode(
                    controller_id,
                    controller,
                    master,
                    states,
                    output_state,
                    smooth_brightness,
                    smooth_ct,
                )
                wakeup_active = True
                continue
            last_sleep_state.pop(controller_id, None)
            wakeup_state.pop(controller_id, None)
            if not circadian_enabled:
                continue
            if not states:
                continue
            if output_state != "on":
                continue

            brightness = smooth_brightness if brightness_enabled else None
            color_temp = smooth_ct if color_temp_enabled else None

            if brightness is None and color_temp is None:
                continue

            last = last_circadian.get(controller_id, {})
            if last.get("brightness") == brightness and last.get("color_temp") == color_temp:
                continue

            if brightness is not None or color_temp is not None:
                color_payload = {"color_temp_kelvin": color_temp, "color_mode": "color_temp"} if color_temp is not None else None
                _publish_light_command(
                    client,
                    controller_id,
                    states,
                    brightness,
                    color_payload,
                    only_on=True,
                )

            last_circadian[controller_id] = {"brightness": brightness, "color_temp": color_temp}
        return wakeup_active
    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT connect failed with code %s", rc)
            return
        logger.info("Connected to MQTT at %s:%s", host, port)
        client.subscribe(TOPIC_INPUTS)
        client.subscribe(TOPIC_EVENTS)
        client.subscribe(TOPIC_CIRCADIAN_SET)
        client.subscribe(TOPIC_LIMITS_SET)
        client.subscribe(TOPIC_MODE_SET)

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            logger.warning("MQTT disconnected (rc=%s). Reconnecting...", rc)
        else:
            logger.info("MQTT disconnected.")

    def on_message(client, userdata, msg):
        topic = msg.topic
        parts = topic.split("/")
        if len(parts) < 3:
            return

        controller_id = parts[1]
        suffix = parts[2]
        if msg.retain:
            controllers, _ = _load_controller_cache()
            known_ids = {
                _normalize_controller_id((controller.get("unique_id") or controller.get("name") or "").strip())
                for controller in controllers
                if isinstance(controller, dict)
            }
            if controller_id not in known_ids:
                _clear_retained_topics(controller_id)
                logger.warning("Cleared retained MQTT topics for unknown controller %s", controller_id)
                return

        if suffix == "circadian" and len(parts) > 3 and parts[3] == "set":
            payload = _parse_payload(msg.payload)
            if not isinstance(payload, dict):
                return

            brightness_enabled = payload.get("brightness_enabled")
            color_temp_enabled = payload.get("color_temp_enabled")
            if brightness_enabled is None and color_temp_enabled is None:
                return

            _set_circadian_flags(
                client,
                controller_id,
                last_circadian_settings,
                brightness_enabled=brightness_enabled,
                color_temp_enabled=color_temp_enabled,
                persist=True,
            )
            controllers, master = _load_controller_cache()
            controller_cfg = next(
                (
                    controller
                    for controller in controllers
                    if isinstance(controller, dict)
                    and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                    == controller_id
                ),
                None,
            )
            if controller_cfg:
                effective = last_circadian_settings.get(controller_id, {})
                effective_brightness = effective.get(
                    "brightness_enabled",
                    bool(brightness_enabled) if brightness_enabled is not None else bool(controller_cfg.get("circadian", {}).get("brightness_enabled", True)),
                )
                effective_color = effective.get(
                    "color_temp_enabled",
                    bool(color_temp_enabled) if color_temp_enabled is not None else bool(controller_cfg.get("circadian", {}).get("color_temp_enabled", True)),
                )
                mode_value = _sync_mode_with_switches(
                    controller_id,
                    controller_cfg,
                    bool(effective_brightness),
                    bool(effective_color),
                    current_mode=last_mode_state.get(controller_id, {}).get("mode"),
                )
                mode_payload = {"mode": mode_value}
                if last_mode_state.get(controller_id) != mode_payload:
                    last_mode_state[controller_id] = mode_payload
                    _publish_mode_state(client, controller_id, mode_value)
                _publish_circadian_targets(controller_id, controller_cfg, master)
            return

        if suffix == "limits" and len(parts) > 3 and parts[3] == "set":
            payload = _parse_payload(msg.payload)
            if not isinstance(payload, dict):
                return

            updated = _update_limits(controller_id, payload)
            if updated or controller_id not in last_limits_state:
                controllers, master = _load_controller_cache()
                controller_cfg = next(
                    (
                        controller
                        for controller in controllers
                        if isinstance(controller, dict)
                        and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                        == controller_id
                    ),
                    None,
                )
                limits_state = _normalize_limits(controller_cfg.get("limits") if controller_cfg else None)
                last_limits_state[controller_id] = limits_state
                limits_topic = TOPIC_LIMITS_STATE.format(controller_id)
                client.publish(limits_topic, json.dumps(limits_state), qos=0, retain=True)
                if controller_cfg:
                    _publish_circadian_targets(controller_id, controller_cfg, master)
            return

        if suffix == "mode" and len(parts) > 3 and parts[3] == "set":
            payload = _parse_payload(msg.payload)
            if isinstance(payload, dict):
                mode_value = payload.get("mode")
            else:
                mode_value = payload
            normalized = _normalize_mode(mode_value)
            prev_mode_value = _normalize_mode(last_mode_state.get(controller_id, {}).get("mode"))
            updated = _update_mode(controller_id, normalized)
            _set_mode_local(controller_id, normalized, last_mode_state)
            if normalized != "Sleep":
                last_sleep_state.pop(controller_id, None)
            if normalized != "WakeUp":
                wakeup_state.pop(controller_id, None)
            if normalized == "Manual":
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=False,
                    color_temp_enabled=False,
                    persist=True,
                )
            elif normalized == "Sleep":
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=False,
                    color_temp_enabled=False,
                    persist=False,
                )
                last_sleep_state[controller_id] = {"mode": "Sleep", "pending": True, "last_output": None}
            elif normalized == "WakeUp":
                if prev_mode_value == "WakeUp":
                    prev_mode_value = "Circadian"
                wakeup_state[controller_id] = {"prev_mode": prev_mode_value}
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=True,
                    color_temp_enabled=True,
                    persist=True,
                )
            elif normalized == "Circadian":
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=True,
                    color_temp_enabled=True,
                    persist=True,
                )
            controllers, master = _load_controller_cache()
            controller_cfg = next(
                (
                    controller
                    for controller in controllers
                    if isinstance(controller, dict)
                    and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                    == controller_id
                ),
                None,
            )
            circadian_cfg = controller_cfg.get("circadian") if isinstance(controller_cfg, dict) else {}
            settings = last_circadian_settings.get(controller_id, {})
            brightness_enabled = settings.get("brightness_enabled", bool(circadian_cfg.get("brightness_enabled", True)))
            color_temp_enabled = settings.get("color_temp_enabled", bool(circadian_cfg.get("color_temp_enabled", True)))
            mode_value = _sync_mode_with_switches(
                controller_id,
                controller_cfg,
                brightness_enabled,
                color_temp_enabled,
                current_mode=normalized,
            )
            mode_payload = {"mode": mode_value}
            if updated or last_mode_state.get(controller_id) != mode_payload:
                last_mode_state[controller_id] = mode_payload
                _publish_mode_state(client, controller_id, mode_value)
            if controller_cfg:
                states = last_inputs.get(controller_id, {})
                (
                    _raw_brightness,
                    _raw_ct,
                    _weather_brightness,
                    _weather_ct,
                    smooth_brightness,
                    smooth_ct,
                    _weather_reduction_pct,
                    _brightness_enabled,
                    _color_temp_enabled,
                    _circadian_enabled,
                    _output_state,
                ) = _compute_targets(
                    controller_id,
                    controller_cfg,
                    master,
                    states=states,
                    output_state_override=None,
                    force_reset=False,
                )
                _publish_circadian_targets(controller_id, controller_cfg, master, states=states)
                if mode_value == "Away":
                    _handle_away_mode(
                        controller_id,
                        states,
                        master,
                        smooth_brightness,
                        smooth_ct,
                        bool(brightness_enabled),
                        bool(color_temp_enabled),
                        circadian_interval,
                    )
                else:
                    away_state.pop(controller_id, None)
                    away_payload = {
                        "active": False,
                        "on": False,
                        "next_ts": None,
                        "next_iso": None,
                        "window_start": None,
                        "window_end": None,
                    }
                    if last_away_state.get(controller_id) != away_payload:
                        last_away_state[controller_id] = away_payload
                        _publish_away_state(client, controller_id, away_payload)
                if normalized == "Circadian" and _output_state == "on":
                    color_payload = (
                        {"color_temp_kelvin": smooth_ct, "color_mode": "color_temp"}
                        if isinstance(smooth_ct, int) and bool(color_temp_enabled)
                        else None
                    )
                    _publish_light_command(
                        client,
                        controller_id,
                        states,
                        smooth_brightness if isinstance(smooth_brightness, int) and bool(brightness_enabled) else None,
                        color_payload,
                        only_on=True,
                    )
                if mode_value == "Sleep":
                    _handle_sleep_mode(
                        controller_id,
                        controller_cfg,
                        master,
                        states,
                        _output_state,
                    )
                if mode_value == "WakeUp":
                    _handle_wakeup_mode(
                        controller_id,
                        controller_cfg,
                        master,
                        states,
                        _output_state,
                        smooth_brightness,
                        smooth_ct,
                    )
            return

        if suffix == "event":
            payload = _parse_payload(msg.payload)
            if isinstance(payload, dict):
                event = str(payload.get("event", "")).strip().lower()
                brightness = payload.get("brightness")
                effect = payload.get("effect")
                color_mode, color_payload = _extract_color_payload(payload)
            else:
                event = str(payload).strip().lower()
                brightness = None
                effect = None
                color_mode = None
                color_payload = {}

            states = last_inputs.get(controller_id, {})
            if event == "manual_off":
                controllers, master = _load_controller_cache()
                controller_cfg = next(
                    (
                        controller
                        for controller in controllers
                        if isinstance(controller, dict)
                        and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                        == controller_id
                    ),
                    None,
                )
                mode_value = _normalize_mode(controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
                if mode_value == "Manual":
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=False,
                        color_temp_enabled=False,
                        persist=True,
                    )
                _publish_input_command(client, controller_id, "turn_off_inputs", _targets_on(states))
                if controller_cfg:
                    _publish_circadian_targets(
                        controller_id,
                        controller_cfg,
                        master,
                        states=states,
                        output_state_override="off",
                        force_reset=True,
                    )
            elif event == "manual_on":
                targets = _targets_all(states)
                controllers, master = _load_controller_cache()
                controller_cfg = next(
                    (
                        controller
                        for controller in controllers
                        if isinstance(controller, dict)
                        and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                        == controller_id
                    ),
                    None,
                )
                mode_value = _normalize_mode(controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
                if mode_value not in ("Away", "WakeUp", "Sleep"):
                    _update_mode(controller_id, "Circadian")
                    prev_mode = last_mode_state.get(controller_id)
                    _set_mode_local(controller_id, "Circadian", last_mode_state)
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=True,
                        color_temp_enabled=True,
                        persist=True,
                    )
                    mode_payload = {"mode": "Circadian"}
                    if prev_mode != mode_payload:
                        last_mode_state[controller_id] = mode_payload
                        _publish_mode_state(client, controller_id, "Circadian")
                elif mode_value == "Away":
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=True,
                        color_temp_enabled=True,
                        persist=True,
                    )
                if brightness is None and not color_payload and mode_value != "Sleep":
                    if controller_cfg:
                        smooth_brightness, smooth_ct, _, _, _, _ = _publish_circadian_targets(
                            controller_id,
                            controller_cfg,
                            master,
                            states=states,
                            output_state_override="on",
                            force_reset=True,
                        )
                        color_payload = (
                            {"color_temp_kelvin": smooth_ct, "color_mode": "color_temp"}
                            if isinstance(smooth_ct, int)
                            else None
                        )
                        if isinstance(smooth_brightness, int) or color_payload:
                            _publish_light_command(
                                client,
                                controller_id,
                                states,
                                smooth_brightness if isinstance(smooth_brightness, int) else None,
                                color_payload,
                                only_on=False,
                            )
                elif isinstance(brightness, int) or color_payload:
                    _publish_light_command(
                        client,
                        controller_id,
                        states,
                        brightness if isinstance(brightness, int) else None,
                        color_payload,
                        only_on=False,
                    )
                if isinstance(effect, str) and effect:
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_effect_inputs",
                        targets,
                        effect=effect,
                    )
                if mode_value == "Sleep" and controller_cfg:
                    _apply_sleep_targets(controller_id, controller_cfg, master, states, only_on=False)
                    last_sleep_state[controller_id] = {"mode": "Sleep", "pending": False, "last_output": "on"}
            elif event == "manual_brightness" and isinstance(brightness, int):
                controllers, master = _load_controller_cache()
                controller_cfg = next(
                    (
                        controller
                        for controller in controllers
                        if isinstance(controller, dict)
                        and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                        == controller_id
                    ),
                    None,
                )
                mode_value = _normalize_mode(controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
                if mode_value == "WakeUp":
                    _update_mode(controller_id, "Circadian")
                    prev_mode = last_mode_state.get(controller_id)
                    _set_mode_local(controller_id, "Circadian", last_mode_state)
                    mode_payload = {"mode": "Circadian"}
                    if prev_mode != mode_payload:
                        last_mode_state[controller_id] = mode_payload
                        _publish_mode_state(client, controller_id, "Circadian")
                    wakeup_state.pop(controller_id, None)
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=False,
                    persist=True,
                )
                _publish_input_command(
                    client,
                    controller_id,
                    "set_brightness_inputs",
                    _targets_on(states),
                    brightness,
                )
                if controller_cfg:
                    _publish_circadian_targets(controller_id, controller_cfg, master, states=states)
            elif event == "manual_color" and color_payload:
                controllers, master = _load_controller_cache()
                controller_cfg = next(
                    (
                        controller
                        for controller in controllers
                        if isinstance(controller, dict)
                        and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                        == controller_id
                    ),
                    None,
                )
                mode_value = _normalize_mode(controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
                if mode_value == "WakeUp":
                    _update_mode(controller_id, "Circadian")
                    prev_mode = last_mode_state.get(controller_id)
                    _set_mode_local(controller_id, "Circadian", last_mode_state)
                    mode_payload = {"mode": "Circadian"}
                    if prev_mode != mode_payload:
                        last_mode_state[controller_id] = mode_payload
                        _publish_mode_state(client, controller_id, "Circadian")
                    wakeup_state.pop(controller_id, None)
                if (
                    "color_temp" in color_payload
                    or "color_temp_kelvin" in color_payload
                    or color_mode == "color_temp"
                ):
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        color_temp_enabled=False,
                        persist=True,
                    )
                color_targets = _targets_with_mode(states, color_mode, only_on=True)
                _publish_input_command(
                    client,
                    controller_id,
                    "set_color_inputs",
                    color_targets,
                    color_payload=color_payload,
                )
                if controller_cfg:
                    _publish_circadian_targets(controller_id, controller_cfg, master, states=states)
            elif event == "manual_effect" and isinstance(effect, str) and effect:
                _publish_input_command(
                    client,
                    controller_id,
                    "set_effect_inputs",
                    _targets_on(states),
                    effect=effect,
                )
            return

        if suffix != "inputs":
            return

        payload = _parse_payload(msg.payload)
        prev_states = last_inputs.get(controller_id, {})
        states = payload.get("states", {}) if isinstance(payload, dict) else {}
        newly_available = []
        if isinstance(states, dict):
            for entity_id, value in states.items():
                if not isinstance(value, dict):
                    continue
                if _is_unavailable(value):
                    continue
                prev_value = prev_states.get(entity_id) if isinstance(prev_states, dict) else None
                if not isinstance(prev_value, dict) or _is_unavailable(prev_value):
                    newly_available.append(entity_id)
        last_inputs[controller_id] = states
        if isinstance(states, dict) and states:
            total_inputs = len(states)
            unavailable = sum(
                1
                for value in states.values()
                if isinstance(value, dict)
                and str(value.get("state", "")).strip().lower() in {"unknown", "unavailable"}
            )
            all_unavailable = unavailable == total_inputs
            any_unavailable = unavailable > 0
        else:
            total_inputs = 0
            unavailable = 0
            all_unavailable = True
            any_unavailable = True
        status_payload = {
            "all_unavailable": bool(all_unavailable),
            "any_unavailable": bool(any_unavailable),
            "available_count": max(0, total_inputs - unavailable),
            "total_count": total_inputs,
        }
        status_topic = TOPIC_INPUTS_STATUS.format(controller_id)
        client.publish(status_topic, json.dumps(status_payload), qos=0, retain=True)

        output_state, output_brightness = _state_from_inputs(states)
        controllers, master = _load_controller_cache()
        controller_cfg = next(
            (
                controller
                for controller in controllers
                if isinstance(controller, dict)
                and _normalize_controller_id(controller.get("unique_id") or controller.get("name") or "")
                == controller_id
            ),
            None,
        )
        if not controller_cfg:
            logger.warning("Ignoring inputs for unknown controller %s (stale retained MQTT data?)", controller_id)
            return
        if controller_cfg:
            prev_state = last_output.get(controller_id, {}).get("state")
            mode_value = _normalize_mode(
                last_mode_state.get(controller_id, {}).get("mode")
                or (controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
            )
            if output_state == "on" and prev_state != "on":
                if mode_value == "Away":
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=True,
                        color_temp_enabled=True,
                        persist=True,
                    )
                elif mode_value not in ("Away", "WakeUp", "Sleep"):
                    if mode_value != "Circadian":
                        _update_mode(controller_id, "Circadian")
                        prev_mode = last_mode_state.get(controller_id)
                        _set_mode_local(controller_id, "Circadian", last_mode_state)
                        mode_payload = {"mode": "Circadian"}
                        if prev_mode != mode_payload:
                            last_mode_state[controller_id] = mode_payload
                            _publish_mode_state(client, controller_id, "Circadian")
                    _set_circadian_flags(
                        client,
                        controller_id,
                        last_circadian_settings,
                        brightness_enabled=True,
                        color_temp_enabled=True,
                        persist=True,
                    )
            if output_state != "on" and mode_value == "Circadian":
                _set_circadian_flags(
                    client,
                    controller_id,
                    last_circadian_settings,
                    brightness_enabled=True,
                    color_temp_enabled=True,
                    persist=True,
                )
            _publish_circadian_targets(
                controller_id,
                controller_cfg,
                master,
                states=states,
                output_state_override=output_state,
                force_reset=output_state != "on",
            )
            mode_value = _normalize_mode(
                last_mode_state.get(controller_id, {}).get("mode")
                or (controller_cfg.get("mode") if isinstance(controller_cfg, dict) else None)
            )
            if mode_value == "Sleep":
                _handle_sleep_mode(controller_id, controller_cfg, master, states, output_state)
            else:
                last_sleep_state.pop(controller_id, None)
        modes = _union_color_modes(states)
        min_mireds, max_mireds = _union_mireds(states)
        color_payload = _median_color_from_inputs(states)
        effect_list = _union_effect_list(states)
        effect = _most_common_effect(states)

        output_payload = {
            "state": output_state,
            "brightness": output_brightness,
            "supported_color_modes": modes,
            "min_mireds": min_mireds,
            "max_mireds": max_mireds,
            "effect_list": effect_list,
            "effect": effect,
        }
        output_payload.update(color_payload)

        if newly_available:
            desired = last_output.get(controller_id) if isinstance(last_output.get(controller_id), dict) else None
            desired_state = desired.get("state") if desired else output_state
            if desired_state == "on":
                _publish_input_command(client, controller_id, "turn_on_inputs", newly_available)
                desired_brightness = desired.get("brightness") if desired else output_brightness
                desired_effect = desired.get("effect") if desired else None
                desired_color = {}
                if desired:
                    for key in (
                        "hs_color",
                        "rgb_color",
                        "rgbw_color",
                        "rgbww_color",
                        "xy_color",
                        "color_temp",
                        "color_temp_kelvin",
                        "color_mode",
                    ):
                        if key in desired:
                            desired_color[key] = desired[key]
                else:
                    desired_color = _median_color_from_inputs(states)
                if isinstance(desired_effect, str) and desired_effect:
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_effect_inputs",
                        newly_available,
                        effect=desired_effect,
                    )
                if desired_color:
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_color_inputs",
                        newly_available,
                        desired_brightness,
                        color_payload=desired_color,
                    )
                elif desired_brightness is not None:
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_brightness_inputs",
                        newly_available,
                        desired_brightness,
                    )

        if "rgb_color" in output_payload and isinstance(output_payload["rgb_color"], list) and len(output_payload["rgb_color"]) == 3:
            r, g, b = output_payload["rgb_color"]
            if "rgbw" in (modes or []) and "rgbw_color" not in output_payload:
                output_payload["rgbw_color"] = [r, g, b, 0]
            if "rgbww" in (modes or []) and "rgbww_color" not in output_payload:
                output_payload["rgbww_color"] = [r, g, b, 0, 0]

        color_mode = _select_color_mode(modes, output_payload)
        if color_mode:
            output_payload["color_mode"] = color_mode
            if color_mode != "color_temp":
                output_payload.pop("color_temp", None)
                output_payload.pop("color_temp_kelvin", None)

        if _payload_equals(last_output.get(controller_id), output_payload):
            return

        last_output[controller_id] = output_payload
        _publish_output_state(
            client,
            controller_id,
            output_state,
            output_brightness,
            modes,
            min_mireds,
            max_mireds,
            color_payload,
            effect_list,
            effect,
        )
        logger.debug("Published %s/%s to %s", output_state, output_brightness, controller_id)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    if username and password:
        client.username_pw_set(username, password)

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            client.connect(host, port, 60)
            client.loop_start()
            # Allow time for initial connect without thrashing reconnects.
            for _ in range(50):
                if client.is_connected():
                    break
                time.sleep(0.1)
            _request_startup_cleanup()
            _flush_retained_clears()
            while True:
                if not client.is_connected():
                    time.sleep(1)
                    continue
                _flush_retained_clears()
                wakeup_active = _circadian_tick()
                runtime = _read_runtime_payload()
                circadian_interval = runtime.get("circadian_interval", circadian_interval)
                wakeup_interval = runtime.get("wakeup_interval", wakeup_interval)
                sleep_seconds = wakeup_interval if wakeup_active else circadian_interval
                next_tick = time.time() + float(sleep_seconds)
                if RETRY_CONFIG.get("enabled"):
                    while time.time() < next_tick:
                        _process_retries()
                        remaining = next_tick - time.time()
                        if remaining <= 0:
                            break
                        time.sleep(min(1.0, remaining))
                else:
                    time.sleep(sleep_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.error("MQTT error: %s", exc)
            client.loop_stop()
            time.sleep(5)


if __name__ == "__main__":
    main()





