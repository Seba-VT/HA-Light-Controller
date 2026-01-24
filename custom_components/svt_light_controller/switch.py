"""Switch platform for SVT Light Controller circadian toggles."""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.switch import SwitchEntity
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
    """Set up SVT Light Controller switches from YAML configuration."""
    manager = SvtLightControllerSwitchManager(hass, async_add_entities)
    hass.data.setdefault(DOMAIN, {})["switch_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up SVT Light Controller switches from a config entry."""
    manager = hass.data.setdefault(DOMAIN, {}).get("switch_manager")
    if not manager:
        manager = SvtLightControllerSwitchManager(hass, async_add_entities)
        hass.data[DOMAIN]["switch_manager"] = manager

    await manager.async_update(get_all_controllers(hass))


class SvtLightControllerSwitchManager:
    def __init__(self, hass: HomeAssistant, async_add_entities) -> None:
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._entities: dict[str, SvtLightControllerCircadianSwitch] = {}

    async def async_update(self, controllers: list[dict]) -> None:
        if "mqtt" not in self._hass.config.components:
            _LOGGER.error("MQTT integration is not loaded; configure MQTT before SVTLC.")
            return

        await mqtt.async_wait_for_mqtt_client(self._hass)

        next_ids: set[str] = set()
        new_entities: list[SvtLightControllerCircadianSwitch] = []

        for controller in controllers:
            try:
                name = controller[CONF_NAME]
                unique_id = controller[CONF_UNIQUE_ID]
                input_lights = controller[CONF_INPUT_LIGHTS]
            except KeyError:
                continue

            circadian = controller.get("circadian") if isinstance(controller, dict) else None
            controller_id = _normalize_unique_id(unique_id)

            for kind in ("brightness", "color_temp"):
                entity_id = f"{controller_id}_{kind}"
                next_ids.add(entity_id)

                if entity_id in self._entities:
                    await self._entities[entity_id].async_apply_config(name, input_lights, circadian)
                    continue

                entity = SvtLightControllerCircadianSwitch(
                    name=name,
                    unique_id=unique_id,
                    input_lights=input_lights,
                    kind=kind,
                    circadian=circadian,
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


class SvtLightControllerCircadianSwitch(SwitchEntity):
    """Switch to control circadian brightness/color temp per controller."""

    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        unique_id: str,
        input_lights: list[str],
        kind: str,
        circadian: dict | None,
        hass: HomeAssistant,
    ) -> None:
        self._input_lights = input_lights
        self._hass = hass
        self._controller_id = _normalize_unique_id(unique_id)
        self._kind = kind
        self._device_name = f"SVTLC {name}"
        self._attr_unique_id = f"{self._controller_id}_circadian_{kind}"
        self._attr_name = f"Circadian {'Brightness' if kind == 'brightness' else 'Color Temp'}"
        self._attr_icon = "mdi:brightness-6" if kind == "brightness" else "mdi:thermometer"
        self._topic_state = f"svtlc/{self._controller_id}/circadian"
        self._topic_set = f"svtlc/{self._controller_id}/circadian/set"
        self._unsub_mqtt = None
        self._has_state = False
        self._attr_is_on = self._default_state(circadian)

    def _default_state(self, circadian: dict | None) -> bool:
        if not isinstance(circadian, dict):
            return True
        if self._kind == "brightness":
            return bool(circadian.get("brightness_enabled", True))
        return bool(circadian.get("color_temp_enabled", True))

    async def async_apply_config(self, name: str, input_lights: list[str], circadian: dict | None) -> None:
        if name:
            self._attr_name = f"Circadian {'Brightness' if self._kind == 'brightness' else 'Color Temp'}"
        self._device_name = f"SVTLC {name}"
        self._input_lights = input_lights
        if not self._has_state:
            self._attr_is_on = self._default_state(circadian)
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

    async def async_turn_on(self, **kwargs) -> None:
        await self._publish_state(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._publish_state(False)

    async def _publish_state(self, enabled: bool) -> None:
        payload = {f"{self._kind}_enabled": enabled}
        await mqtt.async_publish(
            self._hass,
            self._topic_set,
            json.dumps(payload),
            qos=0,
            retain=False,
        )
        self._attr_is_on = enabled
        self.async_write_ha_state()

    @callback
    def _handle_mqtt_state(self, msg) -> None:
        payload = _parse_json_payload(msg.payload)
        if not payload:
            return
        key = f"{self._kind}_enabled"
        if key in payload:
            self._attr_is_on = bool(payload[key])
            self._has_state = True
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
