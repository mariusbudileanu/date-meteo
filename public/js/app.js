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
const COD_COLOR = {
  0: "#34D399",
  1: "#FACC15",
  2: "#FB923C",
  3: "#F43F5E",
};
const COD_NAME = {
  0: "Verde",
  1: "Galben",
  2: "Portocaliu",
  3: "Roșu",
};

const statusElement = document.getElementById("status");
const datePicker = document.getElementById("alert-date-picker");
const latestButton = document.getElementById("latest-alerts-button");
const calendarElement = document.getElementById("calendar");
const featureDetailsElement = document.getElementById("feature-details");
const alertsSummaryElement = document.getElementById("alerts-summary");
const countySelector = document.getElementById("county-selector");
const countyHistoryElement = document.getElementById("county-history");
const downloadsTableBody = document.getElementById("downloads-table-body");

let dataIndex = { dates: {}, files: [] };
let historyStats = { counties: [] };
let alertsLayer = null;
let baseCountyLayer = null;
let selectedDate = "";
let viewYear = new Date().getFullYear();
let viewMonth = new Date().getMonth();

const map = L.map("alerts-map", {
  center: ROMANIA_CENTER,
  zoom: 7,
  minZoom: 5,
  maxZoom: 12,
});

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap, © CARTO",
  subdomains: "abcd",
  maxZoom: 19,
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
  const initialDate = dataIndex.latest_date || preferredInitialDate();
  selectedDate = initialDate;
  datePicker.value = initialDate || todayIso();
  setCalendarView(initialDate || todayIso());
  renderCalendar();

  datePicker.addEventListener("change", () => showDate(datePicker.value));
  latestButton.addEventListener("click", () => loadLatestAlerts());
  countySelector.addEventListener("change", () => renderCountyHistory(countySelector.value));

  await Promise.all([loadBaseCounties(), loadHistoryStats(), renderDownloads()]);
  await loadLatestAlerts();
}

