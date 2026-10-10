/* Spritkarte Lovelace-Karte: OSM-Karte (Leaflet) + Tankempfehlung */
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const FUEL_LABEL = { e5: "Super E5", e10: "Super E10", diesel: "Diesel" };

// Eigene Leaflet-Kopie laden und per noConflict() vom globalen window.L lösen.
// Andere Karten (z. B. weather-radar-card) bringen ihr eigenes Leaflet mit; würden
// wir window.L mitbenutzen, könnten Klassen verschiedener Leaflet-Instanzen
// vermischt werden (-> "Cannot read properties of undefined (reading 'x')").
let leafletPromise;
function loadLeaflet() {
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = LEAFLET_JS;
      s.onload = () => {
        const ours = window.L;
        resolve(ours && ours.noConflict ? ours.noConflict() : ours);
      };
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
          tr.sel { font-weight:bold; background:rgba(251,140,0,.18); }
          tr { cursor:pointer; }
          .wrap { overflow-x:auto; padding:8px 8px 0; }
          .updated { padding:6px 16px 10px; font-size:.8em; text-align:right; color:var(--secondary-text-color); }
        </style>
        <ha-card>
          <div class="tabs vtabs"></div>
          <div class="best"></div>
          <div class="tabs"></div>
          <div id="map"></div>
          <div class="wrap"><table></table></div>
          <div class="updated"></div>
        </ha-card>`;
    }
  }

  getCardSize() {
    let size = 2; // Header + Tabs + Updated
    if (this._config && this._config.show_map !== false) size += 4;
    if (this._config && !this._config.only_recommended) size += 3;
    return size;
  }

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

  connectedCallback() {
    this._ticker = setInterval(() => this._renderUpdated(), 60000);
  }

  disconnectedCallback() {
    clearInterval(this._ticker);
  }

  _renderUpdated() {
    const el = this.shadowRoot && this.shadowRoot.querySelector(".updated");
    const ts = this._data && this._data.updated_at;
    if (!el || !ts) return;
    const t = new Date(ts);
    if (isNaN(t)) return;
    const lang = (this._hass && this._hass.language) || "de";
    const diffMins = Math.round((t.getTime() - Date.now()) / 60000);
    const rel = new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(
      Math.abs(diffMins) < 60 ? diffMins : Math.round(diffMins / 60),
      Math.abs(diffMins) < 60 ? "minute" : "hour"
    );
    const sameDay = t.toDateString() === new Date().toDateString();
    const abs = sameDay
      ? t.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })
      : t.toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
    el.textContent = `Zuletzt aktualisiert: ${abs} (${rel})`;
  }

  _render() {
    const d = this._data;
    if (!d || !d.amounts || !d.vehicles || !d.vehicles.length) return;
    const root = this.shadowRoot;
    this._renderUpdated();

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

    const showMap = this._config.show_map !== false;
    const onlyRec = Boolean(this._config.only_recommended);

    const mapEl = root.querySelector("#map");
    mapEl.style.display = showMap ? "block" : "none";

    const wrapEl = root.querySelector(".wrap");
    wrapEl.style.display = onlyRec ? "none" : "block";

    const stations = [...veh.stations].sort((x, y) => x.costs[a].total - y.costs[a].total);
    if (!onlyRec) {
      // Auswahl nur behalten, solange die Tankstelle zum Fahrzeug gehört
      if (this._sel && !stations.some((s) => s.entity_id === this._sel)) this._sel = null;
      const rowClass = (s) =>
        s.entity_id === rec.entity_id ? "rec" : s.entity_id === this._sel ? "sel" : "";
      root.querySelector("table").innerHTML =
        `<tr><th>Tankstelle</th><th>Preis</th><th>Strecke</th><th>Zeit</th><th>Gesamt</th></tr>` +
        stations.map((s) => `
          <tr data-id="${s.entity_id}" class="${rowClass(s)}">
            <td>${s.name}</td><td>${price(s.price)}</td>
            <td>${s.distance_km.toFixed(1)} km</td>
            <td>${Math.round(s.duration_min)} min</td>
            <td>${eur(s.costs[a].total)}</td></tr>`).join("");
      root.querySelectorAll("tr[data-id]").forEach((tr) =>
        tr.addEventListener("click", () => this._select(tr.dataset.id)));
    } else {
      root.querySelector("table").innerHTML = "";
    }

    if (showMap) {
      loadLeaflet().then((L) => this._drawMap(L, stations, rec));
    }
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

    const GREEN = "#2e7d32";
    const ORANGE = "#fb8c00";
    const routes = d.routes || {};
    const bestSt = stations.find((s) => s.entity_id === rec.entity_id);
    const selSt = this._sel && this._sel !== rec.entity_id
      ? stations.find((s) => s.entity_id === this._sel) : null;

    // Routen zuerst (unter den Markern): gewählte Tankstelle orange, günstigste grün
    const drawRoute = (st, color) => {
      const geo = st && routes[st.route_key];
      if (geo) L.polyline(geo, { color, weight: 5, opacity: 0.85 }).addTo(this._layer);
    };
    drawRoute(selSt, ORANGE);
    drawRoute(bestSt, GREEN);

    // Marker: übrige zuerst, dann gewählte, dann günstigste obenauf
    this._markers = {};
    const rank = (s) => (s === bestSt ? 2 : s === selSt ? 1 : 0);
    [...stations].sort((x, y) => rank(x) - rank(y)).forEach((s) => {
      const isBest = s === bestSt;
      const isSel = s === selSt;
      const m = L.circleMarker([s.lat, s.lon], {
        radius: isBest ? 11 : isSel ? 9 : 7,
        color: isBest ? GREEN : isSel ? ORANGE : "#c62828",
        fillOpacity: 0.85,
      }).bindTooltip(`${s.name}: ${price(s.price)}`, { permanent: isBest || isSel })
        .bindPopup(`<b>${s.name}</b><br>${s.address || ""}<br>${price(s.price)}<br>` +
          `${s.distance_km} km, ${Math.round(s.duration_min)} min<br>` +
          `Gesamt: ${eur(s.costs[this._amount].total)}`)
        .on("click", () => this._select(s.entity_id))
        .addTo(this._layer);
      this._markers[s.entity_id] = m;
      pts.push([s.lat, s.lon]);
    });
    if (this._focusId) {
      const m = this._markers[this._focusId];
      this._focusId = null;
      if (m) { this._map.panTo(m.getLatLng()); m.openPopup(); }
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

  _select(id) {
    this._sel = id;
    this._focusId = id; // nach dem Neuzeichnen Popup öffnen / zentrieren
    this._render();
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
        show_map: "Karte anzeigen",
        map_height: "Kartenhöhe",
        only_recommended: "Kompaktmodus: Nur günstigste Tankstelle (keine Tabelle)",
      }[s.name] || s.name);
      this._form.schema = [
        { name: "entity", required: true,
          selector: { entity: { domain: "sensor" } } },
        { name: "vehicle", selector: { text: {} } },
        { name: "amount",
          selector: { number: { min: 1, max: 200, step: 1, mode: "box",
                                unit_of_measurement: "l" } } },
        { name: "show_map", selector: { boolean: {} } },
        { name: "map_height",
          selector: { number: { min: 150, max: 1000, step: 10, mode: "slider",
                                unit_of_measurement: "px" } } },
        { name: "only_recommended", selector: { boolean: {} } },
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
    this._form.data = {
      map_height: 350,
      show_map: this._config.show_map !== false,
      only_recommended: Boolean(this._config.only_recommended),
      ...this._config,
    };
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

