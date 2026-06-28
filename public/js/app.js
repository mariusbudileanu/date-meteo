const COLOR_STYLES = {
  Verde: { color: "#2E7D32", fillOpacity: 0.30 },
  Galben: { color: "#FFD700", fillOpacity: 0.40 },
  Portocaliu: { color: "#FF8C00", fillOpacity: 0.50 },
  Roșu: { color: "#FF0000", fillOpacity: 0.60 },
};

const EMPTY_MESSAGE = "Nu au fost emise avertizări în această dată.";
const MISSING_GEOMETRY_MESSAGE =
  "Există avertizări ANM, dar fluxul XML curent nu conține geometrii GIS parsabile.";
const statusElement = document.getElementById("status");
const datePicker = document.getElementById("alert-date-picker");
let dataIndex = { dates: [], files: [] };
let alertLayer = null;

const map = L.map("alerts-map", {
  center: [45.9432, 24.9668],
  zoom: 7,
});

setTimeout(() => {
  map.invalidateSize();
}, 200);

L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 19,
}).addTo(map);

addLegend();
start();

async function start() {
  datePicker.value = todayIso();
  datePicker.addEventListener("change", () => loadDate(datePicker.value));

  dataIndex = await loadIndex();
  await loadDate(datePicker.value);
}

async function loadIndex() {
  try {
    const response = await fetch(`data/index.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.warn("index.json could not be loaded", error);
    return { dates: [], files: [] };
  }
}

async function loadDate(dateValue) {
  if (alertLayer) {
    alertLayer.remove();
    alertLayer = null;
  }
  statusElement.textContent = "Se încarcă...";

  if (!dateValue) {
    statusElement.textContent = EMPTY_MESSAGE;
    return;
  }

  try {
    const response = await fetch(`data/${dateValue}.geojson?t=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const features = Array.isArray(data.features) ? data.features : [];

    if (features.length === 0) {
      statusElement.textContent = emptyMessageFor(data.metadata);
      map.setView([45.9432, 24.9668], 7);
      return;
    }

    alertLayer = L.geoJSON(data, {
      style: getAlertStyle,
      onEachFeature: onEachAlert,
    }).addTo(map);

    if (alertLayer.getLayers().length > 0) {
      map.fitBounds(alertLayer.getBounds(), {
        padding: [30, 30],
        maxZoom: 8,
      });
    } else {
      map.setView([45.9432, 24.9668], 7);
    }

    statusElement.textContent = `${features.length} ${
      features.length === 1 ? "avertizare" : "avertizări"
    } pentru ${dateValue}`;
  } catch (error) {
    console.warn(`GeoJSON for ${dateValue} could not be loaded`, error);
    statusElement.textContent = emptyMessageFor(dataIndex);
    map.setView([45.9432, 24.9668], 7);
  }
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
  const colorStyle = colorStyleFor(feature?.properties || {});
  return {
    color: colorStyle.color,
    fillColor: colorStyle.color,
    fillOpacity: colorStyle.fillOpacity,
    weight: 2,
    opacity: 0.95,
  };
}

function colorStyleFor(properties) {
  const rawColor = String(properties.culoare ?? "").trim();
  const cod = String(properties.cod ?? "").trim();

  if (rawColor === "1" || cod === "Galben") {
    return COLOR_STYLES.Galben;
  }
  if (rawColor === "2" || cod === "Portocaliu") {
    return COLOR_STYLES.Portocaliu;
  }
  if (rawColor === "3" || cod === "Roșu") {
    return COLOR_STYLES.Roșu;
  }

  return COLOR_STYLES.Verde;
}

function onEachAlert(feature, layer) {
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
    const rows = Object.entries(COLOR_STYLES)
      .map(
        ([label, style]) => `
          <div class="legend-row">
            <span class="legend-swatch" style="background:${style.color}"></span>
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
