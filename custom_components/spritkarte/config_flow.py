"""Config- und Options-Flow (inkl. Fahrzeugverwaltung)."""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AMOUNTS,
    CONF_API_KEY,
    CONF_CONSUMPTION,
    CONF_ORIGIN_ENTITY,
    CONF_PRICE_ENTITIES,
    CONF_ROUND_TRIP,
    CONF_SCAN_INTERVAL,
    CONF_VEHICLES,
    DEFAULT_AMOUNTS,
    DEFAULT_CONSUMPTION,
    DEFAULT_ROUND_TRIP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUEL_TYPES,
)
from .coordinator import parse_amounts

CONF_VEHICLE_NAME = "vehicle_name"
CONF_FUEL = "fuel"
CONF_DELETE = "delete"
CONF_VEHICLE = "vehicle"


def _fuel_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[{"value": k, "label": v} for k, v in FUEL_TYPES.items()],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _consumption_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=30, step=0.1, unit_of_measurement="l/100km",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _vehicle_fields(d: dict) -> dict:
    return {
        vol.Required(CONF_VEHICLE_NAME, default=d.get(CONF_VEHICLE_NAME, "")): str,
        vol.Required(CONF_FUEL, default=d.get(CONF_FUEL, "e10")): _fuel_selector(),
        vol.Required(
            CONF_CONSUMPTION, default=d.get(CONF_CONSUMPTION, DEFAULT_CONSUMPTION)
        ): _consumption_selector(),
    }


def _settings_schema(d: dict, with_key: bool) -> dict:
    fields: dict = {}
    if with_key:
        fields[vol.Required(CONF_API_KEY, default=d.get(CONF_API_KEY, ""))] = str
    fields.update(
        {
            vol.Required(
                CONF_PRICE_ENTITIES, default=d.get(CONF_PRICE_ENTITIES, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(
                CONF_ORIGIN_ENTITY,
                description={"suggested_value": d.get(CONF_ORIGIN_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["device_tracker", "person", "zone"]
                )
            ),
            vol.Required(CONF_AMOUNTS, default=d.get(CONF_AMOUNTS, DEFAULT_AMOUNTS)): str,
            vol.Required(
                CONF_ROUND_TRIP, default=d.get(CONF_ROUND_TRIP, DEFAULT_ROUND_TRIP)
            ): bool,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=120, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )
    return fields


def _new_vehicle(user_input: dict) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "name": user_input[CONF_VEHICLE_NAME].strip(),
        "fuel": user_input[CONF_FUEL],
        "consumption": float(user_input[CONF_CONSUMPTION]),
    }


def _validate_settings(user_input: dict) -> dict:
    errors = {}
    if not parse_amounts(user_input.get(CONF_AMOUNTS)):
        errors[CONF_AMOUNTS] = "invalid_amounts"
    return errors


def _validate_vehicle(user_input: dict) -> dict:
    errors = {}
    if not user_input.get(CONF_VEHICLE_NAME, "").strip():
        errors[CONF_VEHICLE_NAME] = "invalid_name"
    return errors


class SpritkarteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = _validate_settings(user_input) | _validate_vehicle(user_input)
            if not errors:
                data = {
                    k: v
                    for k, v in user_input.items()
                    if k not in (CONF_VEHICLE_NAME, CONF_FUEL, CONF_CONSUMPTION)
                }
                data[CONF_VEHICLES] = [_new_vehicle(user_input)]
                return self.async_create_entry(title="Spritkarte", data=data)
        d = user_input or {}
        schema = vol.Schema(
            {**_settings_schema(d, True), **_vehicle_fields({CONF_VEHICLE_NAME: "Auto", **d})}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SpritkarteOptionsFlow()


class SpritkarteOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._edit_id: str | None = None

    # --- Hilfen ---
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _vehicles(self) -> list[dict]:
        cur = self._current()
        vehicles = cur.get(CONF_VEHICLES)
        if vehicles:
            return [dict(v) for v in vehicles]
        # Konfiguration aus Version ohne Fahrzeugliste
        return [
            {
                "id": "default",
                "name": "Fahrzeug",
                "fuel": "e10",
                "consumption": float(cur.get(CONF_CONSUMPTION, DEFAULT_CONSUMPTION)),
            }
        ]

    def _save(self, **changes):
        """Optionen speichern, vorhandene Werte (v. a. Fahrzeuge) erhalten."""
        data = {**self.config_entry.options, **changes}
        data.setdefault(CONF_VEHICLES, self._vehicles())
        return self.async_create_entry(title="", data=data)

    # --- Menü ---
    async def async_step_init(self, user_input=None):
        options = ["settings", "add_vehicle", "edit_vehicle"]
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_settings(self, user_input=None):
        errors = {}
        current = self._current()
        if user_input is not None:
            user_input.setdefault(CONF_ORIGIN_ENTITY, None)
            errors = _validate_settings(user_input)
            if not errors:
                return self._save(**user_input)
            current = {**current, **user_input}
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(_settings_schema(current, False)),
            errors=errors,
        )

    async def async_step_add_vehicle(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = _validate_vehicle(user_input)
            if not errors:
                vehicles = self._vehicles() + [_new_vehicle(user_input)]
                return self._save(**{CONF_VEHICLES: vehicles})
        return self.async_show_form(
            step_id="add_vehicle",
            data_schema=vol.Schema(_vehicle_fields(user_input or {})),
            errors=errors,
        )

    async def async_step_edit_vehicle(self, user_input=None):
        vehicles = self._vehicles()
        if user_input is not None:
            self._edit_id = user_input[CONF_VEHICLE]
            return await self.async_step_edit_vehicle_form()
        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": v["id"],
                                "label": f"{v['name']} ({FUEL_TYPES[v['fuel']]}, "
                                f"{v['consumption']:g} l/100km)",
                            }
                            for v in vehicles
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_vehicle", data_schema=schema)

    async def async_step_edit_vehicle_form(self, user_input=None):
        vehicles = self._vehicles()
        veh = next((v for v in vehicles if v["id"] == self._edit_id), None)
        if veh is None:
            return await self.async_step_init()
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_DELETE):
                if len(vehicles) <= 1:
                    errors["base"] = "last_vehicle"
                else:
                    vehicles = [v for v in vehicles if v["id"] != veh["id"]]
                    return self._save(**{CONF_VEHICLES: vehicles})
            else:
                errors = _validate_vehicle(user_input)
                if not errors:
                    veh.update(
                        name=user_input[CONF_VEHICLE_NAME].strip(),
                        fuel=user_input[CONF_FUEL],
                        consumption=float(user_input[CONF_CONSUMPTION]),
                    )
                    return self._save(**{CONF_VEHICLES: vehicles})
        defaults = {
            CONF_VEHICLE_NAME: veh["name"],
            CONF_FUEL: veh["fuel"],
            CONF_CONSUMPTION: veh["consumption"],
        }
        schema = vol.Schema(
            {**_vehicle_fields(defaults), vol.Optional(CONF_DELETE, default=False): bool}
        )
        return self.async_show_form(
            step_id="edit_vehicle_form", data_schema=schema, errors=errors
        )
