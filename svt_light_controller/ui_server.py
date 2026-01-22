"""SVT Light Controller add-on web UI server."""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CONFIG_PATH = "/config/svtlc_controllers.json"
RUNTIME_PATH = "/config/svtlc_runtime.json"
WEB_ROOT = "/webui"
PORT = int(os.environ.get("INGRESS_PORT") or os.environ.get("PORT") or "8099")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


def _read_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {"controllers": [], "master": {}}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"controllers": [], "master": {}}
    if isinstance(data, dict) and isinstance(data.get("controllers"), list):
        payload = {"controllers": data.get("controllers", [])}
        if isinstance(data.get("master"), dict):
            payload["master"] = data.get("master", {})
        else:
            payload["master"] = {}
        return payload
    if isinstance(data, list):
        return {"controllers": data, "master": {}}
    return {"controllers": [], "master": {}}


def _write_config(payload: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = f"{CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp_path, CONFIG_PATH)


def _read_runtime() -> dict:
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


def _write_runtime(payload: dict) -> None:
    os.makedirs(os.path.dirname(RUNTIME_PATH), exist_ok=True)
    current = _read_runtime()
    if "modes" in payload and isinstance(payload.get("modes"), dict):
        modes = current.get("modes", {})
        if not isinstance(modes, dict):
            modes = {}
        modes.update(payload["modes"])
        current["modes"] = modes
        payload = {k: v for k, v in payload.items() if k != "modes"}
    current.update(payload)
    tmp_path = f"{RUNTIME_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2)
    os.replace(tmp_path, RUNTIME_PATH)



def _fetch_ha_config() -> dict | None:
    if not SUPERVISOR_TOKEN:
        return None
    url = "http://supervisor/core/api/config"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _parse_iso(ts: str) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_sun_state() -> dict | None:
    if not SUPERVISOR_TOKEN:
        return None
    url = "http://supervisor/core/api/states/sun.sun"
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


def _today_sun_times(now: datetime, sun_attrs: dict | None) -> tuple[int | None, int | None]:
    if not sun_attrs:
        return None, None
    next_rising = _parse_iso(sun_attrs.get("next_rising"))
    next_setting = _parse_iso(sun_attrs.get("next_setting"))
    if not next_rising or not next_setting:
        return None, None

    sunrise = next_rising if next_rising.date() == now.date() else next_rising - timedelta(days=1)
    sunset = next_setting if next_setting.date() == now.date() else next_setting - timedelta(days=1)
    return (
        sunrise.hour * 60 + sunrise.minute,
        sunset.hour * 60 + sunset.minute,
    )


def _sunrise_sunset(day: date, latitude: float, longitude: float, tz: ZoneInfo) -> tuple[int | None, int | None]:
    zenith = 90.833
    n = day.timetuple().tm_yday
    lng_hour = longitude / 15.0

    def _calc_time(is_sunrise: bool) -> int | None:
        t = n + ((6 - lng_hour) / 24.0) if is_sunrise else n + ((18 - lng_hour) / 24.0)
        m = (0.9856 * t) - 3.289
        l = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
        l = l % 360
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l))))
        ra = ra % 360
        l_quadrant = (math.floor(l / 90.0)) * 90.0
        ra_quadrant = (math.floor(ra / 90.0)) * 90.0
        ra = (ra + (l_quadrant - ra_quadrant)) / 15.0

        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(latitude)))) / (
            cos_dec * math.cos(math.radians(latitude))
        )
        if cos_h > 1 or cos_h < -1:
            return None

        h = (360 - math.degrees(math.acos(cos_h))) if is_sunrise else math.degrees(math.acos(cos_h))
        h = h / 15.0
        t_local = h + ra - (0.06571 * t) - 6.622
        ut = (t_local - lng_hour) % 24

        dt = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("UTC"))
        dt = dt.replace(hour=int(ut), minute=int((ut % 1) * 60))
        local_dt = dt.astimezone(tz)
        return local_dt.hour * 60 + local_dt.minute

    return _calc_time(True), _calc_time(False)


