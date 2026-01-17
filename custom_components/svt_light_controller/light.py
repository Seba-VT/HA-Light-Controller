"""Light platform for SVT Light Controller."""

from __future__ import annotations

import json
import logging

from homeassistant.components import light as light_platform
from homeassistant.components import mqtt

ATTR_BRIGHTNESS = light_platform.ATTR_BRIGHTNESS
ATTR_COLOR_MODE = getattr(light_platform, "ATTR_COLOR_MODE", "color_mode")
ATTR_COLOR_TEMP = light_platform.ATTR_COLOR_TEMP
ATTR_COLOR_TEMP_KELVIN = getattr(light_platform, "ATTR_COLOR_TEMP_KELVIN", "color_temp_kelvin")
ATTR_HS_COLOR = light_platform.ATTR_HS_COLOR
ATTR_RGB_COLOR = light_platform.ATTR_RGB_COLOR
ATTR_EFFECT = light_platform.ATTR_EFFECT
ATTR_RGBW_COLOR = getattr(light_platform, "ATTR_RGBW_COLOR", None)
ATTR_RGBWW_COLOR = getattr(light_platform, "ATTR_RGBWW_COLOR", None)
ATTR_XY_COLOR = light_platform.ATTR_XY_COLOR
LightEntity = light_platform.LightEntity
ColorMode = light_platform.ColorMode
try:
    FEATURE_NONE = light_platform.LightEntityFeature(0)
    EFFECT_FEATURE = light_platform.LightEntityFeature.EFFECT
except AttributeError:
    FEATURE_NONE = 0
    EFFECT_FEATURE = getattr(light_platform, "SUPPORT_EFFECT", 0)

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_CONTROLLERS,
    CONF_INPUT_LIGHTS,
    CONF_NAME,
    CONF_UNIQUE_ID,
    DOMAIN,
    SVTLC_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

PREFERRED_COLOR_MODES = (
    ColorMode.COLOR_TEMP,
    ColorMode.HS,
    ColorMode.RGB,
    ColorMode.RGBW,
    ColorMode.RGBWW,
    ColorMode.XY,
    ColorMode.WHITE,
    ColorMode.BRIGHTNESS,
    ColorMode.ONOFF,
)


def _normalize_unique_id(raw_unique_id: str) -> str:
    return f"svtlc_{raw_unique_id.strip().lower().replace(' ', '_')}"


def _parse_json_payload(payload) -> dict | None:
    if isinstance(payload, (bytes, bytearray)):
        text = payload.decode("utf-8", "ignore")
    else:
        text = str(payload)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    return data if isinstance(data, dict) else None


def _coerce_color_modes(modes) -> set[ColorMode]:
    supported: set[ColorMode] = set()
    if not isinstance(modes, (list, tuple, set)):
        return supported

    for mode in modes:
        if not isinstance(mode, str):
            continue
        try:
            supported.add(ColorMode(mode))
        except ValueError:
            continue

    return supported


def _select_color_mode(supported: set[ColorMode]) -> ColorMode | None:
    for mode in PREFERRED_COLOR_MODES:
        if mode in supported:
            return mode
    return None


