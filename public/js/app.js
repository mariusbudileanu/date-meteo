const ROMANIA_CENTER = [45.9432, 24.9668];
const ROMANIA_BOUNDS = [
  [43.5, 20.0],
  [48.8, 30.0],
];

const NO_ALERTS_MESSAGE = "Nu există avertizări înregistrate pentru această dată.";
const EMPTY_MESSAGE = "Nu au fost emise sau valabile avertizări pentru această dată.";
const MISSING_GEOMETRY_MESSAGE =
  "Există avertizări ANM, dar fluxul XML curent nu conține geometrii GIS parsabile.";
const PHENOMENON_FALLBACK = "conform textului avertizării ANM";

const statusElement = document.getElementById("status");
const datePicker = document.getElementById("alert-date-picker");
const featureDetailsElement = document.getElementById("feature-details");
const alertsSummaryElement = document.getElementById("alerts-summary");
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
  dataIndex = await loadIndex();
  datePicker.value = preferredInitialDate();
  datePicker.addEventListener("change", () => loadAlertsForDate(datePicker.value));

  await loadLatestAlerts(datePicker.value || "ultima rulare");
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

async function loadLatestAlerts(dateLabel) {
  setStatus("Se încarcă...");

  try {
    const response = await fetch("data/latest.geojson", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    renderAlertData(data, dateLabel);
  } catch (error) {
    console.error("latest.geojson could not be loaded", error);
    renderNoAlerts(EMPTY_MESSAGE);
  }
}

async function loadAlertsForDate(dateString) {
  if (!dateString) {
    renderNoAlerts(NO_ALERTS_MESSAGE);
    return;
  }

  setStatus("Se încarcă...");

  if (!isDateAvailable(dateString)) {
    renderNoAlerts(NO_ALERTS_MESSAGE);
    return;
  }

  const url = `data/${dateString}.geojson`;
  console.log("Loading alerts:", url);

  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    renderAlertData(data, dateString);
  } catch (error) {
    console.warn(`No alert file for ${dateString}`, error);
    renderNoAlerts(NO_ALERTS_MESSAGE);
  }
}