def _build_solar_payload() -> dict:
    config = _fetch_ha_config() or {}
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    time_zone = config.get("time_zone") or "UTC"
    tz = ZoneInfo(time_zone)
    now = datetime.now(tz)
    now_minutes = now.hour * 60 + now.minute + now.second / 60
    now_epoch = now.timestamp()

    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return {
            "today": {"sunrise": 360, "sunset": 1080, "dst_offset": 0},
            "months": [],
            "current_month": None,
            "now_minutes": now_minutes,
        }

    today = now.date()
    sun_attrs = _fetch_sun_state()
    sun_sunrise, sun_sunset = _today_sun_times(now, sun_attrs)
    sunrise, sunset = _sunrise_sunset(today, latitude, longitude, tz)
    sunrise = sun_sunrise if sun_sunrise is not None else sunrise
    sunset = sun_sunset if sun_sunset is not None else sunset
    sunrise = sunrise if sunrise is not None else 360
    sunset = sunset if sunset is not None else 1080

    base_offset = datetime(today.year, 1, 15, 12, tzinfo=tz).utcoffset() or timedelta(0)

    today_offset = datetime(today.year, today.month, today.day, 12, tzinfo=tz).utcoffset() or timedelta(0)
    today_dst_offset = int((today_offset - base_offset).total_seconds() // 60)

    months = []
    for month in range(1, 13):
        sample_day = date(today.year, month, 15)
        m_sunrise, m_sunset = _sunrise_sunset(sample_day, latitude, longitude, tz)
        sample_offset = datetime(today.year, month, 15, 12, tzinfo=tz).utcoffset() or timedelta(0)
        dst_offset = int((sample_offset - base_offset).total_seconds() // 60)
        months.append(
            {
                "month": month,
                "sunrise": m_sunrise if m_sunrise is not None else sunrise,
                "sunset": m_sunset if m_sunset is not None else sunset,
                "dst_offset": dst_offset,
            }
        )

    current_month = next((entry for entry in months if entry["month"] == today.month), None)

    return {
        "today": {"sunrise": sunrise, "sunset": sunset, "dst_offset": today_dst_offset},
        "months": months,
        "current_month": current_month,
        "now_minutes": now_minutes,
        "now_epoch": now_epoch,
    }
def _fetch_lights() -> list[dict]:
    if not SUPERVISOR_TOKEN:
        return []
    url = "http://supervisor/core/api/states"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    lights = []
    for item in data:
        entity_id = item.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith("light."):
            continue
        attrs = item.get("attributes", {})
        if entity_id.startswith("light.svtlc_") or attrs.get("controller_id"):
            continue
        min_mireds = attrs.get("min_mireds")
        max_mireds = attrs.get("max_mireds")
        min_mireds = int(min_mireds) if isinstance(min_mireds, (int, float)) else None
        max_mireds = int(max_mireds) if isinstance(max_mireds, (int, float)) else None
        lights.append(
            {
                "entity_id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "min_mireds": min_mireds,
                "max_mireds": max_mireds,
            }
        )
    return lights


class SvtlcHandler(BaseHTTPRequestHandler):
    def _clean_path(self) -> str:
        raw_path = urlparse(self.path).path or "/"
        ingress_path = self.headers.get("X-Ingress-Path", "")
        if ingress_path and raw_path.startswith(ingress_path):
            stripped = raw_path[len(ingress_path):]
            return stripped if stripped.startswith("/") else f"/{stripped}"
        if raw_path.startswith("/api/hassio_ingress/"):
            parts = raw_path.split("/")
            if len(parts) > 4:
                stripped = "/" + "/".join(parts[4:])
                return stripped if stripped.startswith("/") else f"/{stripped}"
        return raw_path

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self._clean_path()
        if path == "/" or path == "/index.html":
            return self._send_file(os.path.join(WEB_ROOT, "index.html"), "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send_file(os.path.join(WEB_ROOT, "app.js"), "application/javascript")
        if path == "/style.css":
            return self._send_file(os.path.join(WEB_ROOT, "style.css"), "text/css")
        if path == "/api/config":
            return self._send_json(_read_config())
        if path == "/api/lights":
            return self._send_json({"lights": _fetch_lights()})
        if path == "/api/solar":
            return self._send_json(_build_solar_payload())
        if path == "/api/runtime":
            return self._send_json(_read_runtime())

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = self._clean_path()
        if path == "/api/runtime":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)

            if not isinstance(payload, dict):
                return self._send_json({"error": "invalid_payload"}, status=HTTPStatus.BAD_REQUEST)
            interval = payload.get("circadian_interval")
            wakeup_interval = payload.get("wakeup_interval")
            updates = {}
            if interval is not None:
                if not isinstance(interval, int) or interval < 1 or interval > 3600:
                    return self._send_json({"error": "invalid_payload"}, status=HTTPStatus.BAD_REQUEST)
                updates["circadian_interval"] = interval
            if wakeup_interval is not None:
                if not isinstance(wakeup_interval, int) or wakeup_interval < 1 or wakeup_interval > 3600:
                    return self._send_json({"error": "invalid_payload"}, status=HTTPStatus.BAD_REQUEST)
                updates["wakeup_interval"] = wakeup_interval
            if not updates:
                return self._send_json({"error": "invalid_payload"}, status=HTTPStatus.BAD_REQUEST)

            _write_runtime(updates)
            return self._send_json({"ok": True})

        if path != "/api/config":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)

        if not isinstance(payload, dict) or not isinstance(payload.get("controllers"), list):
            return self._send_json({"error": "invalid_payload"}, status=HTTPStatus.BAD_REQUEST)

        _write_config(payload)
        return self._send_json({"ok": True})

    def log_message(self, fmt, *args):
        return


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), SvtlcHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()




