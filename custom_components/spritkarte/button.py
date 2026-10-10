"""Button zum manuellen Neuberechnen aller Routen."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([RecalculateButton(hass.data[DOMAIN][entry.entry_id], entry)])


class RecalculateButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Routen neu berechnen"
    _attr_icon = "mdi:routes"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_recalculate"

    async def async_press(self) -> None:
        await self._coordinator.async_recalculate()

