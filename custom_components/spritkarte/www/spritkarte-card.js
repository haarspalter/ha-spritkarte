/* Spritkarte Lovelace-Karte: OSM-Karte (Leaflet) + Tankempfehlung */
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const FUEL_LABEL = { e5: "Super E5", e10: "Super E10", diesel: "Diesel" };

let leafletPromise;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = LEAFLET_JS;
      s.onload = () => resolve(window.L);
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return leafletPromise;
}

const eur = (v) => v.toFixed(2).replace(".", ",") + " €";
const price = (v) => v.toFixed(3).replace(".", ",") + " €/l";

class SpritkarteCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Bitte 'entity' angeben (sensor.tankempfehlung)");
    this._config = config;
    this._amount = config.amount ? String(config.amount) : null;
    this._vid = null;
    this._sig = null;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <link rel="stylesheet" href="${LEAFLET_CSS}">
        <style>
          .tabs { display:flex; gap:8px; padding:0 16px 8px; flex-wrap:wrap; }
          .tab { cursor:pointer; padding:4px 12px; border-radius:16px;
                 border:1px solid var(--divider-color); }
          .tab.active { background:var(--primary-color); color:var(--text-primary-color,#fff); }
          .best { padding:0 16px 8px; font-size:1.1em; }
          #map { height:${config.map_height || 350}px; z-index:0; }
          table { width:100%; border-collapse:collapse; font-size:.9em; }
          th,td { padding:6px 8px; text-align:right; }
          th:first-child,td:first-child { text-align:left; }
          tr.rec { font-weight:bold; background:rgba(76,175,80,.15); }
          tr { cursor:pointer; }
          .wrap { overflow-x:auto; padding:8px 8px 0; }
        </style>
        <ha-card>
          <div class="tabs vtabs"></div>
          <div class="best"></div>
          <div class="tabs"></div>
          <div id="map"></div>
          <div class="wrap"><table></table></div>
        </ha-card>`;
    }
  }

  getCardSize() { return 8; }

  static getConfigElement() {
    return document.createElement("spritkarte-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (e) => e.startsWith("sensor.") && hass.states[e].attributes.vehicles);
    return { entity: entity || "sensor.spritkarte_tankempfehlung", map_height: 350 };
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    if (!st) return;
    const sig = st.last_updated;
    if (sig === this._sig) return;
    this._sig = sig;
    this._data = st.attributes;
    this._render();
  }

  _render() {
    const d = this._data;
    if (!d || !d.amounts || !d.vehicles || !d.vehicles.length) return;
    const root = this.shadowRoot;

    // Fahrzeug bestimmen (Konfig 'vehicle' = Name oder ID, sonst erstes)
    const vehicles = d.vehicles;
    if (!this._vid || !vehicles.some((v) => v.id === this._vid)) {
      const want = this._config.vehicle;
      const match = want && vehicles.find((v) => v.id === want || v.name === want);
      this._vid = (match || vehicles[0]).id;
    }
    const veh = vehicles.find((v) => v.id === this._vid);
    this._veh = veh;

    const vtabs = root.querySelector(".vtabs");
    vtabs.style.display = vehicles.length > 1 ? "flex" : "none";
    vtabs.innerHTML = vehicles.map((v) =>
      `<div class="tab ${v.id === this._vid ? "active" : ""}" data-v="${v.id}">` +
      `🚗 ${v.name} <small>(${FUEL_LABEL[v.fuel] || v.fuel}, ${v.consumption} l/100km)</small></div>`
    ).join("");
    vtabs.querySelectorAll(".tab").forEach((el) =>
      el.addEventListener("click", () => { this._vid = el.dataset.v; this._render(); }));

    const amounts = d.amounts.map(String);
    if (!this._amount || !amounts.includes(this._amount)) this._amount = amounts[0];
    const a = this._amount;

    const rec = veh.recommendations && veh.recommendations[a];
    if (!rec) {
      root.querySelector(".best").textContent =
        `Keine Tankstelle mit ${FUEL_LABEL[veh.fuel] || veh.fuel} für "${veh.name}" gefunden – ` +
        "bitte passende Preis-Sensoren konfigurieren.";
      root.querySelector(".tabs:not(.vtabs)").innerHTML = "";
      root.querySelector("table").innerHTML = "";
      return;
    }
    root.querySelector(".best").innerHTML =
      `⛽ <b>${rec.name}</b> – ${eur(rec.total)} für ${a} l ` +
      `(${price(rec.per_liter)} inkl. Anfahrt)`;

    const tabs = root.querySelector(".tabs:not(.vtabs)");
    tabs.innerHTML = amounts.map(
      (x) => `<div class="tab ${x === a ? "active" : ""}" data-a="${x}">${x} l</div>`).join("");
    tabs.querySelectorAll(".tab").forEach((el) =>
      el.addEventListener("click", () => { this._amount = el.dataset.a; this._render(); }));

    const stations = [...veh.stations].sort((x, y) => x.costs[a].total - y.costs[a].total);
    root.querySelector("table").innerHTML =
      `<tr><th>Tankstelle</th><th>Preis</th><th>Strecke</th><th>Zeit</th><th>Gesamt</th></tr>` +
      stations.map((s) => `
        <tr data-id="${s.entity_id}" class="${s.entity_id === rec.entity_id ? "rec" : ""}">
          <td>${s.name}</td><td>${price(s.price)}</td>
          <td>${s.distance_km.toFixed(1)} km</td>
          <td>${Math.round(s.duration_min)} min</td>
          <td>${eur(s.costs[a].total)}</td></tr>`).join("");
    root.querySelectorAll("tr[data-id]").forEach((tr) =>
      tr.addEventListener("click", () => this._focus(tr.dataset.id)));

    loadLeaflet().then((L) => this._drawMap(L, stations, rec));
  }

  _drawMap(L, stations, rec) {
    const el = this.shadowRoot.getElementById("map");
    if (!this._map) {
      this._map = L.map(el);
      L.tileLayer(this._config.tile_url || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        // OSM-Tile-Policy: Anfragen ohne Referer werden blockiert (HTTP 403)
        referrerPolicy: "strict-origin-when-cross-origin",
        attribution:
          '&copy; <a href="https://openrouteservice.org/">openrouteservice</a> by ' +
          '<a href="https://heigit.org/">HeiGIT</a> | Data from ' +
          '<a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(this._map);
      this._layer = L.layerGroup().addTo(this._map);
      // Karte liegt anfangs oft noch ohne Größe im DOM: bei Größenänderung neu einpassen
      new ResizeObserver(() => {
        this._map.invalidateSize();
        this._tryFit();
      }).observe(el);
    }
    this._layer.clearLayers();
    const d = this._data;
    const pts = [[d.origin.lat, d.origin.lon]];
    L.circleMarker(pts[0], { radius: 8, color: "#1976d2", fillOpacity: 0.9 })
      .bindTooltip("Start").addTo(this._layer);

    this._markers = {};
    stations.forEach((s) => {
      const best = s.entity_id === rec.entity_id;
      const m = L.circleMarker([s.lat, s.lon], {
        radius: best ? 11 : 7,
        color: best ? "#2e7d32" : "#c62828",
        fillOpacity: 0.85,
      }).bindTooltip(`${s.name}: ${price(s.price)}`, { permanent: best })
        .bindPopup(`<b>${s.name}</b><br>${s.address || ""}<br>${price(s.price)}<br>` +
          `${s.distance_km} km, ${Math.round(s.duration_min)} min<br>` +
          `Gesamt: ${eur(s.costs[this._amount].total)}`)
        .addTo(this._layer);
      this._markers[s.entity_id] = m;
      pts.push([s.lat, s.lon]);
    });
    const geo = this._veh.routes && this._veh.routes[rec.entity_id];
    if (geo) {
      L.polyline(geo, { color: "#1976d2", weight: 5, opacity: 0.8 }).addTo(this._layer);
    }
    // Ansicht nur einpassen, wenn sich die Punktmenge ändert (nicht bei Tab-Wechsel,
    // damit eine vom Nutzer gewählte Ansicht erhalten bleibt).
    this._pts = pts;
    const sig = JSON.stringify(pts);
    if (sig !== this._fitSig) {
      this._fitSig = sig;
      this._fitted = false;
    }
    this._tryFit();
  }

  _tryFit() {
    if (!this._map || this._fitted || !this._pts) return;
    const el = this.shadowRoot.getElementById("map");
    if (!el.clientWidth || !el.clientHeight) return; // noch nicht gelayoutet
    this._map.invalidateSize();
    this._map.fitBounds(this._pts, { padding: [25, 25], maxZoom: 17 });
    this._fitted = true;
  }

  _focus(id) {
    const m = this._markers && this._markers[id];
    if (m) { this._map.panTo(m.getLatLng()); m.openPopup(); }
  }
}

class SpritkarteCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        entity: "Tankempfehlungs-Sensor",
        vehicle: "Standard-Fahrzeug (Name, optional)",
        amount: "Standard-Tankmenge (optional)",
        map_height: "Kartenhöhe",
      }[s.name] || s.name);
      this._form.schema = [
        { name: "entity", required: true,
          selector: { entity: { domain: "sensor" } } },
        { name: "vehicle", selector: { text: {} } },
        { name: "amount",
          selector: { number: { min: 1, max: 200, step: 1, mode: "box",
                                unit_of_measurement: "l" } } },
        { name: "map_height",
          selector: { number: { min: 150, max: 1000, step: 10, mode: "slider",
                                unit_of_measurement: "px" } } },
      ];
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const k of Object.keys(config)) {
          if (config[k] === undefined || config[k] === null || config[k] === "") delete config[k];
        }
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", {
          detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { map_height: 350, ...this._config };
  }
}

customElements.define("spritkarte-card", SpritkarteCard);
customElements.define("spritkarte-card-editor", SpritkarteCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "spritkarte-card",
  name: "Spritkarte",
  description: "Tankempfehlung mit OSM-Karte und Routing, für mehrere Fahrzeuge",
  preview: true,
});

