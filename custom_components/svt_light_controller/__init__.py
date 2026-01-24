"""SVT Light Controller integration."""

import os
import voluptuous as vol

from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_CONTROLLERS, CONF_INPUT_LIGHTS, CONF_UNIQUE_ID, CONFIG_PATH, DOMAIN
from .data import get_all_controllers
from .storage import async_load_controllers

CONTROLLER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_INPUT_LIGHTS): [cv.entity_id],
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_CONTROLLERS): [CONTROLLER_SCHEMA],
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def _apply_controller_updates(hass, controllers: list[dict], mtime: float | None = None) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if mtime is not None:
        domain_data["config_mtime"] = mtime
    domain_data["file_controllers"] = controllers

    manager = domain_data.get("manager")
    if manager:
        await manager.async_update(get_all_controllers(hass))
    switch_manager = domain_data.get("switch_manager")
    if switch_manager:
        await switch_manager.async_update(get_all_controllers(hass))
    sensor_manager = domain_data.get("sensor_manager")
    if sensor_manager:
        await sensor_manager.async_update(get_all_controllers(hass))
    number_manager = domain_data.get("number_manager")
    if number_manager:
        await number_manager.async_update(get_all_controllers(hass))
    select_manager = domain_data.get("select_manager")
    if select_manager:
        await select_manager.async_update(get_all_controllers(hass))


async def _ensure_file_poll(hass) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("file_poll_unsub"):
        return

    async def _handle_file_poll(_now):
        current_mtime = _config_mtime()
        controllers = await async_load_controllers(hass)
        previous = domain_data.get("file_controllers")

        if current_mtime == domain_data.get("config_mtime") and controllers == previous:
            return

        await _apply_controller_updates(hass, controllers, mtime=current_mtime)

    domain_data["file_poll_unsub"] = async_track_time_interval(hass, _handle_file_poll, _poll_interval())


async def async_setup(hass, config):
    """Set up the SVT Light Controller integration."""
    if DOMAIN in config:
        hass.data.setdefault(DOMAIN, {})["yaml"] = config[DOMAIN]

    controllers = await async_load_controllers(hass)
    await _apply_controller_updates(hass, controllers, mtime=_config_mtime())
    await _ensure_file_poll(hass)

    hass.async_create_task(async_load_platform(hass, "light", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "switch", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "number", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "select", DOMAIN, {}, config))

    if not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(DOMAIN, context={"source": "import"}, data={})
        )

    return True


async def async_setup_entry(hass, entry):
    """Set up SVT Light Controller from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    entries = domain_data.setdefault("entries", {})
    entries[entry.entry_id] = entry.data

    await _apply_controller_updates(hass, get_all_controllers(hass))
    await _ensure_file_poll(hass)

    await hass.config_entries.async_forward_entry_setups(entry, ["light", "switch", "sensor", "number", "select"])
    return True


async def async_unload_entry(hass, entry):
    """Unload a SVT Light Controller config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, ["light", "switch", "sensor", "number", "select"])
    if unloaded:
        entries = hass.data.get(DOMAIN, {}).get("entries", {})
        entries.pop(entry.entry_id, None)
        manager = hass.data.get(DOMAIN, {}).get("manager")
        if manager:
            await manager.async_update(get_all_controllers(hass))

    return unloaded


def _config_mtime() -> float:
    try:
        return os.path.getmtime(CONFIG_PATH)
    except OSError:
        return 0.0


def _poll_interval():
    from datetime import timedelta

    return timedelta(seconds=2)
