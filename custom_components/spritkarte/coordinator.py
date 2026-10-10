"""Datenabruf, Routing und Kostenberechnung."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    ORS_BASE,
)

_LOGGER = logging.getLogger(__name__)


class OrsRateLimit(UpdateFailed):
    """ORS-Nutzungslimit überschritten (ToS: Limits nicht überreizen)."""


def detect_fuel(entity_id: str, attrs: dict) -> str | None:
    """Kraftstoffsorte (e5/e10/diesel) aus Attribut `fuel_type` oder Entity-ID."""
    raw = str(attrs.get("fuel_type") or "").lower()
    if raw in FUEL_TYPES:
        return raw
    eid = entity_id.lower()
    if "diesel" in eid:
        return "diesel"
    if "e10" in eid:
        return "e10"
    if "e5" in eid or eid.endswith("_super") or "super" in eid:
        return "e5"
    return None


def parse_amounts(raw: str | list | None) -> list[float]:
    """Komma-getrennte Literliste in Floats umwandeln."""
    if raw is None:
        return []
    if isinstance(raw, (int, float)):
        return [float(raw)]
    if isinstance(raw, str):
        raw = raw.replace(";", ",").split(",")
    out: list[float] = []
    for part in raw:
        try:
            val = float(str(part).strip().replace(",", "."))
        except ValueError:
            continue
        if val > 0:
            out.append(val)
    return out


class SpritkarteCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordiniert Preise (bestehende Entitäten) und ORS-Routing."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.cfg = cfg
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=int(cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self._session = async_get_clientsession(hass)
        self._store = Store(hass, 1, f"{DOMAIN}_routes_{entry.entry_id}")
        self._cache: dict[str, Any] = {"origin": None, "routes": {}}
        self._blocked_until: float = 0.0

    # ---------- Eingangsdaten ----------
    def _origin(self) -> tuple[float, float]:
        ent = self.cfg.get(CONF_ORIGIN_ENTITY)
        if ent:
            st = self.hass.states.get(ent)
            if st:
                lat = st.attributes.get("latitude")
                lon = st.attributes.get("longitude")
                if lat is not None and lon is not None:
                    return float(lat), float(lon)
        return self.hass.config.latitude, self.hass.config.longitude

    def _stations(self) -> list[dict[str, Any]]:
        found: dict[tuple, dict[str, Any]] = {}
        for ent in self.cfg.get(CONF_PRICE_ENTITIES, []):
            st = self.hass.states.get(ent)
            if st is None:
                continue
            try:
                price = float(st.state)
            except (ValueError, TypeError):
                continue
            a = st.attributes
            lat, lon = a.get("latitude"), a.get("longitude")
            if lat is None or lon is None:
                _LOGGER.debug("%s hat keine Koordinaten, übersprungen", ent)
                continue
            name = a.get("station_name") or a.get("brand") or st.name
            fuel = detect_fuel(ent, a)
            if fuel is None:
                _LOGGER.warning("Kraftstoffsorte von %s nicht erkennbar, übersprungen", ent)
                continue
            key = (round(float(lat), 5), round(float(lon), 5), fuel)
            item = {
                "entity_id": ent,
                "name": name,
                "brand": a.get("brand"),
                "address": ", ".join(
                    x
                    for x in (
                        " ".join(
                            str(y) for y in (a.get("street"), a.get("house_number")) if y
                        ),
                        " ".join(
                            str(y) for y in (a.get("postcode"), a.get("city")) if y
                        ),
                    )
                    if x
                ),
                "price": price,
                "fuel": fuel,
                "lat": float(lat),
                "lon": float(lon),
            }
            if key not in found or price < found[key]["price"]:
                found[key] = item
        return list(found.values())

    # ---------- ORS ----------
    async def _ors(self, path: str, payload: dict) -> dict:
        headers = {
            "Authorization": self.cfg[CONF_API_KEY],
            "Content-Type": "application/json",
        }
        try:
            async with self._session.post(
                f"{ORS_BASE}{path}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    raise OrsRateLimit("ORS-Nutzungslimit erreicht (HTTP 429)")
                if resp.status != 200:
                    raise UpdateFailed(f"ORS {path}: HTTP {resp.status} {await resp.text()}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"ORS nicht erreichbar: {err}") from err

    # ---------- Routen-Cache ----------
    @staticmethod
    def _skey(s: dict) -> str:
        return f"{s['lat']:.5f},{s['lon']:.5f}"

    @staticmethod
    def _okey(origin: tuple[float, float]) -> str:
        return f"{origin[0]:.3f},{origin[1]:.3f}"

    async def async_load_cache(self) -> None:
        data = await self._store.async_load()
        if data:
            self._cache = data

    async def async_recalculate(self) -> None:
        """Alle Routen verwerfen und sofort neu berechnen (manueller Start)."""
        self._cache = {"origin": None, "routes": {}}
        await self._store.async_save(self._cache)
        await self.async_request_refresh()

    async def _fetch_route(self, origin: tuple[float, float], s: dict) -> dict:
        data = await self._ors(
            "/v2/directions/driving-car/geojson",
            {"coordinates": [[origin[1], origin[0]], [s["lon"], s["lat"]]]},
        )
        feat = data["features"][0]
        summary = feat["properties"]["summary"]
        return {
            "km": summary["distance"] / 1000,
            "min": summary["duration"] / 60,
            "geometry": [
                [round(c[1], 5), round(c[0], 5)] for c in feat["geometry"]["coordinates"]
            ],
        }

    async def _ensure_routes(
        self, origin: tuple[float, float], stations: list[dict]
    ) -> dict[str, dict]:
        """Routen nur berechnen, wenn sie fehlen (neue Tankstelle / neuer Startpunkt)."""
        okey = self._okey(origin)
        if self._cache.get("origin") != okey:
            self._cache = {"origin": okey, "routes": {}}
        routes = self._cache["routes"]
        wanted = {self._skey(s) for s in stations}
        for k in list(routes):
            if k not in wanted:
                del routes[k]

        missing = [s for s in stations if self._skey(s) not in routes]
        changed = bool(missing) or len(routes) != len(wanted)
        # Datenschutz (ORS-ToS: keine personenbezogenen Daten): Startpunkt nur auf
        # ca. 100 m genau übermitteln.
        origin = (round(origin[0], 3), round(origin[1], 3))
        if self._blocked_until and monotonic() < self._blocked_until:
            missing = []  # Nutzungslimit: bis zum Ablauf der Sperre nicht erneut anfragen
        for i, s in enumerate(missing):
            if i:
                await asyncio.sleep(1.6)  # ORS: max. 40 Directions-Requests/Minute
            try:
                routes[self._skey(s)] = await self._fetch_route(origin, s)
            except OrsRateLimit as err:
                _LOGGER.warning("%s – pausiere Anfragen für 1 Stunde", err)
                self._blocked_until = monotonic() + 3600
                break
            except (UpdateFailed, KeyError, IndexError) as err:
                _LOGGER.warning("Route zu %s nicht berechenbar: %s", s["name"], err)
        if changed:
            await self._store.async_save(self._cache)
        return routes

    # ---------- Hauptlogik ----------
    def vehicles(self) -> list[dict[str, Any]]:
        """Konfigurierte Fahrzeuge (Rückwärtskompatibel zur Ein-Fahrzeug-Konfig)."""
        vehicles = self.cfg.get(CONF_VEHICLES)
        if vehicles:
            return vehicles
        return [
            {
                "id": "default",
                "name": "Fahrzeug",
                "fuel": "e10",
                "consumption": float(self.cfg.get(CONF_CONSUMPTION, DEFAULT_CONSUMPTION)),
            }
        ]

    async def _async_update_data(self) -> dict[str, Any]:
        origin = self._origin()
        all_stations = self._stations()
        amounts = parse_amounts(self.cfg.get(CONF_AMOUNTS, DEFAULT_AMOUNTS))
        factor = 2 if self.cfg.get(CONF_ROUND_TRIP, DEFAULT_ROUND_TRIP) else 1

        if not all_stations:
            raise UpdateFailed("Keine Tankstellen mit gültigem Preis/Koordinaten")
        if not amounts:
            raise UpdateFailed("Keine gültigen Tankmengen konfiguriert")

        # Routen hängen nur von den Koordinaten ab -> einmal je Standort, für alle Sorten
        unique = list({self._skey(s): s for s in all_stations}.values())
        routes_info = await self._ensure_routes(origin, unique)

        vehicles_out = []
        for veh in self.vehicles():
            stations = [s for s in all_stations if s["fuel"] == veh["fuel"]]
            vehicles_out.append(
                self._calc_vehicle(veh, stations, routes_info, amounts, factor)
            )
        if not any(v["stations"] for v in vehicles_out):
            raise UpdateFailed("Keine Route/Tankstelle für die Fahrzeuge verfügbar")

        # Geometrie aller genutzten Routen einmalig (von Fahrzeugen geteilt) ausliefern
        used = {s["route_key"] for v in vehicles_out for s in v["stations"]}
        return {
            "origin": {"lat": origin[0], "lon": origin[1]},
            "amounts": amounts,
            "round_trip": factor == 2,
            "vehicles": vehicles_out,
            "routes": {k: routes_info[k]["geometry"] for k in used if k in routes_info},
        }

    def _calc_vehicle(
        self,
        veh: dict[str, Any],
        stations: list[dict],
        routes_info: dict[str, dict],
        amounts: list[float],
        factor: int,
    ) -> dict[str, Any]:
        cons = float(veh["consumption"])
        enriched = []
        for s in stations:
            info = routes_info.get(self._skey(s))
            if info is None:
                continue
            km, minutes = info["km"], info["min"]
            trip_km = km * factor
            burned = trip_km * cons / 100
            costs = {}
            for amt in amounts:
                total = (amt + burned) * s["price"]
                costs[f"{amt:g}"] = {
                    "total": round(total, 2),
                    "per_liter": round(total / amt, 3),
                }
            enriched.append(
                {
                    **s,
                    "distance_km": round(km, 2),
                    "duration_min": round(minutes, 1),
                    "trip_km": round(trip_km, 2),
                    "fuel_burned_l": round(burned, 2),
                    "costs": costs,
                    "route_key": self._skey(s),
                }
            )

        result: dict[str, Any] = {
            "id": veh["id"],
            "name": veh["name"],
            "fuel": veh["fuel"],
            "consumption": cons,
            "stations": [],
            "recommendations": {},
        }
        if not enriched:
            return result

        cheapest = min(enriched, key=lambda e: e["price"])
        for amt in amounts:
            k = f"{amt:g}"
            best = min(enriched, key=lambda e: e["costs"][k]["total"])
            result["recommendations"][k] = {
                "entity_id": best["entity_id"],
                "name": best["name"],
                "total": best["costs"][k]["total"],
                "per_liter": best["costs"][k]["per_liter"],
                "saving_vs_cheapest_price": round(
                    best["costs"][k]["total"] - cheapest["costs"][k]["total"], 2
                ),
            }
            best["recommended_for"] = best.get("recommended_for", []) + [amt]

        enriched.sort(key=lambda e: e["costs"][f"{amounts[0]:g}"]["total"])
        result["stations"] = enriched
        return result
