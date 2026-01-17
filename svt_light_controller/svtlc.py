"""SVT Light Controller add-on MQTT bridge."""

import json
import logging
import math
import statistics
import time
from collections import Counter

import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
TOPIC_INPUTS = "svtlc/+/inputs"
TOPIC_EVENTS = "svtlc/+/event"


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

    for value in states.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("state", "")).strip().lower() != "on":
            continue
        mode = value.get("color_mode")
        if isinstance(mode, str) and mode in color_group:
            has_color_input = True

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


def _publish_input_command(
    client,
    controller_id: str,
    command: str,
    targets: list[str],
    brightness: int | None = None,
    color_payload: dict | None = None,
    effect: str | None = None,
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


def _select_color_mode(modes: list[str], color_payload: dict) -> str | None:
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

    last_output: dict[str, dict] = {}
    last_inputs: dict[str, dict] = {}

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT connect failed with code %s", rc)
            return
        logger.info("Connected to MQTT at %s:%s", host, port)
        client.subscribe(TOPIC_INPUTS)
        client.subscribe(TOPIC_EVENTS)

    def on_message(client, userdata, msg):
        topic = msg.topic
        parts = topic.split("/")
        if len(parts) < 3:
            return

        controller_id = parts[1]
        suffix = parts[2]

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
                _publish_input_command(client, controller_id, "turn_off_inputs", _targets_on(states))
            elif event == "manual_on":
                targets = _targets_all(states)
                _publish_input_command(client, controller_id, "turn_on_inputs", targets)
                if isinstance(brightness, int):
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_brightness_inputs",
                        targets,
                        brightness,
                    )
                if color_payload:
                    color_targets = _targets_with_mode(states, color_mode, only_on=False)
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_color_inputs",
                        color_targets,
                        color_payload=color_payload,
                    )
                if isinstance(effect, str) and effect:
                    _publish_input_command(
                        client,
                        controller_id,
                        "set_effect_inputs",
                        targets,
                        effect=effect,
                    )
            elif event == "manual_brightness" and isinstance(brightness, int):
                _publish_input_command(
                    client,
                    controller_id,
                    "set_brightness_inputs",
                    _targets_on(states),
                    brightness,
                )
            elif event == "manual_color" and color_payload:
                color_targets = _targets_with_mode(states, color_mode, only_on=True)
                _publish_input_command(
                    client,
                    controller_id,
                    "set_color_inputs",
                    color_targets,
                    color_payload=color_payload,
                )
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
        states = payload.get("states", {}) if isinstance(payload, dict) else {}
        last_inputs[controller_id] = states

        output_state, output_brightness = _state_from_inputs(states)
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

    if username and password:
        client.username_pw_set(username, password)

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            client.connect(host, port, 60)
            client.loop_forever()
        except Exception as exc:  # noqa: BLE001
            logger.error("MQTT error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()