function renderAlertData(data, dateLabel) {
  const features = Array.isArray(data.features) ? data.features : [];
  console.log("GeoJSON loaded:", data);
  console.log("Feature count:", features.length);

  clearAlertsLayer();
  renderSelectedFeature(null);

  if (features.length === 0) {
    const message = emptyMessageFor(data.metadata || dataIndex);
    renderNoAlerts(message);
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

  renderStatus(features, dateLabel);
  renderAlertsSummary(features);
}

function renderNoAlerts(message) {
  clearAlertsLayer();
  renderSelectedFeature(null);
  renderAlertsSummary([]);
  map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  setStatus(message);
}

function renderStatus(features, dateLabel) {
  const alertCount = countDistinctAlerts(features);
  const featureCount = features.length;
  const alertPhrase = alertCount === 1 ? "1 avertizare activă" : `${alertCount} avertizări active`;
  const zonePhrase = featureCount === 1 ? "1 zonă afectată" : `${featureCount} zone afectate`;
  setStatus(`${alertPhrase} · ${zonePhrase} pentru ${dateLabel}`);
}

function renderSelectedFeature(feature) {
  if (!feature) {
    featureDetailsElement.classList.add("empty-state");
    featureDetailsElement.innerHTML = "Nicio zonă selectată.";
    return;
  }

  const props = feature.properties || {};
  const code = props.cod || "Verde";
  const phenomenon = props.fenomen_principal || PHENOMENON_FALLBACK;
  const source = sourceLabel(props.source || props.tip);

  featureDetailsElement.classList.remove("empty-state");
  featureDetailsElement.innerHTML = `
    <dl class="detail-list">
      ${detailRow("Județ", props.cod_judet || "")}
      ${detailRow("Cod", code)}
      ${detailRow("Fenomen", phenomenon)}
      ${detailRow("Valabilitate", formatValidity(props))}
      ${detailRow("Durată", formatDuration(props))}
      ${detailRow("Sursa", source)}
    </dl>
    <p class="alert-summary-text">${escapeHtml(shortFeatureText(props))}</p>
  `;
}

function renderAlertsSummary(features) {
  if (!features.length) {
    alertsSummaryElement.classList.add("empty-state");
    alertsSummaryElement.innerHTML = NO_ALERTS_MESSAGE;
    return;
  }

  alertsSummaryElement.classList.remove("empty-state");
  alertsSummaryElement.innerHTML = groupFeaturesByAlert(features)
    .map((group) => alertCardHtml(group))
    .join("");
}

function groupFeaturesByAlert(features) {
  const groups = new Map();
  for (const feature of features) {
    const props = feature.properties || {};
    const key = props.alert_id || `alert-${groups.size + 1}`;
    if (!groups.has(key)) {
      groups.set(key, { alertId: key, features: [] });
    }
    groups.get(key).features.push(feature);
  }
  return [...groups.values()];
}

function alertCardHtml(group) {
  const properties = group.features.map((feature) => feature.properties || {});
  const first = properties[0] || {};
  const codes = sortedUnique(properties.map((props) => props.cod).filter(Boolean), codeSortKey);
  const phenomena = sortedUnique(properties.map((props) => props.fenomen_principal).filter(Boolean));
  const zones = sortedUnique(properties.map((props) => props.cod_judet).filter(Boolean));
  const sources = sortedUnique(properties.map((props) => sourceLabel(props.source || props.tip)).filter(Boolean));
  const message = DOMPurify.sanitize(first.mesaj || "");

  return `
    <article class="alert-card">
      <h3>${escapeHtml(codes.join(" / ") || "Avertizare ANM")}</h3>
      <div class="alert-card-grid">
        <div><strong>Coduri:</strong> ${escapeHtml(codes.join(" / ") || "-")}</div>
        <div><strong>Interval:</strong> ${escapeHtml(formatValidity(first))}</div>
        <div><strong>Fenomene:</strong> ${escapeHtml(phenomena.join(" / ") || PHENOMENON_FALLBACK)}</div>
        <div><strong>Număr zone/județe:</strong> ${group.features.length}</div>
        <div><strong>Zone afectate:</strong> ${escapeHtml(zones.join(", ") || "-")}</div>
        <div><strong>Sursa:</strong> ${escapeHtml(sources.join(" / ") || "ANM")}</div>
      </div>
      <details>
        <summary>Vezi textul complet ANM</summary>
        <div class="anm-message">${message || "Fără mesaj ANM."}</div>
      </details>
    </article>
  `;
}

function onEachAlertFeature(feature, layer) {
  const props = feature.properties || {};
  const code = props.cod || "Verde";
  const codeClass = `cod-${slugify(code)}`;

  layer.bindPopup(`
    <span class="popup-title ${codeClass}">${escapeHtml(code)}</span>
    <div class="popup-meta">
      <strong>Județ:</strong> ${escapeHtml(props.cod_judet || "")}<br>
      <strong>Fenomen:</strong> ${escapeHtml(props.fenomen_principal || PHENOMENON_FALLBACK)}<br>
      <strong>Valabilitate:</strong> ${escapeHtml(formatValidity(props))}<br>
      <strong>Durată:</strong> ${escapeHtml(formatDuration(props))}<br>
      <strong>Sursa:</strong> ${escapeHtml(sourceLabel(props.source || props.tip))}
    </div>
    <div class="popup-message">${escapeHtml(shortFeatureText(props))}</div>
  `);

  layer.on("click", () => {
    renderSelectedFeature(feature);
  });
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

  return NO_ALERTS_MESSAGE;
}

function getAlertStyle(feature) {
  const props = feature.properties || {};
  const colorCode = String(props.culoare ?? "0").trim();
  const code = String(props.cod ?? "").toLowerCase();

  let color = "#2E7D32";
  let fillOpacity = 0.30;

  if (colorCode === "1" || code.includes("galben")) {
    color = "#FFD700";
    fillOpacity = 0.45;
  } else if (colorCode === "2" || code.includes("portocaliu")) {
    color = "#FF8C00";
    fillOpacity = 0.50;
  } else if (colorCode === "3" || code.includes("roșu") || code.includes("rosu")) {
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

function preferredInitialDate() {
  const dates = indexDates();
  const today = todayIso();
  if (dates.includes(today)) {
    return today;
  }
  return dates[dates.length - 1] || today;
}

function isDateAvailable(dateString) {
  return indexDates().includes(dateString);
}

function indexDates() {
  if (Array.isArray(dataIndex.dates) && dataIndex.dates.length > 0) {
    return dataIndex.dates;
  }

  if (!Array.isArray(dataIndex.files)) {
    return [];
  }

  return dataIndex.files
    .map((file) => {
      if (typeof file === "string") {
        return file.replace(/\.geojson$/, "");
      }
      return file?.date;
    })
    .filter(Boolean);
}

function countDistinctAlerts(features) {
  const alertIds = new Set(
    features
      .map((feature) => feature.properties?.alert_id)
      .filter(Boolean),
  );
  return alertIds.size || (features.length ? 1 : 0);
}

function detailRow(label, value) {
  return `
    <div class="detail-row">
      <dt class="detail-label">${escapeHtml(label)}</dt>
      <dd>${escapeHtml(value || "-")}</dd>
    </div>
  `;
}

function formatValidity(props) {
  return props.intervalul || [formatAlertDateTime(props.data_aparitiei), formatAlertDateTime(props.data_expirarii)]
    .filter(Boolean)
    .join(" – ");
}

function formatDuration(props) {
  const hours = props.durata_ore;
  const days = props.durata_zile_text;
  const hourText = hours ? `${hours} ${Number(hours) === 1 ? "oră" : "ore"}` : "";

  if (hourText && days) {
    return `${hourText} / ${days}`;
  }
  return hourText || days || "-";
}

function formatAlertDateTime(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const dayMonth = new Intl.DateTimeFormat("ro-RO", {
    day: "numeric",
    month: "long",
  }).format(date);
  const time = new Intl.DateTimeFormat("ro-RO", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);

  return `${dayMonth}, ora ${time}`;
}

function shortFeatureText(props) {
  const code = String(props.cod || "verde").toLowerCase();
  const phenomenon = props.fenomen_principal || PHENOMENON_FALLBACK;
  return `Această zonă este afectată de cod ${code} de ${phenomenon}.`;
}

function sourceLabel(source) {
  if (!source) {
    return "ANM";
  }
  return String(source).toLowerCase().includes("nowcasting") ? "ANM Nowcasting" : "ANM General";
}

function sortedUnique(values, sortFn) {
  const unique = [...new Set(values.filter(Boolean))];
  return unique.sort(sortFn);
}

function codeSortKey(a, b) {
  const order = { Verde: 0, Galben: 1, Portocaliu: 2, Roșu: 3 };
  return (order[a] ?? 99) - (order[b] ?? 99) || String(a).localeCompare(String(b), "ro");
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
