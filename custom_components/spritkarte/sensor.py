"""Sensoren mit Tankempfehlung (Gesamtsensor + je Fahrzeug ein Sensor)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [TankempfehlungSensor(coordinator, entry)]
    vehicles = coordinator.vehicles()
    entities += [
        VehicleSensor(coordinator, entry, veh) for veh in vehicles
    ]
    # Füge Sensoren für die günstigste Tankstelle hinzu
    entities += [
        CheapestGasStationSensor(coordinator, entry, veh) for veh in vehicles
    ]
    async_add_entities(entities)


def _first_recommendation(data: dict, vehicle: dict | None) -> dict | None:
    if not data or not vehicle or not vehicle["recommendations"]:
        return None
    return vehicle["recommendations"].get(f"{data['amounts'][0]:g}")


class TankempfehlungSensor(CoordinatorEntity, SensorEntity):
    """Alle Fahrzeuge + Details (für die Karte). State = Empfehlung des 1. Fahrzeugs."""

    _attr_has_entity_name = True
    _attr_name = "Tankempfehlung"
    _attr_icon = "mdi:gas-station"
    # Große Attribute nicht in die Datenbank schreiben
    _unrecorded_attributes = frozenset({"vehicles", "routes", "origin", "amounts", "round_trip"})

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_recommendation"

    @property
    def native_value(self):
        d = self.coordinator.data
        if not d:
            return None
        rec = _first_recommendation(d, d["vehicles"][0])
        return rec["name"] if rec else None

    @property
    def extra_state_attributes(self):
        return self.coordinator.data or {}


class VehicleSensor(CoordinatorEntity, SensorEntity):
    """Kompakte Empfehlung je Fahrzeug (für Automationen/Benachrichtigungen)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:car"

    def __init__(self, coordinator, entry, vehicle: dict) -> None:
        super().__init__(coordinator)
        self._vid = vehicle["id"]
        self._attr_unique_id = f"{entry.entry_id}_vehicle_{self._vid}"
        self._attr_name = f"Tankempfehlung {vehicle['name']}"

    def _vehicle(self) -> dict | None:
        d = self.coordinator.data
        if not d:
            return None
        return next((v for v in d["vehicles"] if v["id"] == self._vid), None)

    @property
    def native_value(self):
        rec = _first_recommendation(self.coordinator.data, self._vehicle())
        return rec["name"] if rec else None

    @property
    def extra_state_attributes(self):
        v = self._vehicle()
        if not v:
            return {}
        return {
            "vehicle": v["name"],
            "fuel": v["fuel"],
            "consumption": v["consumption"],
            "recommendations": v["recommendations"],
        }


class CheapestGasStationSensor(CoordinatorEntity, SensorEntity):
    """Text-Entität mit der aktuell günstigsten Tankstelle für ein Fahrzeug."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gas-station-check"
    _attr_unit_of_measurement = ""

    def __init__(self, coordinator, entry, vehicle: dict) -> None:
        super().__init__(coordinator)
        self._vid = vehicle["id"]
        self._attr_unique_id = f"{entry.entry_id}_cheapest_{self._vid}"
        self._attr_name = f"Günstigste Tankstelle {vehicle['name']}"

    def _vehicle(self) -> dict | None:
        d = self.coordinator.data
        if not d:
            return None
        return next((v for v in d["vehicles"] if v["id"] == self._vid), None)

    @property
    def native_value(self):
        v = self._vehicle()
        if not v or not self.coordinator.data:
            return None
        
        stations = self.coordinator.data.get("vehicles", [])
        vehicle_data = next((veh for veh in stations if veh["id"] == self._vid), None)
        
        if not vehicle_data or not vehicle_data.get("stations"):
            return None
        
        cheapest_station = min(vehicle_data["stations"], key=lambda s: s["price"])
        return cheapest_station["name"]

    @property
    def extra_state_attributes(self):
        v = self._vehicle()
        if not v or not self.coordinator.data:
            return {}
        
        stations = self.coordinator.data.get("vehicles", [])
        vehicle_data = next((veh for veh in stations if veh["id"] == self._vid), None)
        
        if not vehicle_data:
            return {}
        
        cheapest = min(vehicle_data["stations"], key=lambda s: s["price"])
        return {
            "vehicle": v["name"],
            "fuel": v["fuel"],
            "entity_id": cheapest["entity_id"],
            "price_per_liter": f"{cheapest['price']:.2f} €",
            "distance_km": f"{cheapest.get('distance_km', 'N/A'):.1f}",
        }
