"""Controller data helpers."""

from __future__ import annotations

from .const import CONF_CONTROLLERS, DOMAIN


def get_all_controllers(hass) -> list[dict]:
    """Return combined controllers from YAML, file config, and entries."""
    data = hass.data.get(DOMAIN, {})

    controllers: list[dict] = []

    yaml_data = data.get("yaml", {})
    if isinstance(yaml_data, dict):
        controllers.extend(yaml_data.get(CONF_CONTROLLERS, []))

    file_controllers = data.get("file_controllers", [])
    if isinstance(file_controllers, list):
        controllers.extend(file_controllers)

    entries = data.get("entries", {})
    if isinstance(entries, dict):
        controllers.extend(entries.values())

    return controllers