async function loadIndex() {
  try {
    const response = await fetch("data/index.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const index = await response.json();
    if (Array.isArray(index.dates)) {
      index.dates = Object.fromEntries(index.dates.map((date) => [date, { file: `${date}.geojson` }]));
    }
    return { dates: {}, files: [], ...index };
  } catch (error) {
    console.warn("index.json could not be loaded", error);
    return { dates: {}, files: [] };
  }
}

async function loadLatestAlerts() {
  setStatus("Se încarcă...");

  try {
    const data = await fetchJson("data/latest.geojson");
    const dateLabel = data.metadata?.latest_for_date || data.metadata?.date || dataIndex.latest_date || selectedDate;
    renderAlertData(data, dateLabel);
  } catch (error) {
    console.error("latest.geojson could not be loaded", error);
    renderNoAlerts(EMPTY_MESSAGE, selectedDate || todayIso());
  }
}

async function showDate(dateString) {
  if (!dateString) {
    renderNoAlerts(NO_ALERTS_MESSAGE, "");
    return;
  }

  selectedDate = dateString;
  datePicker.value = dateString;
  setCalendarView(dateString);
  renderCalendar();

  if (!isDateAvailable(dateString)) {
    renderEmptyDay(dateString);
    return;
  }

  setStatus("Se încarcă...");
  const file = dataIndex.dates?.[dateString]?.file || `${dateString}.geojson`;

  try {
    const data = await fetchJson(`data/${file}`);
    renderAlertData(data, dateString);
  } catch (error) {
    console.warn(`No alert file for ${dateString}`, error);
    renderEmptyDay(dateString);
  }
}

function renderAlertData(data, dateLabel) {
  const features = Array.isArray(data.features) ? data.features : [];
  const metadata = data.metadata || {};
  const effectiveDate = dateLabel || metadata.date || selectedDate || dataIndex.latest_date || todayIso();
  selectedDate = effectiveDate;
  datePicker.value = effectiveDate;
  setCalendarView(effectiveDate);
  renderCalendar();

  clearAlertsLayer();
  renderSelectedFeature(null);

  if (features.length > 0) {
    alertsLayer = L.geoJSON(data, {
      style: getAlertStyle,
      onEachFeature: onEachAlertFeature,
    }).addTo(map);
    refitMapToCurrentLayer();
  } else {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  }

  const message = emptyMessageFor(metadata || dataIndex);
  if (features.length === 0 && !metadata.active_alerts?.length) {
    renderNoAlerts(message, effectiveDate);
    return;
  }

  renderStatus(metadata, features, effectiveDate);
  renderAlertsSummary(metadata, features);

  requestAnimationFrame(() => {
    refitMapToCurrentLayer();
  });

  setTimeout(() => {
    map.invalidateSize(true);
    refitMapToCurrentLayer();
  }, 1000);
}

function renderNoAlerts(message, dateLabel) {
  clearAlertsLayer();
  renderSelectedFeature(null);
  renderAlertsSummary({ active_alerts: [] }, []);
  map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  setStatus(message || (dateLabel ? `${NO_ALERTS_MESSAGE} pentru ${dateLabel}` : NO_ALERTS_MESSAGE));
}

function renderEmptyDay(dateString) {
  selectedDate = dateString;
  datePicker.value = dateString;
  setCalendarView(dateString);
  renderCalendar();
  renderNoAlerts(NO_ALERTS_MESSAGE, dateString);
}

function renderStatus(metadata, features, dateLabel) {
  const alertCount = safeNumber(metadata?.alert_count, countDistinctAlerts(features));
  const featureCount = safeNumber(metadata?.feature_count, features.length);
  setStatus(`${pluralAlerts(alertCount)} · ${pluralZones(featureCount)} pentru ${dateLabel}`);
}

function renderSelectedFeature(feature) {
  if (!feature) {
    featureDetailsElement.classList.add("empty-state");
    featureDetailsElement.innerHTML = "Nicio zonă selectată.";
    return;
  }

  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, props.culoare || 0);
  const phenomenon = props.fenomen_principal || PHENOMENON_FALLBACK;
  const source = sourceLabel(props.source || props.tip);

  featureDetailsElement.classList.remove("empty-state");
  featureDetailsElement.innerHTML = `
    <div class="selected-code">${codeChip(code)}</div>
    <dl class="detail-list">
      ${detailRow("Județ / zonă", props.judet_cod || props.cod_judet || "")}
      ${detailRow("Fenomen", phenomenon)}
      ${detailRow("Valabilitate", formatValidity(props))}
      ${detailRow("Durată", formatDuration(props))}
      ${detailRow("Sursa", source)}
    </dl>
    <p class="alert-summary-text">${escapeHtml(shortFeatureText(props))}</p>
  `;
}

function renderAlertsSummary(metadata, features) {
  const activeAlerts = Array.isArray(metadata?.active_alerts) ? metadata.active_alerts : [];
  const groups = activeAlerts.length ? activeAlerts : recordsFromFeatureGroups(features);

  if (!groups.length) {
    alertsSummaryElement.classList.add("empty-state");
    alertsSummaryElement.innerHTML = NO_ALERTS_MESSAGE;
    return;
  }

  alertsSummaryElement.classList.remove("empty-state");
  alertsSummaryElement.innerHTML = groups.map((record) => alertCardHtml(record)).join("");
}

function recordsFromFeatureGroups(features) {
  const groups = new Map();
  for (const feature of features) {
    const props = feature.properties || {};
    const key = props.alert_id || `alert-${groups.size + 1}`;
    if (!groups.has(key)) {
      groups.set(key, {
        alert_id: key,
        source: props.source || props.tip,
        interval_text: props.interval_text || props.intervalul,
        interval_start: props.interval_start,
        interval_end: props.interval_end || props.data_expirarii,
        durata_ore: props.durata_ore,
        cod_culoare_max: 0,
        fenomene_pe_cod: props.fenomene_pe_cod || {},
        judete_afectate: [],
        judete_count: 0,
        judete_culori: {},
        text_alerta_html: props.mesaj_html || props.mesaj || "",
        color_counts: {},
      });
    }
    const record = groups.get(key);
    const code = safeNumber(props.cod_culoare, props.culoare || 0);
    const zone = props.judet_cod || props.cod_judet;
    record.cod_culoare_max = Math.max(record.cod_culoare_max, code);
    if (zone) {
      record.judete_culori[zone] = code;
      if (code > 0) {
        record.judete_afectate.push(zone);
        record.color_counts[String(code)] = (record.color_counts[String(code)] || 0) + 1;
      }
    }
  }

  return [...groups.values()].map((record) => ({
    ...record,
    judete_afectate: sortedUnique(record.judete_afectate),
    judete_count: sortedUnique(record.judete_afectate).length,
  }));
}

