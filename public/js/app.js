const ROMANIA_CENTER = [45.9432, 24.9668];
const ROMANIA_BOUNDS = [
  [43.5, 20.0],
  [48.8, 30.0],
];

const EMPTY_MESSAGE = "Nu au fost emise sau valabile avertizări pentru această dată.";
const MISSING_GEOMETRY_MESSAGE =
  "Există avertizări ANM, dar fluxul XML curent nu conține geometrii GIS parsabile.";

const statusElement = document.getElementById("status");
const datePicker = document.getElementById("alert-date-picker");
let dataIndex = { dates: [], files: [] };
let alertsLayer = null;

const map = L.map("alerts-map", {
  center: ROMANIA_CENTER,
  zoom: 7,
  minZoom: 5,
  maxZoom: 12,
});

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

map.fitBounds(ROMANIA_BOUNDS, {
  padding: [20, 20],
});

setTimeout(() => {
  map.invalidateSize(true);
  debugLeafletCss();
}, 500);

setTimeout(() => {
  map.invalidateSize(true);
  debugLeafletCss();
}, 1500);

addLegend();
start();

async function start() {
  datePicker.value = todayIso();
  datePicker.addEventListener("change", () => loadAlertsForDate(datePicker.value));

  dataIndex = await loadIndex();
  await loadAlertsForDate(datePicker.value);
}