def _color_payload_from_kwargs(kwargs: dict) -> tuple[str | None, dict]:
    color_payload: dict = {}
    color_mode = kwargs.get(ATTR_COLOR_MODE)
    if isinstance(color_mode, str):
        color_payload["color_mode"] = color_mode

    if ATTR_HS_COLOR in kwargs:
        color_payload["hs_color"] = kwargs[ATTR_HS_COLOR]
        color_mode = color_mode or "hs"
    elif ATTR_RGB_COLOR in kwargs:
        color_payload["rgb_color"] = kwargs[ATTR_RGB_COLOR]
        color_mode = color_mode or "rgb"
    elif ATTR_RGBW_COLOR and ATTR_RGBW_COLOR in kwargs:
        color_payload["rgbw_color"] = kwargs[ATTR_RGBW_COLOR]
        color_mode = color_mode or "rgbw"
    elif ATTR_RGBWW_COLOR and ATTR_RGBWW_COLOR in kwargs:
        color_payload["rgbww_color"] = kwargs[ATTR_RGBWW_COLOR]
        color_mode = color_mode or "rgbww"
    elif ATTR_XY_COLOR in kwargs:
        color_payload["xy_color"] = kwargs[ATTR_XY_COLOR]
        color_mode = color_mode or "xy"
    elif ATTR_COLOR_TEMP in kwargs:
        color_payload["color_temp"] = kwargs[ATTR_COLOR_TEMP]
        color_mode = color_mode or "color_temp"
    elif ATTR_COLOR_TEMP_KELVIN in kwargs:
        color_payload["color_temp_kelvin"] = kwargs[ATTR_COLOR_TEMP_KELVIN]
        color_mode = color_mode or "color_temp"

    if color_mode:
        color_payload["color_mode"] = color_mode

    return color_mode if isinstance(color_mode, str) else None, color_payload


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up SVT Light Controller lights from YAML configuration."""
    domain_config = hass.data.get(DOMAIN)
    if not domain_config:
        return

    if "mqtt" not in hass.config.components:
        _LOGGER.error("MQTT integration is not loaded; configure MQTT before SVTLC.")
        return

    await mqtt.async_wait_for_mqtt_client(hass)

    controllers = domain_config.get(CONF_CONTROLLERS, [])
    entities: list[LightEntity] = []

    for controller in controllers:
        entities.append(
            SvtLightControllerLight(
                name=controller[CONF_NAME],
                unique_id=controller[CONF_UNIQUE_ID],
                input_lights=controller[CONF_INPUT_LIGHTS],
                hass=hass,
            )
        )

    async_add_entities(entities)


class SvtLightControllerLight(LightEntity):
    """Virtual light representing a controller output."""

    _attr_supported_features = FEATURE_NONE
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_should_poll = False

    def __init__(self, name: str, unique_id: str, input_lights: list[str], hass: HomeAssistant) -> None:
        self._input_lights = input_lights
        self._hass = hass
        self._attr_name = f"{SVTLC_PREFIX} {name}"
        self._controller_id = _normalize_unique_id(unique_id)
        self._attr_unique_id = self._controller_id
        self._topic_base = f"svtlc/{self._controller_id}"
        self._topic_inputs = f"{self._topic_base}/inputs"
        self._topic_output = f"{self._topic_base}/output"
        self._topic_event = f"{self._topic_base}/event"
        self._topic_command = f"{self._topic_base}/command"
        self._unsub_tracker = None
        self._unsub_mqtt_output = None
        self._unsub_mqtt_command = None
        self._state = None
        self._attr_brightness = None
        self._attr_min_mireds = None
        self._attr_max_mireds = None
        self._attr_effect_list = []
        self._attr_effect = None

    @property
    def is_on(self) -> bool | None:
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "input_lights": self._input_lights,
            "controller_id": self._controller_id,
            "mqtt_topic_output": self._topic_output,
            "mqtt_topic_command": self._topic_command,
        }

    async def async_added_to_hass(self) -> None:
        self._unsub_mqtt_output = await mqtt.async_subscribe(
            self._hass,
            self._topic_output,
            self._handle_mqtt_output,
        )
        self._unsub_mqtt_command = await mqtt.async_subscribe(
            self._hass,
            self._topic_command,
            self._handle_mqtt_command,
        )

        @callback
        def _handle_state_change(event) -> None:
            self._hass.async_create_task(self._publish_inputs())

        self._unsub_tracker = async_track_state_change_event(
            self._hass,
            self._input_lights,
            _handle_state_change,
        )

        await self._publish_inputs()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_tracker:
            self._unsub_tracker()
            self._unsub_tracker = None

        if self._unsub_mqtt_output:
            self._unsub_mqtt_output()
            self._unsub_mqtt_output = None

        if self._unsub_mqtt_command:
            self._unsub_mqtt_command()
            self._unsub_mqtt_command = None

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        effect = kwargs.get(ATTR_EFFECT)
        color_mode, color_payload = _color_payload_from_kwargs(kwargs)

        if effect is not None and self._state:
            event = "manual_effect"
        elif color_payload and self._state:
            event = "manual_color"
        elif brightness is not None and self._state:
            event = "manual_brightness"
        else:
            event = "manual_on"

        payload = {"event": event}
        if brightness is not None:
            payload["brightness"] = brightness
        if effect is not None:
            payload["effect"] = effect
        payload.update(color_payload)

        await mqtt.async_publish(
            self._hass,
            self._topic_event,
            json.dumps(payload),
            qos=0,
            retain=False,
        )
        self._state = True
        if brightness is not None:
            self._attr_brightness = brightness
        if color_mode and color_mode in self._attr_supported_color_modes:
            self._attr_color_mode = ColorMode(color_mode)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await mqtt.async_publish(
            self._hass,
            self._topic_event,
            json.dumps({"event": "manual_off"}),
            qos=0,
            retain=False,
        )
        self._state = False
        self._attr_brightness = None
        self.async_write_ha_state()

    async def _publish_inputs(self) -> None:
        states = {}
        for entity_id in self._input_lights:
            state = self._hass.states.get(entity_id)
            if state is None:
                states[entity_id] = {
                    "state": "unknown",
                    "brightness": None,
                    "supported_color_modes": None,
                    "min_mireds": None,
                    "max_mireds": None,
                }
                continue

            attrs = state.attributes
            supported_color_modes = attrs.get("supported_color_modes")
            if isinstance(supported_color_modes, (list, tuple, set)):
                supported_color_modes = list(supported_color_modes)
            else:
                supported_color_modes = None

            brightness = attrs.get(ATTR_BRIGHTNESS) if state.state == "on" else None

            states[entity_id] = {
                "state": state.state,
                "brightness": brightness,
                "supported_color_modes": supported_color_modes,
                "min_mireds": attrs.get("min_mireds"),
                "max_mireds": attrs.get("max_mireds"),
                "effect_list": attrs.get("effect_list"),
                "effect": attrs.get(ATTR_EFFECT),
                "color_mode": attrs.get("color_mode"),
                "hs_color": attrs.get(ATTR_HS_COLOR),
                "rgb_color": attrs.get(ATTR_RGB_COLOR),
                "rgbw_color": attrs.get(ATTR_RGBW_COLOR) if ATTR_RGBW_COLOR else None,
                "rgbww_color": attrs.get(ATTR_RGBWW_COLOR) if ATTR_RGBWW_COLOR else None,
                "xy_color": attrs.get(ATTR_XY_COLOR),
                "color_temp": attrs.get(ATTR_COLOR_TEMP),
                "color_temp_kelvin": attrs.get(ATTR_COLOR_TEMP_KELVIN),
            }

        payload = json.dumps({"states": states})
        await mqtt.async_publish(
            self._hass,
            self._topic_inputs,
            payload,
            qos=0,
            retain=True,
        )

    @callback
    def _handle_mqtt_output(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if payload is not None:
            state = str(payload.get("state", "")).strip().lower()
            brightness = payload.get("brightness")

            if state in {"on", "true", "1", "yes"}:
                self._state = True
            elif state in {"off", "false", "0", "no"}:
                self._state = False
            else:
                self._state = None

            if self._state:
                self._attr_brightness = brightness if isinstance(brightness, int) else self._attr_brightness
            else:
                self._attr_brightness = None

            modes = payload.get("supported_color_modes")
            supported_modes = _coerce_color_modes(modes)
            if supported_modes:
                self._attr_supported_color_modes = supported_modes
                if self._attr_color_mode not in supported_modes:
                    selected = _select_color_mode(supported_modes)
                    if selected:
                        self._attr_color_mode = selected

            min_mireds = payload.get("min_mireds")
            max_mireds = payload.get("max_mireds")
            if isinstance(min_mireds, int):
                self._attr_min_mireds = min_mireds
            if isinstance(max_mireds, int):
                self._attr_max_mireds = max_mireds

            effect_list = payload.get("effect_list")
            if isinstance(effect_list, list):
                self._attr_effect_list = effect_list
                self._attr_supported_features = FEATURE_NONE | EFFECT_FEATURE
            else:
                self._attr_effect_list = []
                self._attr_supported_features = FEATURE_NONE

            effect = payload.get("effect")
            if effect is not None:
                self._attr_effect = effect
            else:
                self._attr_effect = None

            hs_color = payload.get("hs_color")
            if isinstance(hs_color, (list, tuple)) and len(hs_color) == 2:
                self._attr_hs_color = tuple(hs_color)

            rgb_color = payload.get("rgb_color")
            if isinstance(rgb_color, (list, tuple)) and len(rgb_color) == 3:
                self._attr_rgb_color = tuple(rgb_color)

            rgbw_color = payload.get("rgbw_color")
            if isinstance(rgbw_color, (list, tuple)) and len(rgbw_color) == 4:
                self._attr_rgbw_color = tuple(rgbw_color)

            rgbww_color = payload.get("rgbww_color")
            if isinstance(rgbww_color, (list, tuple)) and len(rgbww_color) == 5:
                self._attr_rgbww_color = tuple(rgbww_color)

            xy_color = payload.get("xy_color")
            if isinstance(xy_color, (list, tuple)) and len(xy_color) == 2:
                self._attr_xy_color = tuple(xy_color)

            color_temp = payload.get("color_temp")
            if isinstance(color_temp, (int, float)):
                self._attr_color_temp = int(color_temp)

            color_temp_kelvin = payload.get("color_temp_kelvin")
            if isinstance(color_temp_kelvin, (int, float)):
                self._attr_color_temp_kelvin = int(color_temp_kelvin)

            if payload.get("color_mode"):
                try:
                    self._attr_color_mode = ColorMode(payload["color_mode"])
                except ValueError:
                    pass

            self.async_write_ha_state()
            return

        payload_text = msg.payload
        if isinstance(payload_text, (bytes, bytearray)):
            payload_text = payload_text.decode("utf-8", "ignore")
        else:
            payload_text = str(payload_text)

        normalized = payload_text.strip().lower()
        if normalized in {"on", "true", "1", "yes"}:
            self._state = True
        elif normalized in {"off", "false", "0", "no"}:
            self._state = False
        else:
            self._state = None

        if self._state is False:
            self._attr_brightness = None

        self.async_write_ha_state()

    @callback
    def _handle_mqtt_command(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if payload is not None:
            command = str(payload.get("command", "")).strip().lower()
            targets = payload.get("targets")
            brightness = payload.get("brightness")
            effect = payload.get("effect")
            color_mode = payload.get("color_mode")
            hs_color = payload.get("hs_color")
            rgb_color = payload.get("rgb_color")
            rgbw_color = payload.get("rgbw_color")
            rgbww_color = payload.get("rgbww_color")
            xy_color = payload.get("xy_color")
            color_temp = payload.get("color_temp")
            color_temp_kelvin = payload.get("color_temp_kelvin")
        else:
            if isinstance(msg.payload, (bytes, bytearray)):
                payload_text = msg.payload.decode("utf-8", "ignore")
            else:
                payload_text = str(msg.payload)
            command = payload_text.strip().lower()
            targets = None
            brightness = None
            effect = None
            color_mode = None
            hs_color = None
            rgb_color = None
            rgbw_color = None
            rgbww_color = None
            xy_color = None
            color_temp = None
            color_temp_kelvin = None

        if command not in {
            "turn_off_inputs",
            "turn_on_inputs",
            "set_brightness_inputs",
            "set_color_inputs",
            "set_effect_inputs",
        }:
            return

        if not isinstance(targets, list) or not targets:
            _LOGGER.debug("No targets provided for %s", self.entity_id)
            return

        if command == "set_brightness_inputs":
            if not isinstance(brightness, int):
                _LOGGER.debug("Brightness missing for %s", self.entity_id)
                return
            service = "turn_on"
            data = {"entity_id": targets, ATTR_BRIGHTNESS: brightness}
        elif command == "set_color_inputs":
            service = "turn_on"
            data = {"entity_id": targets}
            if isinstance(brightness, int):
                data[ATTR_BRIGHTNESS] = brightness
            if rgbw_color is not None and ATTR_RGBW_COLOR:
                data[ATTR_RGBW_COLOR] = rgbw_color
            elif rgbww_color is not None and ATTR_RGBWW_COLOR:
                data[ATTR_RGBWW_COLOR] = rgbww_color
            elif rgb_color is not None:
                data[ATTR_RGB_COLOR] = rgb_color
            elif hs_color is not None:
                data[ATTR_HS_COLOR] = hs_color
            elif xy_color is not None:
                data[ATTR_XY_COLOR] = xy_color
            elif color_temp is not None:
                data[ATTR_COLOR_TEMP] = color_temp
            elif color_temp_kelvin is not None:
                data[ATTR_COLOR_TEMP_KELVIN] = color_temp_kelvin
        elif command == "set_effect_inputs":
            if not isinstance(effect, str) or not effect:
                _LOGGER.debug("Effect missing for %s", self.entity_id)
                return
            service = "turn_on"
            data = {"entity_id": targets, ATTR_EFFECT: effect}
        else:
            service = "turn_on" if command == "turn_on_inputs" else "turn_off"
            data = {"entity_id": targets}

        self._hass.async_create_task(
            self._hass.services.async_call(
                "light",
                service,
                data,
                blocking=False,
            )
        )