function alertCardHtml(record) {
  const max = safeNumber(record.cod_culoare_max, 0);
  const message = DOMPurify.sanitize(record.text_alerta_html || "");
  const zones = Array.isArray(record.judete_afectate) ? record.judete_afectate : [];
  const previewZones = zones.slice(0, 28).join(", ");
  const overflow = zones.length > 28 ? ` și încă ${zones.length - 28}` : "";
  const phenomena = phenomenaHtml(record.fenomene_pe_cod || {});

  return `
    <article class="alert-card lvl-${max}">
      <div class="alert-card-head">
        <h3>${escapeHtml(sourceLabel(record.source))}</h3>
        ${codeChip(max)}
      </div>
      <div class="alert-card-grid">
        <div><strong>Coduri:</strong> ${colorCountsHtml(record.color_counts, record.judete_culori)}</div>
        <div><strong>Interval:</strong> ${escapeHtml(record.interval_text || formatRange(record.interval_start, record.interval_end))}</div>
        <div><strong>Fenomene:</strong> ${phenomena}</div>
        <div><strong>Zone afectate:</strong> ${pluralZones(safeNumber(record.judete_count, zones.length))}</div>
        <div class="span-2"><strong>Lista zonelor:</strong> ${escapeHtml(previewZones || "-")}${escapeHtml(overflow)}</div>
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
  const code = safeNumber(props.cod_culoare, props.culoare || 0);

  layer.bindPopup(`
    <div class="popup-code">${codeChip(code)}</div>
    <div class="popup-meta">
      <strong>Județ / zonă:</strong> ${escapeHtml(props.judet_cod || props.cod_judet || "")}<br>
      <strong>Fenomen:</strong> ${escapeHtml(props.fenomen_principal || PHENOMENON_FALLBACK)}<br>
      <strong>Valabilitate:</strong> ${escapeHtml(formatValidity(props))}<br>
      <strong>Durată:</strong> ${escapeHtml(formatDuration(props))}<br>
      <strong>Sursa:</strong> ${escapeHtml(sourceLabel(props.source || props.tip))}
    </div>
  `);

  layer.on({
    click: () => renderSelectedFeature(feature),
    mouseover: () => layer.setStyle({ weight: 3, fillOpacity: 0.72 }),
    mouseout: () => {
      if (alertsLayer) {
        alertsLayer.resetStyle(layer);
      }
    },
  });
}

async function loadBaseCounties() {
  try {
    const data = await fetchJson("data/judete.geojson");
    baseCountyLayer = L.geoJSON(data, {
      style: () => ({
        color: "#34D399",
        weight: 0.8,
        opacity: 0.35,
        fillColor: "#34D399",
        fillOpacity: 0.07,
      }),
      interactive: false,
    }).addTo(map);
    baseCountyLayer.bringToBack();
  } catch (error) {
    console.warn("judete.geojson could not be loaded", error);
  }
}

async function loadHistoryStats() {
  try {
    historyStats = await fetchJson("data/history_stats.json");
  } catch (error) {
    console.warn("history_stats.json could not be loaded", error);
    historyStats = { counties: [] };
  }

  const counties = Array.isArray(historyStats.counties) ? historyStats.counties : [];
  if (!counties.length) {
    countySelector.innerHTML = "";
    countyHistoryElement.classList.add("empty-state");
    countyHistoryElement.innerHTML = "Nu există statistici încărcate.";
    return;
  }

  countySelector.innerHTML = counties
    .map((county) => `<option value="${escapeHtml(county.judet_cod)}">${escapeHtml(county.judet_cod)}</option>`)
    .join("");
  renderCountyHistory(counties[0].judet_cod);
}

function renderCountyHistory(countyCode) {
  const counties = Array.isArray(historyStats.counties) ? historyStats.counties : [];
  const county = counties.find((item) => item.judet_cod === countyCode);

  if (!county) {
    countyHistoryElement.classList.add("empty-state");
    countyHistoryElement.innerHTML = "Nu există statistici pentru zona selectată.";
    return;
  }

  countyHistoryElement.classList.remove("empty-state");
  countyHistoryElement.innerHTML = `
    <div class="history-stat">
      <span>${escapeHtml(county.judet_cod)}</span>
      ${codeChip(county.max_color)}
    </div>
    <div class="history-grid">
      <div><strong>Avertizări arhivate:</strong> ${escapeHtml(county.alert_count)}</div>
      <div><strong>Ultima expirare:</strong> ${escapeHtml(formatAlertDateTime(county.last_alert_end) || "-")}</div>
      <div><strong>Distribuție coduri:</strong> ${colorCountsHtml(county.color_counts)}</div>
    </div>
  `;
}

async function renderDownloads() {
  try {
    const manifest = await fetchJson("istoric/index.json");
    const months = Array.isArray(manifest.months) ? manifest.months : [];
    if (!months.length) {
      downloadsTableBody.innerHTML = `<tr><td colspan="5">Nu există arhivă disponibilă.</td></tr>`;
      return;
    }

    downloadsTableBody.innerHTML = months
      .map(
        (month) => `
          <tr>
            <td>${escapeHtml(month.month)}</td>
            <td>${escapeHtml(month.alert_count)}</td>
            <td>${escapeHtml(month.first_alert || "-")} - ${escapeHtml(month.last_alert || "-")}</td>
            <td>${codeChip(month.max_color)}</td>
            <td><a href="${escapeHtml(month.path)}" download>Descarcă CSV</a></td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    console.warn("istoric/index.json could not be loaded", error);
    downloadsTableBody.innerHTML = `<tr><td colspan="5">Nu există arhivă disponibilă.</td></tr>`;
  }
}