async function loadIndex() {
  try {
    const response = await fetch("data/index.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.warn("index.json could not be loaded", error);
    return { dates: [], files: [] };
  }
}

async function loadAlertsForDate(dateString) {
  const url = `data/${dateString}.geojson`;
  console.log("Loading alerts:", url);
  setStatus("Se încarcă...");

  let response = await fetch(url, { cache: "no-store" });

  if (!response.ok) {
    console.warn("No daily file, trying latest.geojson");
    response = await fetch("data/latest.geojson", { cache: "no-store" });
  }

  if (!response.ok) {
    console.error("Could not load alert GeoJSON.");
    clearAlertsLayer();
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
    setStatus(emptyMessageFor(dataIndex));
    return;
  }

  const data = await response.json();
  console.log("GeoJSON loaded:", data);
  console.log("Feature count:", data.features ? data.features.length : 0);

  clearAlertsLayer();

  if (!data.features || data.features.length === 0) {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
    setStatus(emptyMessageFor(data.metadata || dataIndex));
    return;
  }

  alertsLayer = L.geoJSON(data, {
    style: getAlertStyle,
    onEachFeature: onEachAlertFeature,
  }).addTo(map);

  const layerCount = alertsLayer.getLayers().length;
  console.log("Leaflet layer count:", layerCount);

  if (layerCount > 0 && alertsLayer.getBounds().isValid()) {
    console.log("Layer bounds:", alertsLayer.getBounds().toBBoxString());
    map.fitBounds(alertsLayer.getBounds(), {
      padding: [30, 30],
      maxZoom: 8,
    });
  } else {
    console.error("GeoJSON loaded, but no valid Leaflet layers were created.");
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  }

  requestAnimationFrame(() => {
    refitMapToCurrentLayer();
  });

  setTimeout(() => {
    map.invalidateSize(true);

    if (alertsLayer && alertsLayer.getLayers().length > 0 && alertsLayer.getBounds().isValid()) {
      map.fitBounds(alertsLayer.getBounds(), {
        padding: [30, 30],
        maxZoom: 8,
      });
    }
  }, 1000);

  setStatus(`${data.features.length} ${data.features.length === 1 ? "avertizare" : "avertizări"} pentru ${dateString}`);
}

function debugLeafletCss() {
  const tile = document.querySelector(".leaflet-tile");
  const mapPane = document.querySelector(".leaflet-map-pane");
  const container = document.getElementById("alerts-map");
  const debugInfo = {
    containerWidth: container?.clientWidth,
    containerHeight: container?.clientHeight,
    tilePosition: tile ? getComputedStyle(tile).position : null,
    tileWidth: tile ? getComputedStyle(tile).width : null,
    tileHeight: tile ? getComputedStyle(tile).height : null,
    mapPanePosition: mapPane ? getComputedStyle(mapPane).position : null,
  };

  window.__leafletDebugCss = window.__leafletDebugCss || [];
  window.__leafletDebugCss.push(debugInfo);

  console.log("Leaflet CSS debug:", debugInfo);
}

function refitMapToCurrentLayer() {
  map.invalidateSize(true);

  if (alertsLayer && alertsLayer.getLayers().length > 0 && alertsLayer.getBounds().isValid()) {
    map.fitBounds(alertsLayer.getBounds(), {
      padding: [30, 30],
      maxZoom: 8,
    });
  } else {
    map.fitBounds(ROMANIA_BOUNDS, {
      padding: [20, 20],
    });
  }
}

function clearAlertsLayer() {
  if (alertsLayer) {
    map.removeLayer(alertsLayer);
    alertsLayer = null;
  }
}

function setStatus(message) {
  statusElement.textContent = message;
}

function emptyMessageFor(metadata) {
  if (metadata?.alerts_found_raw && metadata?.features_with_geometry === 0) {
    return metadata.reason === "XML contains alerts but no coordGis geometry was found"
      ? MISSING_GEOMETRY_MESSAGE
      : metadata.reason || EMPTY_MESSAGE;
  }

  return EMPTY_MESSAGE;
}

function getAlertStyle(feature) {
  const props = feature.properties || {};
  const culoare = String(props.culoare ?? "0").trim();
  const cod = String(props.cod ?? "").toLowerCase();

  let color = "#2E7D32";
  let fillOpacity = 0.30;

  if (culoare === "1" || cod.includes("galben")) {
    color = "#FFD700";
    fillOpacity = 0.45;
  } else if (culoare === "2" || cod.includes("portocaliu")) {
    color = "#FF8C00";
    fillOpacity = 0.50;
  } else if (culoare === "3" || cod.includes("roșu") || cod.includes("rosu")) {
    color = "#FF0000";
    fillOpacity = 0.60;
  }

  return {
    color,
    fillColor: color,
    weight: 1.5,
    opacity: 1,
    fillOpacity,
  };
}

function onEachAlertFeature(feature, layer) {
  const props = feature.properties || {};
  const cod = props.cod || "Verde";
  const codClass = `cod-${slugify(cod)}`;
  const message = DOMPurify.sanitize(props.mesaj || "");

  layer.bindPopup(`
    <span class="popup-title ${codClass}">${escapeHtml(cod)}</span>
    <div class="popup-meta">
      <strong>Tip:</strong> ${escapeHtml(props.tip || props.source || "")}<br>
      <strong>Cod zonă:</strong> ${escapeHtml(props.cod_judet || "")}<br>
      <strong>Apariție:</strong> ${escapeHtml(props.data_aparitiei || "")}<br>
      <strong>Expirare:</strong> ${escapeHtml(props.data_expirarii || "")}<br>
      <strong>Interval:</strong> ${escapeHtml(props.intervalul || "")}
    </div>
    <div class="popup-message">${message || "Fără mesaj."}</div>
  `);
}

function addLegend() {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const container = L.DomUtil.create("div", "leaflet-control legend");
    const rows = [
      ["Verde", "#2E7D32"],
      ["Galben", "#FFD700"],
      ["Portocaliu", "#FF8C00"],
      ["Roșu", "#FF0000"],
    ]
      .map(
        ([label, color]) => `
          <div class="legend-row">
            <span class="legend-swatch" style="background:${color}"></span>
            <span>${label}</span>
          </div>
        `,
      )
      .join("");

    container.innerHTML = `<div class="legend-title">Coduri</div>${rows}`;
    return container;
  };
  legend.addTo(map);
}

function todayIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function slugify(value) {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
