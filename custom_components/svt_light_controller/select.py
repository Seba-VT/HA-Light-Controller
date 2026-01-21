"""Select platform for SVT Light Controller mode."""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_INPUT_LIGHTS, CONF_NAME, CONF_UNIQUE_ID, DOMAIN
from .data import get_all_controllers

_LOGGER = logging.getLogger(__name__)

MODE_OPTIONS = ["Circadian", "Manual", "Away", "Sleep", "WakeUp"]


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
    """Set up SVT Light Controller selects from YAML configuration."""
    manager = SvtLightControllerSelectManager(hass, async_add_entities)
    hass.data.setdefault(DOMAIN, {})["select_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up SVT Light Controller selects from a config entry."""
    manager = hass.data.setdefault(DOMAIN, {}).get("select_manager")
    if not manager:
        manager = SvtLightControllerSelectManager(hass, async_add_entities)
        hass.data[DOMAIN]["select_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


class SvtLightControllerSelectManager:
    def __init__(self, hass: HomeAssistant, async_add_entities) -> None:
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._entities: dict[str, SvtLightControllerModeSelect] = {}

    async def async_update(self, controllers: list[dict]) -> None:
        if "mqtt" not in self._hass.config.components:
            _LOGGER.error("MQTT integration is not loaded; configure MQTT before SVTLC.")
            return

        await mqtt.async_wait_for_mqtt_client(self._hass)

        next_ids: set[str] = set()
        new_entities: list[SvtLightControllerModeSelect] = []

        for controller in controllers:
            try:
                name = controller[CONF_NAME]
                unique_id = controller[CONF_UNIQUE_ID]
                input_lights = controller[CONF_INPUT_LIGHTS]
            except KeyError:
                continue

            controller_id = _normalize_unique_id(unique_id)
            entity_id = f"{controller_id}_mode"
            next_ids.add(entity_id)

            if entity_id in self._entities:
                await self._entities[entity_id].async_apply_config(name, input_lights)
                continue

            entity = SvtLightControllerModeSelect(
                name=name,
                unique_id=unique_id,
                input_lights=input_lights,
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


class SvtLightControllerModeSelect(SelectEntity):
    """Select entity for controller mode."""

    _attr_should_poll = False
    _attr_options = MODE_OPTIONS

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
        self._attr_unique_id = f"{self._controller_id}_mode"
        self._attr_name = "Mode"
        self._attr_icon = "mdi:circle-slice-8"
        self._topic_state = f"svtlc/{self._controller_id}/mode"
        self._topic_set = f"svtlc/{self._controller_id}/mode/set"
        self._unsub_mqtt = None
        self._attr_current_option = "Circadian"

    async def async_apply_config(self, name: str, input_lights: list[str]) -> None:
        if name:
            self._attr_name = "Mode"
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
            "mqtt_topic_set": self._topic_set,
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

    async def async_select_option(self, option: str) -> None:
        if option not in MODE_OPTIONS:
            return
        payload = {"mode": option}
        await mqtt.async_publish(
            self._hass,
            self._topic_set,
            json.dumps(payload),
            qos=0,
            retain=False,
        )
        self._attr_current_option = option
        self.async_write_ha_state()

    @callback
    def _handle_mqtt_state(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if not payload:
            return
        value = payload.get("mode")
        if isinstance(value, str) and value in MODE_OPTIONS:
            self._attr_current_option = value
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