function renderCalendar() {
  const first = new Date(viewYear, viewMonth, 1);
  const days = new Date(viewYear, viewMonth + 1, 0).getDate();
  const offset = (first.getDay() + 6) % 7;
  const weekdays = ["L", "Ma", "Mi", "J", "V", "S", "D"]
    .map((day) => `<div class="cal-weekday">${day}</div>`)
    .join("");
  let cells = "";

  for (let index = 0; index < offset; index += 1) {
    cells += `<div class="cal-cell empty"></div>`;
  }

  for (let day = 1; day <= days; day += 1) {
    const iso = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const info = dataIndex.dates?.[iso];
    const code = safeNumber(info?.max_color, 0);
    const codeClass = info ? `cod-${code}` : "no-data";
    const futureClass = dataIndex.today && iso > dataIndex.today ? "future" : "";
    const selectedClass = iso === selectedDate ? "selected" : "";
    const title = info
      ? `${info.alert_count} avertizări · ${info.feature_count} zone`
      : "fără date";
    cells += `
      <button type="button" class="cal-cell ${codeClass} ${futureClass} ${selectedClass}"
        data-iso="${iso}" title="${escapeHtml(title)}">${day}</button>
    `;
  }

  calendarElement.innerHTML = `
    <div class="cal-head">
      <button type="button" class="icon-button" id="cal-prev" aria-label="Luna anterioară">‹</button>
      <span>${first.toLocaleDateString("ro-RO", { month: "long", year: "numeric" })}</span>
      <button type="button" class="icon-button" id="cal-next" aria-label="Luna următoare">›</button>
    </div>
    <div class="cal-grid">${weekdays}${cells}</div>
  `;

  document.getElementById("cal-prev").addEventListener("click", () => {
    viewMonth -= 1;
    if (viewMonth < 0) {
      viewMonth = 11;
      viewYear -= 1;
    }
    renderCalendar();
  });

  document.getElementById("cal-next").addEventListener("click", () => {
    viewMonth += 1;
    if (viewMonth > 11) {
      viewMonth = 0;
      viewYear += 1;
    }
    renderCalendar();
  });

  calendarElement.querySelectorAll("[data-iso]").forEach((button) => {
    button.addEventListener("click", () => showDate(button.dataset.iso));
  });
}

function setCalendarView(dateString) {
  const parsed = parseIsoDate(dateString);
  if (!parsed) {
    return;
  }
  viewYear = parsed.getFullYear();
  viewMonth = parsed.getMonth();
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
  const code = safeNumber(props.cod_culoare, props.culoare || 0);
  const color = COD_COLOR[code] || COD_COLOR[0];

  return {
    color,
    fillColor: color,
    weight: 1.5,
    opacity: 1,
    fillOpacity: code === 3 ? 0.62 : 0.55,
  };
}

