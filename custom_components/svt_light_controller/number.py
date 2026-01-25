"""Number platform for SVT Light Controller limits."""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

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
    DOMAIN,
)
from .data import get_all_controllers

_LOGGER = logging.getLogger(__name__)


def _normalize_unique_id(raw_unique_id: str) -> str:
    return f"svtlc_{raw_unique_id.strip().lower().replace(' ', '_')}"

def _controller_slug(controller_id: str) -> str:
    return controller_id[len("svtlc_") :] if controller_id.startswith("svtlc_") else controller_id


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


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up SVT Light Controller numbers from YAML configuration."""
    manager = SvtLightControllerNumberManager(hass, async_add_entities)
    hass.data.setdefault(DOMAIN, {})["number_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up SVT Light Controller numbers from a config entry."""
    manager = hass.data.setdefault(DOMAIN, {}).get("number_manager")
    if not manager:
        manager = SvtLightControllerNumberManager(hass, async_add_entities)
        hass.data[DOMAIN]["number_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


class SvtLightControllerNumberManager:
    def __init__(self, hass: HomeAssistant, async_add_entities) -> None:
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._entities: dict[str, SvtLightControllerLimitNumber] = {}

    async def async_update(self, controllers: list[dict]) -> None:
        if "mqtt" not in self._hass.config.components:
            _LOGGER.error("MQTT integration is not loaded; configure MQTT before SVTLC.")
            return

        await mqtt.async_wait_for_mqtt_client(self._hass)

        next_ids: set[str] = set()
        new_entities: list[SvtLightControllerLimitNumber] = []

        for controller in controllers:
            try:
                name = controller[CONF_NAME]
                unique_id = controller[CONF_UNIQUE_ID]
                input_lights = controller[CONF_INPUT_LIGHTS]
            except KeyError:
                continue

            limits = controller.get(CONF_LIMITS) if isinstance(controller, dict) else None
            controller_id = _normalize_unique_id(unique_id)

            for key in (
                CONF_BRIGHTNESS_MIN_PCT,
                CONF_BRIGHTNESS_MAX_PCT,
                CONF_CT_MIN_KELVIN,
                CONF_CT_MAX_KELVIN,
                CONF_WEATHER_MIN_KELVIN,
            ):
                entity_id = f"{controller_id}_{key}"
                next_ids.add(entity_id)

                if entity_id in self._entities:
                    await self._entities[entity_id].async_apply_config(name, input_lights, limits)
                    continue

                entity = SvtLightControllerLimitNumber(
                    name=name,
                    unique_id=unique_id,
                    input_lights=input_lights,
                    key=key,
                    limits=limits,
                    hass=self._hass,
                )
                self._entities[entity_id] = entity
                new_entities.append(entity)

        if new_entities:
            self._async_add_entities(new_entities)

        for entity_id in list(self._entities.keys()):
            if entity_id in next_ids:
                continue
            entity = self._entities.pop(entity_id)
            await entity.async_remove()
            entity_registry = er.async_get(self._hass)
            if entity_registry.async_get(entity.entity_id):
                entity_registry.async_remove(entity.entity_id)


class SvtLightControllerLimitNumber(NumberEntity):
    """Writable number for per-controller limits."""

    _attr_should_poll = False
    _attr_mode = "slider"

    def __init__(
        self,
        name: str,
        unique_id: str,
        input_lights: list[str],
        key: str,
        limits: dict | None,
        hass: HomeAssistant,
    ) -> None:
        self._input_lights = input_lights
        self._hass = hass
        self._controller_id = _normalize_unique_id(unique_id)
        self._controller_slug = _controller_slug(self._controller_id)
        self._key = key
        self._device_name = f"SVTLC {name}"
        label = {
            CONF_BRIGHTNESS_MIN_PCT: "Min Brightness",
            CONF_BRIGHTNESS_MAX_PCT: "Max Brightness",
            CONF_CT_MIN_KELVIN: "Min Color Temp",
            CONF_CT_MAX_KELVIN: "Max Color Temp",
            CONF_WEATHER_MIN_KELVIN: "Weather Min Color Temp",
        }[key]
        icons = {
            CONF_BRIGHTNESS_MIN_PCT: "mdi:brightness-5",
            CONF_BRIGHTNESS_MAX_PCT: "mdi:brightness-7",
            CONF_CT_MIN_KELVIN: "mdi:thermometer-low",
            CONF_CT_MAX_KELVIN: "mdi:thermometer-high",
            CONF_WEATHER_MIN_KELVIN: "mdi:weather-cloudy",
        }
        self._attr_unique_id = f"{self._controller_id}_{key}"
        self._attr_object_id = f"svtlc_{key}_{self._controller_slug}"
        self._attr_name = label
        self._attr_icon = icons.get(key)
        self._topic_state = f"svtlc/{self._controller_id}/limits"
        self._topic_set = f"svtlc/{self._controller_id}/limits/set"
        self._unsub_mqtt = None

        if key in (CONF_BRIGHTNESS_MIN_PCT, CONF_BRIGHTNESS_MAX_PCT):
            self._attr_native_min_value = 1
            self._attr_native_max_value = 100
            self._attr_native_step = 1
        else:
            min_k, max_k = self._calc_ct_bounds()
            self._attr_native_min_value = min_k
            self._attr_native_max_value = max_k
            self._attr_native_step = 10

        self._attr_native_value = self._default_value(limits)

    def _default_value(self, limits: dict | None) -> int | None:
        if isinstance(limits, dict) and isinstance(limits.get(self._key), (int, float)):
            return int(round(limits[self._key]))
        if self._key == CONF_BRIGHTNESS_MIN_PCT:
            return 1
        if self._key == CONF_BRIGHTNESS_MAX_PCT:
            return 100
        if self._key == CONF_CT_MIN_KELVIN:
            return 2000
        if self._key == CONF_CT_MAX_KELVIN:
            return 6500
        if self._key == CONF_WEATHER_MIN_KELVIN:
            if isinstance(limits, dict) and isinstance(limits.get(CONF_CT_MIN_KELVIN), (int, float)):
                return int(round(limits[CONF_CT_MIN_KELVIN]))
            return 2200
        return None

    async def async_apply_config(self, name: str, input_lights: list[str], limits: dict | None) -> None:
        if name:
            label = {
                CONF_BRIGHTNESS_MIN_PCT: "Min Brightness",
                CONF_BRIGHTNESS_MAX_PCT: "Max Brightness",
                CONF_CT_MIN_KELVIN: "Min Color Temp",
                CONF_CT_MAX_KELVIN: "Max Color Temp",
                CONF_WEATHER_MIN_KELVIN: "Weather Min Color Temp",
            }[self._key]
            self._attr_name = label
        self._device_name = f"SVTLC {name}"
        self._input_lights = input_lights
        if self._key in (CONF_CT_MIN_KELVIN, CONF_CT_MAX_KELVIN):
            min_k, max_k = self._calc_ct_bounds()
            self._attr_native_min_value = min_k
            self._attr_native_max_value = max_k
        self._attr_native_value = self._default_value(limits)
        self._attr_native_value = self._clamp_value(self._attr_native_value)
        self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._controller_id)},
            "name": self._device_name,
            "manufacturer": "SVT",
            "model": "SVT Light Controller",
        }

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "input_lights": self._input_lights,
            "controller_id": self._controller_id,
            "mqtt_topic_state": self._topic_state,
            "mqtt_topic_set": self._topic_set,
        }

    async def async_added_to_hass(self) -> None:
        await self._ensure_device_link()
        self._ensure_entity_id()
        if self._key in (CONF_CT_MIN_KELVIN, CONF_CT_MAX_KELVIN):
            min_k, max_k = self._calc_ct_bounds()
            self._attr_native_min_value = min_k
            self._attr_native_max_value = max_k
            self._attr_native_value = self._clamp_value(self._attr_native_value)
        self._unsub_mqtt = await mqtt.async_subscribe(
            self._hass,
            self._topic_state,
            self._handle_mqtt_state,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    async def async_set_native_value(self, value: float) -> None:
        payload_value = self._clamp_value(int(round(value)))
        payload = {self._key: payload_value}
        await mqtt.async_publish(
            self._hass,
            self._topic_set,
            json.dumps(payload),
            qos=0,
            retain=False,
        )
        self._attr_native_value = payload_value
        self.async_write_ha_state()

    @callback
    def _handle_mqtt_state(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if not payload:
            return
        value = payload.get(self._key)
        if isinstance(value, (int, float)):
            self._attr_native_value = self._clamp_value(int(round(value)))
        self.async_write_ha_state()

    def _clamp_value(self, value: int | None) -> int | None:
        if value is None:
            return None
        min_value = self._attr_native_min_value
        max_value = self._attr_native_max_value
        if min_value is None or max_value is None:
            return int(value)
        return int(max(min_value, min(max_value, value)))

    def _calc_ct_bounds(self) -> tuple[int, int]:
        min_values = []
        max_values = []
        for entity_id in self._input_lights:
            state = self._hass.states.get(entity_id)
            if not state:
                continue
            attrs = state.attributes or {}
            min_mireds = attrs.get("min_mireds")
            max_mireds = attrs.get("max_mireds")
            if not isinstance(min_mireds, (int, float)) or not isinstance(max_mireds, (int, float)):
                continue
            if min_mireds <= 0 or max_mireds <= 0:
                continue
            min_kelvin = int(round(1000000 / max_mireds))
            max_kelvin = int(round(1000000 / min_mireds))
            min_values.append(min_kelvin)
            max_values.append(max_kelvin)

        if not min_values or not max_values:
            return 1500, 8000

        min_k = max(min_values)
        max_k = min(max_values)
        if min_k > max_k:
            min_k, max_k = max_k, min_k
        min_k = max(1500, min(8000, min_k))
        max_k = max(1500, min(8000, max_k))
        if min_k > max_k:
            min_k, max_k = 1500, 8000
        return min_k, max_k

    async def _ensure_device_link(self) -> None:
        try:
            entries = self._hass.config_entries.async_entries(DOMAIN)
            if not entries:
                return
            config_entry_id = entries[0].entry_id

            device_registry = dr.async_get(self._hass)
            device = device_registry.async_get_or_create(
                config_entry_id=config_entry_id,
                identifiers={(DOMAIN, self._controller_id)},
                name=self._device_name,
                manufacturer="SVT",
                model="SVT Light Controller",
            )

            entity_registry = er.async_get(self._hass)
            entity = entity_registry.async_get(self.entity_id)
            if entity and entity.device_id != device.id:
                entity_registry.async_update_entity(self.entity_id, device_id=device.id)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to link SVTLC device")

    def _ensure_entity_id(self) -> None:
        try:
            entity_registry = er.async_get(self._hass)
            desired = f"number.{self._attr_object_id}"
            if self.entity_id != desired and desired not in entity_registry.entities:
                entity_registry.async_update_entity(self.entity_id, new_entity_id=desired)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to update SVTLC number entity_id")
