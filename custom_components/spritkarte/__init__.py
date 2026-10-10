"""Spritkarte: Tankempfehlung mit Routing und OSM-Karte."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CARD_FILE, DOMAIN, URL_BASE
from .coordinator import SpritkarteCoordinator

PLATFORMS = ["sensor", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Lovelace-Karte als statische Datei bereitstellen."""
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(www), False)]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILE}")

    async def _recalculate(call) -> None:
        for coord in hass.data.get(DOMAIN, {}).values():
            await coord.async_recalculate()

    hass.services.async_register(DOMAIN, "recalculate", _recalculate)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = SpritkarteCoordinator(hass, entry)
    await coordinator.async_load_cache()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok

