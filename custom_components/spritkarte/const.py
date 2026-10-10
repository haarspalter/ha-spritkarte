"""Konstanten für Spritkarte."""

DOMAIN = "spritkarte"

CONF_API_KEY = "ors_api_key"
CONF_PRICE_ENTITIES = "price_entities"
CONF_ORIGIN_ENTITY = "origin_entity"
CONF_AMOUNTS = "amounts"
CONF_CONSUMPTION = "consumption"
CONF_ROUND_TRIP = "round_trip"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_VEHICLES = "vehicles"

FUEL_TYPES = {"e5": "Super E5", "e10": "Super E10", "diesel": "Diesel"}

DEFAULT_AMOUNTS = "20, 40"
DEFAULT_CONSUMPTION = 7.0
DEFAULT_ROUND_TRIP = True
DEFAULT_SCAN_INTERVAL = 15  # Minuten

ORS_BASE = "https://api.openrouteservice.org"

URL_BASE = "/spritkarte_static"
CARD_FILE = "spritkarte-card.js"

