"""Sensor platform for SVT Light Controller circadian targets."""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_INPUT_LIGHTS, CONF_NAME, CONF_UNIQUE_ID, DOMAIN
from .data import get_all_controllers

_LOGGER = logging.getLogger(__name__)


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


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up SVT Light Controller sensors from YAML configuration."""
    manager = SvtLightControllerSensorManager(hass, async_add_entities)
    hass.data.setdefault(DOMAIN, {})["sensor_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up SVT Light Controller sensors from a config entry."""
    manager = hass.data.setdefault(DOMAIN, {}).get("sensor_manager")
    if not manager:
        manager = SvtLightControllerSensorManager(hass, async_add_entities)
        hass.data[DOMAIN]["sensor_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


class SvtLightControllerSensorManager:
    def __init__(self, hass: HomeAssistant, async_add_entities) -> None:
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._entities: dict[str, SensorEntity] = {}

    async def async_update(self, controllers: list[dict]) -> None:
        if "mqtt" not in self._hass.config.components:
            _LOGGER.error("MQTT integration is not loaded; configure MQTT before SVTLC.")
            return

        await mqtt.async_wait_for_mqtt_client(self._hass)

        next_ids: set[str] = set()
        new_entities: list[SensorEntity] = []

        for controller in controllers:
            try:
                name = controller[CONF_NAME]
                unique_id = controller[CONF_UNIQUE_ID]
                input_lights = controller[CONF_INPUT_LIGHTS]
            except KeyError:
                continue

            controller_id = _normalize_unique_id(unique_id)

            for kind in ("brightness", "color_temp"):
                variants = ("target", "raw") if kind == "brightness" else ("target", "weather", "raw")
                for variant in variants:
                    entity_id = f"{controller_id}_{kind}_{variant}"
                    next_ids.add(entity_id)

                    if entity_id in self._entities:
                        await self._entities[entity_id].async_apply_config(name, input_lights)
                        continue

                    entity = SvtLightControllerCircadianSensor(
                        name=name,
                        unique_id=unique_id,
                        input_lights=input_lights,
                        kind=kind,
                        variant=variant,
                        hass=self._hass,
                    )
                    self._entities[entity_id] = entity
                    new_entities.append(entity)

            weather_entity_id = f"{controller_id}_weather_reduction"
            next_ids.add(weather_entity_id)
            if weather_entity_id in self._entities:
                await self._entities[weather_entity_id].async_apply_config(name, input_lights)
            else:
                entity = SvtLightControllerWeatherReductionSensor(
                    name=name,
                    unique_id=unique_id,
                    input_lights=input_lights,
                    hass=self._hass,
                )
                self._entities[weather_entity_id] = entity
                new_entities.append(entity)

        if new_entities:
            self._async_add_entities(new_entities)

        for entity_id in list(self._entities.keys()):
            if entity_id in next_ids:
                continue
            entity = self._entities.pop(entity_id)
            await entity.async_remove()


class SvtLightControllerCircadianSensor(SensorEntity):
    """Read-only sensor entity for circadian targets."""

    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        unique_id: str,
        input_lights: list[str],
        kind: str,
        variant: str,
        hass: HomeAssistant,
    ) -> None:
        self._input_lights = input_lights
        self._hass = hass
        self._controller_id = _normalize_unique_id(unique_id)
        self._kind = kind
        self._variant = variant
        self._device_name = f"SVTLC {name}"
        self._attr_unique_id = f"{self._controller_id}_circadian_{kind}_{variant}"
        label = "Brightness" if kind == "brightness" else "Color Temp"
        if variant == "target":
            suffix = "Smoothed Target"
        elif variant == "weather":
            suffix = "Weather Target"
        else:
            suffix = "Raw Target"
        self._attr_name = f"Circadian {label} {suffix}"
        self._attr_icon = self._resolve_icon()
        self._topic_state = f"svtlc/{self._controller_id}/circadian"
        self._unsub_mqtt = None
        self._attr_native_value = None
        if kind == "brightness":
            self._attr_native_unit_of_measurement = PERCENTAGE
        else:
            self._attr_native_unit_of_measurement = UnitOfTemperature.KELVIN

    async def async_apply_config(self, name: str, input_lights: list[str]) -> None:
        if name:
            label = "Brightness" if self._kind == "brightness" else "Color Temp"
            if self._variant == "target":
                suffix = "Smoothed Target"
            elif self._variant == "weather":
                suffix = "Weather Target"
            else:
                suffix = "Raw Target"
            self._attr_name = f"Circadian {label} {suffix}"
        self._device_name = f"SVTLC {name}"
        self._input_lights = input_lights
        self.async_write_ha_state()

    def _resolve_icon(self) -> str:
        if self._kind == "brightness":
            if self._variant == "target":
                return "mdi:brightness-6"
            if self._variant == "weather":
                return "mdi:weather-partly-cloudy"
            return "mdi:brightness-5"
        if self._variant == "target":
            return "mdi:thermometer"
        if self._variant == "weather":
            return "mdi:weather-cloudy"
        return "mdi:thermometer-lines"

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
        }

    async def async_added_to_hass(self) -> None:
        await self._ensure_device_link()
        self._unsub_mqtt = await mqtt.async_subscribe(
            self._hass,
            self._topic_state,
            self._handle_mqtt_state,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    @callback
    def _handle_mqtt_state(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if not payload:
            return
        if self._kind == "brightness":
            if self._variant == "target":
                key = "brightness_target"
            elif self._variant == "weather":
                key = "brightness_target_weather"
            else:
                key = "brightness_target_raw"
        else:
            if self._variant == "target":
                key = "color_temp_target"
            elif self._variant == "weather":
                key = "color_temp_target_weather"
            else:
                key = "color_temp_target_raw"
        value = payload.get(key)
        if isinstance(value, (int, float)):
            if self._kind == "brightness":
                self._attr_native_value = int(round((float(value) / 255.0) * 100.0))
            else:
                self._attr_native_value = int(round(float(value)))
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

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


class SvtLightControllerWeatherReductionSensor(SensorEntity):
    """Read-only sensor entity for weather reduction percent."""

    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        unique_id: str,
        input_lights: list[str],
        hass: HomeAssistant,
    ) -> None:
        self._input_lights = input_lights
        self._hass = hass
        self._controller_id = _normalize_unique_id(unique_id)
        self._device_name = f"SVTLC {name}"
        self._attr_unique_id = f"{self._controller_id}_circadian_weather_reduction"
        self._attr_name = "Weather Reduction"
        self._attr_icon = "mdi:weather-partly-cloudy"
        self._topic_state = f"svtlc/{self._controller_id}/circadian"
        self._unsub_mqtt = None
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = PERCENTAGE

    async def async_apply_config(self, name: str, input_lights: list[str]) -> None:
        self._device_name = f"SVTLC {name}"
        self._input_lights = input_lights
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
        }

    async def async_added_to_hass(self) -> None:
        await self._ensure_device_link()
        self._unsub_mqtt = await mqtt.async_subscribe(
            self._hass,
            self._topic_state,
            self._handle_mqtt_state,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    @callback
    def _handle_mqtt_state(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if not payload:
            return
        value = payload.get("weather_reduction_pct")
        if isinstance(value, (int, float)):
            self._attr_native_value = int(round(float(value)))
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

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