function addLegend() {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const container = L.DomUtil.create("div", "leaflet-control legend");
    const rows = [0, 1, 2, 3]
      .map(
        (code) => `
          <div class="legend-row">
            <span class="legend-swatch" style="background:${COD_COLOR[code]}"></span>
            <span>${COD_NAME[code]}</span>
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
  const today = dataIndex.today || todayIso();
  if (dates.includes(today)) {
    return today;
  }
  return dates[dates.length - 1] || today;
}

function isDateAvailable(dateString) {
  return Boolean(dataIndex.dates?.[dateString]);
}

function indexDates() {
  if (dataIndex.dates && !Array.isArray(dataIndex.dates)) {
    return Object.keys(dataIndex.dates).sort();
  }

  if (!Array.isArray(dataIndex.files)) {
    return [];
  }

  return dataIndex.files
    .map((file) => (typeof file === "string" ? file.replace(/\.geojson$/, "") : file?.date))
    .filter(Boolean)
    .sort();
}

function countDistinctAlerts(features) {
  const alertIds = new Set(features.map((feature) => feature.properties?.alert_id).filter(Boolean));
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
  return props.interval_text || props.intervalul || formatRange(props.interval_start || props.data_aparitiei, props.interval_end || props.data_expirarii);
}

function formatRange(start, end) {
  return [formatAlertDateTime(start), formatAlertDateTime(end)].filter(Boolean).join(" – ");
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

  const date = new Date(String(value).length === 16 ? `${value}:00` : value);
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
  const code = String(props.cod_culoare_nume || props.cod || "verde").toLowerCase();
  const phenomenon = props.fenomen_principal || PHENOMENON_FALLBACK;
  return `Această zonă este afectată de cod ${code} de ${phenomenon}.`;
}

function sourceLabel(source) {
  if (!source) {
    return "ANM";
  }
  return String(source).toLowerCase().includes("nowcasting") ? "ANM Nowcasting" : "ANM General";
}

function colorCountsHtml(colorCounts, fallbackColors = {}) {
  const counts = { ...(colorCounts || {}) };
  if (!Object.keys(counts).length && fallbackColors) {
    for (const color of Object.values(fallbackColors)) {
      const code = String(color);
      if (safeNumber(code, 0) > 0) {
        counts[code] = (counts[code] || 0) + 1;
      }
    }
  }

  const entries = Object.entries(counts)
    .map(([code, count]) => [safeNumber(code, 0), count])
    .filter(([code]) => code > 0)
    .sort((a, b) => a[0] - b[0]);

  if (!entries.length) {
    return codeChip(0);
  }

  return entries.map(([code, count]) => `${codeChip(code)} <span class="count-badge">${escapeHtml(count)}</span>`).join(" ");
}

function phenomenaHtml(phenomenaByCode) {
  const entries = Object.entries(phenomenaByCode || {})
    .map(([code, text]) => [safeNumber(code, 0), text])
    .filter(([code, text]) => code > 0 && text)
    .sort((a, b) => a[0] - b[0]);

  if (!entries.length) {
    return escapeHtml(PHENOMENON_FALLBACK);
  }

  return entries
    .map(([code, text]) => `<span class="phenomenon-line">${codeChip(code)} ${escapeHtml(text)}</span>`)
    .join("");
}

function codeChip(code) {
  const normalized = safeNumber(code, 0);
  return `<span class="cod cod-${normalized}">${escapeHtml(COD_NAME[normalized] || "Verde")}</span>`;
}

function pluralAlerts(count) {
  const n = safeNumber(count, 0);
  if (n === 1) {
    return "1 avertizare activă";
  }
  if (n >= 20) {
    return `${n} de avertizări active`;
  }
  return `${n} avertizări active`;
}

function pluralZones(count) {
  const n = safeNumber(count, 0);
  if (n === 1) {
    return "1 zonă afectată";
  }
  if (n >= 20) {
    return `${n} de zone afectate`;
  }
  return `${n} zone afectate`;
}

function sortedUnique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "ro"));
}

function todayIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoDate(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
