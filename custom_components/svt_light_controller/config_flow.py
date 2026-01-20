"""Config flow for SVT Light Controller."""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SVT Light Controller."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        return self.async_create_entry(title="SVT Light Controller", data={})

    async def async_step_import(self, user_input=None):
        return self.async_create_entry(title="SVT Light Controller", data={})
