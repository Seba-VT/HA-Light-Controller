"""SVT Light Controller integration."""

import voluptuous as vol

from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.discovery import async_load_platform

from .const import CONF_CONTROLLERS, CONF_INPUT_LIGHTS, CONF_UNIQUE_ID, DOMAIN

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


async def async_setup(hass, config):
    """Set up the SVT Light Controller integration."""
    if DOMAIN not in config:
        return True

    hass.data[DOMAIN] = config[DOMAIN]

    hass.async_create_task(async_load_platform(hass, "light", DOMAIN, {}, config))
    return True