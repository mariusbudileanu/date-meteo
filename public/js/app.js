const ROMANIA_CENTER = [45.9432, 24.9668];
const ROMANIA_BOUNDS = [
  [43.5, 20.0],
  [48.8, 30.0],
];

const NO_ALERTS_MESSAGE = "Nu există avertizări arhivate pentru această dată.";
const NO_NOWCASTING_MESSAGE = "Nu există avertizări nowcasting active în acest moment.";
const ARCHIVE_ONLY_MESSAGE = "Există înregistrări în arhivă pentru această dată, dar nu există hartă GeoJSON disponibilă.";
const PHENOMENON_FALLBACK = "conform textului avertizării ANM";
const COD_COLOR = { 1: "#FDE047", 2: "#FB923C", 3: "#F43F5E" };
const COD_NAME = { 1: "Galben", 2: "Portocaliu", 3: "Roșu" };
const COUNTY_CODES = new Set([
  "AB", "AR", "AG", "B", "BC", "BH", "BN", "BR", "BT", "BV", "BZ", "CJ", "CL", "CS", "CT", "CV",
  "DB", "DJ", "GJ", "GL", "GR", "HD", "HR", "IF", "IL", "IS", "MH", "MM", "MS", "NT", "OT",
  "PH", "SB", "SJ", "SM", "SV", "TL", "TM", "TR", "VL", "VN", "VS",
]);

const PHENOMENA = [
  { value: "all", label: "Toate fenomenele" },
  { value: "heat", label: "Temperaturi extreme / caniculă" },
  { value: "rain", label: "Ploi" },
  { value: "storm", label: "Vijelii" },
  { value: "snow", label: "Ninsori" },
  { value: "blizzard", label: "Viscol" },
  { value: "fog", label: "Ceață" },
  { value: "ice", label: "Polei" },
  { value: "other", label: "Alte fenomene" },
];

const statusElement = document.getElementById("status");
const lastUpdatedElement = document.getElementById("last-updated");
const daySummaryElement = document.getElementById("day-summary");
const latestButton = document.getElementById("latest-alerts-button");
const calendarElement = document.getElementById("calendar");
const sourceFilter = document.getElementById("source-filter");
const phenomenonFilter = document.getElementById("phenomenon-filter");
const severityFilter = document.getElementById("severity-filter");
const mapModeSelect = document.getElementById("map-mode");
const nowcastingToggle = document.getElementById("nowcasting-toggle");
const overlapFilter = document.getElementById("overlap-filter");
const resetFiltersButton = document.getElementById("reset-filters-button");
const visibleAlertChipsElement = document.getElementById("visible-alert-chips");
const featureDetailsElement = document.getElementById("feature-details");
const alertsSummaryElement = document.getElementById("alerts-summary");
const compareSection = document.getElementById("compare-section");
const compareAlertsElement = document.getElementById("compare-alerts");
const nowcastingSection = document.getElementById("nowcasting-section");
const nowcastingSummaryElement = document.getElementById("nowcasting-summary");
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
let currentWeather = null;
let currentData = null;
let currentDateLabel = "";
let currentFeatures = [];
let currentRecords = [];
let currentIndexes = emptyIndexes();
let alertsById = new Map();
let featuresByCounty = new Map();
let featuresByAlertId = new Map();
let featuresByPhenomenon = new Map();
let featuresBySeverity = new Map();
let visibleAlertIds = new Set();
let selectedCountyKey = "";
let selectedCounty = "";
let selectedPhenomenon = "all";
let selectedSeverity = "all";
let selectedSourceMode = "general";
let mapMode = "max";
let showOnlyOverlaps = false;

const map = L.map("alerts-map", { center: ROMANIA_CENTER, zoom: 7, minZoom: 5, maxZoom: 12 });

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap, © CARTO",
  subdomains: "abcd",
  maxZoom: 19,
}).addTo(map);

map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
setTimeout(() => map.invalidateSize(true), 500);
setTimeout(() => map.invalidateSize(true), 1500);

populatePhenomenonFilter();
addLegend();
start();

async function start() {
  dataIndex = await loadIndex();
  renderLastUpdated(dataIndex.generated_at_utc);

  try {
    currentWeather = await fetchJson("data/current_weather.json");
  } catch (error) {
    currentWeather = null;
  }

  const initialDate = dataIndex.latest_date || preferredInitialDate();
  selectedDate = initialDate;
  setCalendarView(initialDate || todayIso());
  renderCalendar();
  renderEmptyDashboard(initialDate || todayIso(), "Se încarcă avertizările...");

  latestButton?.addEventListener("click", () => loadLatestAlerts());
  sourceFilter?.addEventListener("change", () => {
    if (nowcastingToggle) nowcastingToggle.checked = sourceFilter.value !== "general";
    updateDashboard();
  });
  nowcastingToggle?.addEventListener("change", () => {
    if (sourceFilter) sourceFilter.value = nowcastingToggle.checked ? "all" : "general";
    updateDashboard();
  });
  phenomenonFilter?.addEventListener("change", () => updateDashboard());
  severityFilter?.addEventListener("change", () => updateDashboard());
  mapModeSelect?.addEventListener("change", () => updateDashboard());
  overlapFilter?.addEventListener("change", () => updateDashboard());
  resetFiltersButton?.addEventListener("click", () => resetDashboardFilters());
  countySelector?.addEventListener("change", () => renderCountyHistory(countySelector.value));

  await Promise.all([loadBaseCounties(), loadHistoryStats(), renderDownloads()]);
  await loadLatestAlerts();
}

async function loadIndex() {
  try {
    const response = await fetch("data/index.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = await response.json();
    if (Array.isArray(index.dates)) {
      index.dates = Object.fromEntries(index.dates.map((date) => [date, { file: `${date}.geojson`, has_geojson: true }]));
    }
    return { dates: {}, files: [], ...index };
  } catch (error) {
    console.warn("index.json could not be loaded", error);
    return { dates: {}, files: [] };
  }
}

async function loadLatestAlerts() {
  setStatus("Se încarcă ultimele avertizări ANM...");
  try {
    const data = applyDemoOverlap(await fetchJson("data/latest.geojson"));
    const dateLabel = data.metadata?.latest_for_date || data.metadata?.date || dataIndex.latest_date || selectedDate;
    renderAlertData(data, dateLabel, true);
  } catch (error) {
    console.error("latest.geojson could not be loaded", error);
    renderEmptyDay(selectedDate || todayIso());
  }
}

async function showDate(dateString) {
  if (!dateString) {
    renderEmptyDay("");
    return;
  }

  selectedDate = dateString;
  setCalendarView(dateString);
  renderCalendar();

  if (!isDateAvailable(dateString)) {
    renderEmptyDay(dateString);
    return;
  }

  setStatus("Se încarcă avertizările ANM pentru data selectată...");
  const entry = dataIndex.dates?.[dateString] || {};
  const file = entry.file;
  if (entry.has_archive && !entry.has_geojson && !file) {
    renderArchiveOnlyDay(dateString, entry);
    return;
  }
  if (!file) {
    renderEmptyDay(dateString);
    return;
  }
  try {
    const data = applyDemoOverlap(await fetchJson(`data/${file}`));
    renderAlertData(data, dateString, true);
  } catch (error) {
    console.warn(`No alert file for ${dateString}`, error);
    renderEmptyDay(dateString);
  }
}

function renderAlertData(data, dateLabel, resetVisibility) {
  currentData = data;
  currentDateLabel = dateLabel || data.metadata?.date || selectedDate || todayIso();
  currentFeatures = Array.isArray(data.features) ? data.features : [];
  currentRecords = normalizedActiveRecords(data.metadata || {}, currentFeatures);

  if (resetVisibility) {
    visibleAlertIds = new Set(currentRecords.map((record) => record.alert_id).filter(Boolean));
  }
  currentIndexes = buildIndexes(currentRecords, currentFeatures);
  syncIndexAliases();

  selectedDate = currentDateLabel;
  selectedCountyKey = "";
  selectedCounty = "";
  setCalendarView(selectedDate);
  renderCalendar();
  updateDashboard();
}

function syncControlState() {
  selectedSourceMode = sourceFilter?.value || "general";
  selectedPhenomenon = phenomenonFilter?.value || "all";
  selectedSeverity = severityFilter?.value || "all";
  mapMode = mapModeSelect?.value || "max";
  showOnlyOverlaps = Boolean(overlapFilter?.checked);
  selectedCounty = selectedCountyKey;
}

function nowcastingEnabled() {
  return selectedSourceMode !== "general" || Boolean(nowcastingToggle?.checked);
}

function sourceMatchesFeature(feature) {
  const isNowcasting = isNowcastingFeature(feature);
  if (selectedSourceMode === "nowcasting") return isNowcasting;
  if (selectedSourceMode === "all") return true;
  if (nowcastingToggle?.checked) return true;
  return !isNowcasting;
}

function syncIndexAliases() {
  alertsById = currentIndexes.alertsById;
  featuresByCounty = currentIndexes.featuresByCounty;
  featuresByAlertId = currentIndexes.featuresByAlertId;
  featuresByPhenomenon = currentIndexes.featuresByPhenomenon;
  featuresBySeverity = currentIndexes.featuresBySeverity;
  currentIndexes.visibleAlertIds = visibleAlertIds;
}

function resetDashboardFilters() {
  if (sourceFilter) sourceFilter.value = "general";
  if (nowcastingToggle) nowcastingToggle.checked = false;
  if (phenomenonFilter) phenomenonFilter.value = "all";
  if (severityFilter) severityFilter.value = "all";
  if (mapModeSelect) mapModeSelect.value = "max";
  if (overlapFilter) overlapFilter.checked = false;
  visibleAlertIds = new Set(currentRecords.map((record) => record.alert_id).filter(Boolean));
  syncIndexAliases();
  selectedCountyKey = "";
  selectedCounty = "";
  updateDashboard();
}

function updateDashboard() {
  syncControlState();
  const visibleFeatures = getVisibleFeatures({ respectVisibleAlertIds: true });
  const visibleRecords = getVisibleRecords({ respectVisibleAlertIds: true });
  const cardRecords = getVisibleRecords({ respectVisibleAlertIds: false });

  renderDaySummary(visibleFeatures, selectedDate);
  renderStatus(visibleFeatures, selectedDate);
  renderMap(visibleFeatures);
  renderVisibleAlertChips(visibleRecords);
  renderAlertsSummary(cardRecords);
  renderCompareSection(cardRecords);
  renderNowcastingSection(cardRecords.filter(isNowcastingRecord));
  updateLegendActiveState();

  if (selectedCountyKey) {
    const countyFeatures = getVisibleFeaturesForCounty(selectedCountyKey);
    if (countyFeatures.length) renderSelectedCountyPanel(selectedCountyKey, countyFeatures);
    else renderSelectedEmpty();
  } else {
    renderSelectedEmpty();
  }
  publishDebugState(visibleFeatures, cardRecords);
}

function publishDebugState(visibleFeatures, cardRecords) {
  const aggregateFeatures = aggregateFeaturesByCounty(visibleFeatures);
  const byCounty = Object.fromEntries(
    aggregateFeatures.map((feature) => [
      feature.properties.county_key,
      {
        countyName: feature.properties.county_name,
        alertCount: feature.properties.alert_count,
        maxCode: feature.properties.max_code,
        secondaryCode: feature.properties.secondary_code,
        hasOverlap: feature.properties.has_overlap,
        hasNowcasting: feature.properties.has_nowcasting,
        clickPoint: featureClickPoint(feature),
        alertIds: (feature.properties.features || []).map((item) => item.properties?.alert_id),
        phenomena: (feature.properties.features || []).map((item) => item.properties?.fenomen_principal),
        codes: (feature.properties.features || []).map((item) => item.properties?.cod_culoare),
      },
    ])
  );

  const debugState = {
    date: currentDateLabel,
    source: selectedSourceMode,
    selectedSourceMode,
    nowcastingEnabled: nowcastingEnabled(),
    phenomenon: selectedPhenomenon,
    severity: selectedSeverity,
    mode: mapMode,
    showOnlyOverlaps,
    selectedCounty,
    visibleAlertIds: [...visibleAlertIds],
    alertIds: currentRecords.map((record) => record.alert_id),
    cardAlertIds: cardRecords.map((record) => record.alert_id),
    compareCardIds: cardRecords.slice(0, 4).map((record) => record.alert_id),
    compareVisible: mapMode === "compare" && cardRecords.length > 0,
    visibleFeatureCount: visibleFeatures.length,
    indexCounts: {
      alertsById: alertsById.size,
      featuresByCounty: featuresByCounty.size,
      featuresByAlertId: featuresByAlertId.size,
      featuresByPhenomenon: featuresByPhenomenon.size,
      featuresBySeverity: featuresBySeverity.size,
    },
    byCounty,
  };

  window.__meteoDashboard = {
    ...debugState,
    pointForLatLng(lat, lng) {
      const point = map.latLngToContainerPoint([lat, lng]);
      const rect = map.getContainer().getBoundingClientRect();
      return {
        x: Math.round(rect.left + point.x),
        y: Math.round(rect.top + point.y),
      };
    },
  };
  publishDebugNode(debugState);
}

function featureClickPoint(feature) {
  try {
    const bounds = L.geoJSON(feature).getBounds();
    const center = bounds.getCenter();
    const point = map.latLngToContainerPoint(center);
    const rect = map.getContainer().getBoundingClientRect();
    return {
      lat: center.lat,
      lng: center.lng,
      x: Math.round(rect.left + point.x),
      y: Math.round(rect.top + point.y),
    };
  } catch (error) {
    return null;
  }
}

function publishDebugNode(state) {
  let node = document.getElementById("dashboard-debug-state");
  if (!node) {
    node = document.createElement("script");
    node.type = "application/json";
    node.id = "dashboard-debug-state";
    document.body.appendChild(node);
  }
  node.textContent = JSON.stringify(state);
}

function renderEmptyDay(dateString) {
  currentData = null;
  currentDateLabel = dateString;
  currentFeatures = [];
  currentRecords = [];
  currentIndexes = emptyIndexes();
  visibleAlertIds = new Set();
  syncIndexAliases();
  selectedCountyKey = "";
  selectedCounty = "";
  selectedDate = dateString;
  setCalendarView(dateString);
  renderCalendar();
  renderEmptyDashboard(dateString, NO_ALERTS_MESSAGE);
}

function renderArchiveOnlyDay(dateString, info = {}) {
  currentData = null;
  currentDateLabel = dateString;
  currentFeatures = [];
  currentRecords = [];
  currentIndexes = emptyIndexes();
  visibleAlertIds = new Set();
  syncIndexAliases();
  selectedCountyKey = "";
  selectedCounty = "";
  selectedDate = dateString;
  setCalendarView(dateString);
  renderCalendar();
  clearAlertsLayer();
  map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  renderDaySummary([], dateString);
  renderSelectedEmpty(ARCHIVE_ONLY_MESSAGE);
  alertsSummaryElement.classList.add("empty-state");
  alertsSummaryElement.innerHTML = `${escapeHtml(ARCHIVE_ONLY_MESSAGE)}${info.alert_count ? `<br>${escapeHtml(pluralAnmAlerts(info.alert_count))} în arhiva CSV.` : ""}`;
  renderVisibleAlertChips([]);
  renderCompareSection([]);
  renderNowcastingSection([]);
  setStatus(ARCHIVE_ONLY_MESSAGE);
  publishDebugState([], []);
}

function renderEmptyDashboard(dateString, message) {
  clearAlertsLayer();
  map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  renderDaySummary([], dateString);
  renderSelectedEmpty(message === NO_ALERTS_MESSAGE ? "Nu există avertizări pentru data selectată." : "Selectează un județ colorat pentru detalii.");
  alertsSummaryElement.classList.add("empty-state");
  alertsSummaryElement.innerHTML = message;
  renderVisibleAlertChips([]);
  renderCompareSection([]);
  renderNowcastingSection([]);
  setStatus(message);
  publishDebugState([], []);
}

function getVisibleFeatures({ respectVisibleAlertIds }) {
  const filtered = currentFeatures.filter((feature) => {
    const props = feature.properties || {};
    const alertId = props.alert_id || "";
    const sourceOk = sourceMatchesFeature(feature);
    const phenomenonOk = selectedPhenomenon === "all" || normalizePhenomenon(feature) === selectedPhenomenon;
    const severityOk = selectedSeverity === "all" || String(safeNumber(props.cod_culoare, 0)) === selectedSeverity;
    const alertOk = !respectVisibleAlertIds || !alertId || visibleAlertIds.has(alertId);
    return sourceOk && phenomenonOk && severityOk && alertOk;
  });

  if (!showOnlyOverlaps) return filtered;

  const overlapCountyKeys = new Set(
    aggregateFeaturesByCounty(filtered)
      .filter((feature) => safeNumber(feature.properties?.alert_count, 0) > 1)
      .map((feature) => feature.properties?.county_key)
  );
  return filtered.filter((feature) => overlapCountyKeys.has(countyKey(feature)));
}

function getVisibleRecords({ respectVisibleAlertIds }) {
  const filtered = currentRecords.filter((record) => {
    const alertOk = !respectVisibleAlertIds || !record.alert_id || visibleAlertIds.has(record.alert_id);
    return alertOk && sourceMatchesRecord(record) && phenomenonMatchesRecord(record) && severityMatchesRecord(record);
  });
  if (!showOnlyOverlaps) return filtered;

  const overlapAlertIds = new Set();
  for (const feature of aggregateFeaturesByCounty(getVisibleFeatures({ respectVisibleAlertIds }))) {
    if (safeNumber(feature.properties?.alert_count, 0) <= 1) continue;
    for (const item of feature.properties?.features || []) {
      if (item.properties?.alert_id) overlapAlertIds.add(item.properties.alert_id);
    }
  }
  return filtered.filter((record) => overlapAlertIds.has(record.alert_id));
}

function getCountyKey(feature) {
  return countyKey(feature);
}

function getVisibleFeaturesForCounty(key) {
  if (!key) return [];
  return getVisibleFeatures({ respectVisibleAlertIds: true }).filter((feature) => getCountyKey(feature) === key);
}

function summarizeCountyFeatures(features) {
  const records = uniqueFeaturesByAlert(features);
  const maxCode = maxCodeFromFeatures(features);
  const phenomena = sortedUnique(records.map((feature) => cleanDisplayText(compactPhenomenon(featureText(feature)), "conform textului ANM")));
  const countyName = cleanDisplayText(
    features[0]?.properties?.judet_nume || features[0]?.properties?.zona_nume || features[0]?.properties?.judet_cod,
    "Zonă afectată"
  );
  return {
    countyName,
    records,
    alertCount: countDistinctAlerts(features),
    maxCode,
    phenomena,
    hasNowcasting: features.some(isNowcastingFeature),
    isNowcastingOnly: features.length > 0 && features.every(isNowcastingFeature),
  };
}

function buildCountyPopupHtml(countyKey, features) {
  const summary = summarizeCountyFeatures(features);
  const first = summary.records[0] || features[0];
  const firstProps = first?.properties || {};
  const title = summary.isNowcastingOnly ? "Zonă nowcasting" : summary.countyName;
  const lines = [`<strong>${escapeHtml(title)}</strong>`];

  if (summary.isNowcastingOnly && summary.countyName !== "Zonă afectată") {
    lines.push(`<span>Județ asociat: ${escapeHtml(summary.countyName)}</span>`);
  }

  if (summary.alertCount <= 1) {
    const code = safeNumber(firstProps.cod_culoare, summary.maxCode);
    lines.push(`<span>${escapeHtml(pluralActiveAlerts(summary.alertCount || 1))}</span>`);
    lines.push(`<span>Cod: ${escapeHtml(COD_NAME[code] || "-")}</span>`);
    lines.push(`<span>Fenomen: ${escapeHtml(cleanDisplayText(compactPhenomenon(featureText(first)), "conform textului ANM"))}</span>`);
    lines.push(`<span>${summary.isNowcastingOnly ? "Valabil până la" : "Valabilitate"}: ${escapeHtml(cleanDisplayText(formatValidity(firstProps), "interval indisponibil"))}</span>`);
  } else {
    lines.push(`<span>${escapeHtml(pluralActiveAlerts(summary.alertCount))}</span>`);
    lines.push(`<span>Cod maxim: ${escapeHtml(COD_NAME[summary.maxCode] || "-")}</span>`);
    lines.push(`<span>Fenomene: ${escapeHtml(summary.phenomena.join(", ") || "conform textului ANM")}</span>`);
    if (summary.hasNowcasting) lines.push("<span>Include alertă nowcasting</span>");
    lines.push("<span>Click pentru detalii în panoul lateral</span>");
  }

  return `<div class="compact-popup">${lines.join("")}</div>`;
}

function sourceMatchesRecord(record) {
  const isNowcasting = isNowcastingRecord(record);
  if (selectedSourceMode === "nowcasting") return isNowcasting;
  if (selectedSourceMode === "all") return true;
  if (nowcastingToggle?.checked) return true;
  return !isNowcasting;
}

function phenomenonMatchesRecord(record) {
  if (selectedPhenomenon === "all") return true;
  if (record.features?.some((feature) => normalizePhenomenon(feature) === selectedPhenomenon)) return true;
  return normalizePhenomenon(recordAsFeature(record)) === selectedPhenomenon;
}

function severityMatchesRecord(record) {
  if (selectedSeverity === "all") return true;
  if (record.features?.some((feature) => String(safeNumber(feature.properties?.cod_culoare, 0)) === selectedSeverity)) return true;
  return String(safeNumber(record.cod_culoare_max, 0)) === selectedSeverity;
}

function renderDaySummary(features, dateLabel) {
  const alertCount = countDistinctAlerts(features);
  const zoneCount = countDistinctCounties(features);
  const maxCode = maxCodeFromFeatures(features);
  const phenomena = activePhenomenaLabels(features);
  const dateText = formatDisplayDate(dateLabel || selectedDate || todayIso());
  const updated = formatUtcStamp(dataIndex.generated_at_utc) || "necunoscută";

  if (!features.length) {
    daySummaryElement.innerHTML = `
      ${summaryCard("Data selectată", dateText)}
      ${summaryCard("Avertizări ANM", pluralAnmAlerts(0))}
      ${summaryCard("Zone afectate", pluralZones(0))}
      ${summaryCard("Cod maxim", "Fără cod")}
      ${summaryCard("Fenomene active", "Nicio avertizare")}
      ${summaryCard("Ultima actualizare", updated)}
    `;
    return;
  }

  daySummaryElement.innerHTML = `
    ${summaryCard("Data selectată", dateText)}
    ${summaryCard("Avertizări ANM", pluralAnmAlerts(alertCount))}
    ${summaryCard("Zone afectate", pluralZones(zoneCount))}
    ${summaryCard("Cod maxim", `Cod maxim: ${COD_NAME[maxCode] || "-"}`, `summary-code severity-${maxCode}`)}
    ${summaryCard("Fenomene active", phenomena || PHENOMENON_FALLBACK)}
    ${summaryCard("Ultima actualizare", updated)}
  `;
}

function renderStatus(features, dateLabel) {
  if (!features.length) {
    setStatus(NO_ALERTS_MESSAGE);
    return;
  }
  const nowcastingCount = features.filter(isNowcastingFeature).length;
  const nowcastingText = nowcastingCount ? ` · ${nowcastingCount} zone nowcasting afișate` : "";
  setStatus(`${formatDisplayDate(dateLabel)} · ${pluralAnmAlerts(countDistinctAlerts(features))} · ${pluralZones(countDistinctCounties(features))}${nowcastingText}`);
}

function renderMap(features) {
  clearAlertsLayer();
  if (!features.length) {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
    return;
  }

  const aggregateFeatures = aggregateFeaturesByCounty(features);
  alertsLayer = L.geoJSON({ type: "FeatureCollection", features: aggregateFeatures }, {
    style: aggregateStyle,
    onEachFeature: onEachAggregateFeature,
  }).addTo(map);

  requestAnimationFrame(() => refitMapToCurrentLayer());
  setTimeout(() => {
    map.invalidateSize(true);
    refitMapToCurrentLayer();
  }, 500);
}

function aggregateFeaturesByCounty(features) {
  const groups = new Map();
  for (const feature of features) {
    const key = countyKey(feature);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(feature);
  }

  return [...groups.entries()].map(([key, countyFeatures]) => {
    const sorted = [...countyFeatures].sort((a, b) => safeNumber(b.properties?.cod_culoare, 0) - safeNumber(a.properties?.cod_culoare, 0));
    const representative = sorted[0];
    const codes = sortedUnique(sorted.map((feature) => safeNumber(feature.properties?.cod_culoare, 0)).filter((code) => code > 0)).sort((a, b) => b - a);
    const alertIds = sortedUnique(sorted.map((feature) => feature.properties?.alert_id).filter(Boolean));
    const hasNowcasting = sorted.some(isNowcastingFeature);
    return {
      type: "Feature",
      geometry: representative.geometry,
      properties: {
        aggregate: true,
        county_key: key,
        county_name: representative.properties?.judet_nume || representative.properties?.judet_cod || key,
        features: sorted,
        alert_count: alertIds.length || sorted.length,
        max_code: codes[0] || 0,
        secondary_code: codes[1] || 0,
        has_overlap: (alertIds.length || sorted.length) > 1,
        has_nowcasting: hasNowcasting,
      },
    };
  });
}

function aggregateStyle(feature) {
  const props = feature.properties || {};
  const code = safeNumber(props.max_code, 0);
  const secondary = safeNumber(props.secondary_code, 0);
  const color = COD_COLOR[code] || "#94a3b8";
  const outline = props.has_overlap ? (COD_COLOR[secondary] || "#ffffff") : color;
  return {
    color: outline,
    fillColor: color,
    weight: props.has_overlap ? 3.4 : 1.5,
    opacity: 1,
    dashArray: props.has_overlap ? "5 3" : props.has_nowcasting ? "3 4" : null,
    fillOpacity: code === 3 ? 0.64 : 0.56,
    className: ["alert-county", props.county_key ? `county-${props.county_key}` : "", props.has_overlap ? "has-overlap" : "", props.has_nowcasting ? "has-nowcasting" : ""].filter(Boolean).join(" "),
  };
}

function onEachAggregateFeature(feature, layer) {
  const props = feature.properties || {};
  layer.once("add", () => {
    const element = layer.getElement?.();
    if (!element) return;
    element.classList.add("alert-county");
    if (props.county_key) element.classList.add(`county-${props.county_key}`);
    if (props.has_overlap) element.classList.add("has-overlap");
    if (props.has_nowcasting) element.classList.add("has-nowcasting");
  });
  layer.bindPopup(() => {
    const countyFeatures = getVisibleFeaturesForCounty(props.county_key || "");
    return buildCountyPopupHtml(props.county_key || "", countyFeatures.length ? countyFeatures : (props.features || []));
  });
  layer.on({
    click: () => {
      selectedCountyKey = props.county_key || "";
      selectedCounty = selectedCountyKey;
      const countyFeatures = getVisibleFeaturesForCounty(selectedCountyKey);
      renderSelectedCountyPanel(selectedCountyKey, countyFeatures.length ? countyFeatures : (props.features || []));
    },
    mouseover: () => layer.setStyle({ weight: props.has_overlap ? 4.4 : 2.6, fillOpacity: 0.72 }),
    mouseout: () => alertsLayer?.resetStyle(layer),
  });
}

function renderSelectedEmpty(message = "Selectează un județ de pe hartă pentru detalii despre avertizările active.") {
  featureDetailsElement.classList.add("empty-state");
  featureDetailsElement.innerHTML = escapeHtml(message);
}

function renderSelectedCountyPanel(countyKey, features) {
  renderCountyPanel(features, countyKey);
}

function renderCountyPanel(features, countyKey = "") {
  if (!features.length) {
    renderSelectedEmpty("Nu există avertizări pentru data selectată.");
    return;
  }

  const summary = summarizeCountyFeatures(features);
  const countyName = summary.countyName;
  const generalFeatures = features.filter((feature) => !isNowcastingFeature(feature));
  const nowcastingFeatures = features.filter(isNowcastingFeature);
  const generalRecords = uniqueFeaturesByAlert(generalFeatures);
  const nowcastingRecords = uniqueFeaturesByAlert(nowcastingFeatures);

  let weatherHtml = "";
  if (selectedDate === todayIso() || selectedDate === dataIndex.latest_date) {
    if (currentWeather && currentWeather.by_county && currentWeather.by_county[countyName]) {
      const stations = currentWeather.by_county[countyName];
      const stationList = stations.map(s => {
          const temp = s.temperature_c !== null ? `${s.temperature_c}°C` : "N/A";
          const desc = s.weather ? `, ${s.weather.toLowerCase()}` : "";
          return `<li>${escapeHtml(s.station_name)}: ${temp}${escapeHtml(desc)}</li>`;
      }).join("");
      const updated = currentWeather.fetched_at_utc ? formatUtcStamp(currentWeather.fetched_at_utc) : "necunoscut";
      weatherHtml = `
        <div class="weather-panel">
          <h3>Starea vremii acum în județ</h3>
          <p class="weather-meta">Actualizat: ${escapeHtml(updated)}</p>
          <ul class="weather-stations">
            ${stationList}
          </ul>
        </div>
      `;
    } else {
      weatherHtml = `<p class="weather-meta">Nu există observații curente disponibile pentru acest județ.</p>`;
    }
  } else {
    weatherHtml = `<p class="weather-meta">Observațiile meteo curente sunt disponibile doar pentru ziua curentă.</p>`;
  }

  featureDetailsElement.classList.remove("empty-state");
  featureDetailsElement.innerHTML = `
    <div class="selected-zone">
      <span>Județ: ${escapeHtml(countyName)}</span>
      ${codeChip(summary.maxCode)}
    </div>
    <div class="county-summary-line">
      <strong>Avertizări active: ${escapeHtml(String(summary.alertCount))}</strong>
      <span>Cod maxim: ${escapeHtml(COD_NAME[summary.maxCode] || "-")}</span>
      ${summary.alertCount > 1 ? `<span class="overlap-badge">alerte suprapuse</span>` : ""}
    </div>
    <div class="county-alert-list">
      ${generalRecords.map((feature, index) => countyAlertHtml(feature, index + 1)).join("")}
    </div>
    ${nowcastingRecords.length ? `
      <div class="nowcasting-county-block">
        <h3>Nowcasting activ</h3>
        ${nowcastingRecords.map((feature, index) => countyAlertHtml(feature, index + 1)).join("")}
      </div>
    ` : ""}
    ${weatherHtml}
  `;
}

function countyAlertHtml(feature, index) {
  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, 0);
  const phenomenon = cleanDisplayText(featureText(feature), "conform textului ANM");
  const interval = cleanDisplayText(formatValidity(props), "interval indisponibil");
  return `
    <article class="county-alert-item">
      <h3>${index}. Cod ${escapeHtml((COD_NAME[code] || "-").toLowerCase())} — ${escapeHtml(compactPhenomenon(phenomenon))}</h3>
      <dl class="detail-list compact-detail-list">
        ${detailRow("Interval", interval)}
        ${detailRow("Fenomen", phenomenon)}
        ${props.zona_nume ? detailRow("Zonă", cleanDisplayText(props.zona_nume, "")) : ""}
        ${detailRow("Sursa", sourceLabel(props.source || props.tip))}
      </dl>
    </article>
  `;
}

function renderAlertsSummary(records) {
  const generalRecords = records.filter((record) => !isNowcastingRecord(record));
  if (!generalRecords.length) {
    alertsSummaryElement.classList.add("empty-state");
    alertsSummaryElement.innerHTML = NO_ALERTS_MESSAGE;
    return;
  }

  alertsSummaryElement.classList.remove("empty-state");
  alertsSummaryElement.innerHTML = generalRecords.map((record) => alertCardHtml(record)).join("");
  attachAlertCardEvents();
}

function renderVisibleAlertChips(records) {
  if (!visibleAlertChipsElement) return;
  const visibleRecords = records.filter((record) => visibleAlertIds.has(record.alert_id));
  if (!visibleRecords.length) {
    visibleAlertChipsElement.innerHTML = `<span class="empty-chip">Nu există alerte afișate.</span>`;
    return;
  }
  visibleAlertChipsElement.innerHTML = visibleRecords
    .map((record) => alertChipHtml(record))
    .join("");
}

function alertChipHtml(record) {
  const max = safeNumber(record.cod_culoare_max, 0);
  const sourcePrefix = isNowcastingRecord(record) ? "Nowcasting · " : `Cod ${String(COD_NAME[max] || "-").toLowerCase()} · `;
  return `
    <span class="visible-alert-chip lvl-${max} ${isNowcastingRecord(record) ? "nowcasting" : ""}">
      ${escapeHtml(sourcePrefix)}${escapeHtml(recordPrimaryPhenomenon(record))}
    </span>
  `;
}

function renderNowcastingSection(records) {
  if (!nowcastingSection || !nowcastingSummaryElement) return;
  const show = nowcastingEnabled();
  nowcastingSection.hidden = !show;
  if (!show) {
    nowcastingSummaryElement.innerHTML = "";
    return;
  }
  if (!records.length) {
    nowcastingSummaryElement.classList.add("empty-state");
    nowcastingSummaryElement.innerHTML = escapeHtml(NO_NOWCASTING_MESSAGE);
    return;
  }
  nowcastingSummaryElement.classList.remove("empty-state");
  nowcastingSummaryElement.innerHTML = records.map((record) => alertCardHtml(record)).join("");
  attachAlertCardEvents();
}

function renderCompareSection(records) {
  if (!compareSection || !compareAlertsElement) return;
  const show = mapMode === "compare" && records.length > 0;
  compareSection.hidden = !show;
  if (!show) {
    compareAlertsElement.innerHTML = "";
    return;
  }

  const visibleRecords = records.slice(0, 4);
  const overflow = records.length > visibleRecords.length
    ? `<p class="compare-overflow-note">Sunt disponibile ${escapeHtml(records.length)} avertizări; folosește filtrele pentru izolare.</p>`
    : "";
  compareAlertsElement.innerHTML = `
    ${visibleRecords.map((record) => compareAlertCardHtml(record)).join("")}
    ${overflow}
  `;
  attachCompareEvents();
}

function compareAlertCardHtml(record) {
  const max = safeNumber(record.cod_culoare_max, 0);
  const phenomenon = recordPrimaryPhenomenon(record);
  return `
    <article class="compare-alert-card lvl-${max} ${isNowcastingRecord(record) ? "nowcasting-card" : ""}" data-alert-id="${escapeHtml(record.alert_id)}">
      <div class="alert-card-head">
        <div>
          <p class="section-kicker">${sourceBadge(record.source)}</p>
          <h3>${escapeHtml(COD_NAME[max] || "-")} — ${escapeHtml(phenomenon)}</h3>
        </div>
        ${codeChip(max)}
      </div>
      <div class="compare-meta">
        <span>${escapeHtml(record.interval_text || formatRange(record.interval_start, record.interval_end) || "-")}</span>
        <span>${escapeHtml(pluralZones(safeNumber(record.judete_count, 0)))}</span>
      </div>
      <button type="button" class="mini-button compare-card-action compare-isolate" data-alert-id="${escapeHtml(record.alert_id)}">Vezi această hartă</button>
    </article>
  `;
}

function attachCompareEvents() {
  document.querySelectorAll(".compare-isolate").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.alertId;
      if (!id) return;
      visibleAlertIds = new Set([id]);
      syncIndexAliases();
      if (mapModeSelect) mapModeSelect.value = "alert";
      updateDashboard();
    });
  });
}

function alertCardHtml(record) {
  const max = safeNumber(record.cod_culoare_max, 0);
  const message = DOMPurify.sanitize(record.text_alerta_html || "");
  const checked = visibleAlertIds.has(record.alert_id) ? "checked" : "";
  const phenomenon = recordPrimaryPhenomenon(record);
  const geometryNote = record.features?.length ? "" : `<p class="geometry-note">Alertă activă în metadata, fără geometrii desenabile.</p>`;
  return `
    <article class="alert-card lvl-${max} ${isNowcastingRecord(record) ? "nowcasting-card" : ""}" data-alert-id="${escapeHtml(record.alert_id)}">
      <div class="alert-card-head">
        <div>
          <p class="section-kicker">${sourceBadge(record.source)}</p>
          <h3>Cod maxim: ${escapeHtml(COD_NAME[max] || "-")} — ${escapeHtml(phenomenon)}</h3>
        </div>
        ${codeChip(max)}
      </div>
      <div class="incident-controls">
        <label class="alert-visible-label">
          <input type="checkbox" class="alert-visible" data-alert-id="${escapeHtml(record.alert_id)}" ${checked}>
          <span>Afișează pe hartă</span>
        </label>
        <button type="button" class="mini-button alert-isolate" data-alert-id="${escapeHtml(record.alert_id)}">Izolează</button>
        <button type="button" class="mini-button alert-hide" data-alert-id="${escapeHtml(record.alert_id)}">Ascunde</button>
      </div>
      ${geometryNote}
      <div class="alert-card-grid">
        <div><span class="field-label">Fenomen</span><strong>${escapeHtml(phenomenon)}</strong></div>
        <div><span class="field-label">Interval</span>${escapeHtml(record.interval_text || formatRange(record.interval_start, record.interval_end) || "-")}</div>
        <div><span class="field-label">Zone afectate</span>${escapeHtml(pluralZones(safeNumber(record.judete_count, 0)))}</div>
        <div><span class="field-label">Sursa</span>${escapeHtml(sourceLabel(record.source))}</div>
        <div><span class="field-label">Coduri prezente</span>${presentCodesHtml(record)}</div>
        <div class="span-2"><span class="field-label">Fenomene pe cod</span>${phenomenaListHtml(record.fenomene_pe_cod)}</div>
      </div>
      <details>
        <summary>Vezi textul complet publicat de ANM</summary>
        <div class="anm-message">${message || "Fără mesaj ANM."}</div>
      </details>
    </article>
  `;
}

function attachAlertCardEvents() {
  document.querySelectorAll(".alert-visible").forEach((input) => {
    input.addEventListener("change", () => {
      const id = input.dataset.alertId;
      if (!id) return;
      if (input.checked) visibleAlertIds.add(id);
      else visibleAlertIds.delete(id);
      syncIndexAliases();
      updateDashboard();
    });
  });
  document.querySelectorAll(".alert-isolate").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.alertId;
      if (!id) return;
      visibleAlertIds = new Set([id]);
      syncIndexAliases();
      if (mapModeSelect) mapModeSelect.value = "alert";
      updateDashboard();
    });
  });
  document.querySelectorAll(".alert-hide").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.alertId;
      if (!id) return;
      visibleAlertIds.delete(id);
      syncIndexAliases();
      updateDashboard();
    });
  });
}

function normalizedActiveRecords(metadata, features) {
  const activeAlerts = Array.isArray(metadata?.active_alerts) ? metadata.active_alerts : [];
  const grouped = activeAlerts.length ? activeAlerts : recordsFromFeatureGroups(features);
  const featureGroups = groupFeaturesByAlert(features);
  return grouped.map((record) => normalizeAlertRecord(record, featureGroups.get(record.alert_id) || []));
}

function normalizeAlertRecord(record, features = []) {
  const zones = sortedUnique(features.map((feature) => feature.properties?.judet_cod).filter(Boolean));
  const zoneColors = {};
  for (const feature of features) {
    const code = feature.properties?.judet_cod;
    if (code) zoneColors[code] = safeNumber(feature.properties?.cod_culoare, 0);
  }
  const colorCounts = countsFromFeatures(features) || record.color_counts || {};
  const maxCode = Math.max(safeNumber(record.cod_culoare_max, 0), maxCodeFromFeatures(features));
  return {
    ...record,
    alert_id: record.alert_id || "",
    source: record.source || features[0]?.properties?.source || "general",
    cod_culoare_max: maxCode,
    fenomene_pe_cod: record.fenomene_pe_cod || phenomenaByCodeFromFeatures(features),
    judete_afectate: zones.length ? zones : (Array.isArray(record.judete_afectate) ? record.judete_afectate : []),
    judete_count: zones.length || safeNumber(record.judete_count, 0),
    judete_culori: Object.keys(zoneColors).length ? zoneColors : (record.judete_culori || {}),
    color_counts: Object.keys(colorCounts).length ? colorCounts : (record.color_counts || {}),
    text_alerta_html: record.text_alerta_html || "",
    features,
  };
}

function recordsFromFeatureGroups(features) {
  const groups = groupFeaturesByAlert(features);
  return [...groups.entries()].map(([alertId, groupedFeatures]) => {
    const first = groupedFeatures[0]?.properties || {};
    return {
      alert_id: alertId,
      source: first.source || first.tip,
      interval_text: first.interval_text || first.intervalul,
      interval_start: first.interval_start,
      interval_end: first.interval_end || first.data_expirare,
      durata_ore: first.durata_ore,
      cod_culoare_max: maxCodeFromFeatures(groupedFeatures),
      fenomene_pe_cod: phenomenaByCodeFromFeatures(groupedFeatures),
      text_alerta_html: first.mesaj_html || first.mesaj || "",
    };
  });
}

function groupFeaturesByAlert(features) {
  const groups = new Map();
  for (const feature of features) {
    const key = feature.properties?.alert_id || `alert-${groups.size + 1}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(feature);
  }
  return groups;
}

function buildIndexes(records, features) {
  const indexes = emptyIndexes();
  for (const record of records) indexes.alertsById.set(record.alert_id, record);
  for (const feature of features) {
    const key = countyKey(feature);
    const alertId = feature.properties?.alert_id || "";
    const phenomenon = normalizePhenomenon(feature);
    const severity = String(safeNumber(feature.properties?.cod_culoare, 0));
    if (!indexes.featuresByCounty.has(key)) indexes.featuresByCounty.set(key, []);
    if (alertId && !indexes.featuresByAlertId.has(alertId)) indexes.featuresByAlertId.set(alertId, []);
    if (!indexes.featuresByPhenomenon.has(phenomenon)) indexes.featuresByPhenomenon.set(phenomenon, []);
    if (!indexes.featuresBySeverity.has(severity)) indexes.featuresBySeverity.set(severity, []);
    indexes.featuresByCounty.get(key).push(feature);
    if (alertId) indexes.featuresByAlertId.get(alertId).push(feature);
    indexes.featuresByPhenomenon.get(phenomenon).push(feature);
    indexes.featuresBySeverity.get(severity).push(feature);
  }
  indexes.visibleAlertIds = visibleAlertIds;
  return indexes;
}

function emptyIndexes() {
  return {
    alertsById: new Map(),
    featuresByCounty: new Map(),
    featuresByAlertId: new Map(),
    featuresByPhenomenon: new Map(),
    featuresBySeverity: new Map(),
    visibleAlertIds: new Set(),
  };
}

function applyDemoOverlap(data) {
  const params = new URLSearchParams(window.location.search);
  const demo = params.get("demo");
  if (demo === "nowcasting" || demo === "overlap") return applyDemoNowcastingFixture(data);
  return data;
}

function applyDemoNowcastingFixture(data) {
  const clone = JSON.parse(JSON.stringify(data));
  const originalFeatures = Array.isArray(clone.features) ? clone.features : [];
  const albaTemplate = originalFeatures.find((feature) => feature.properties?.judet_cod === "AB" && !isNowcastingFeature(feature));
  if (!albaTemplate) return clone;

  const start = new Date();
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  const intervalStart = localIsoMinute(start);
  const intervalEnd = localIsoMinute(end);
  const intervalText = `${formatAlertDateTime(intervalStart)} - ${formatAlertDateTime(intervalEnd)}`;
  const retainedFeatures = originalFeatures.filter((feature) => feature.properties?.judet_cod !== "AB");

  const general = JSON.parse(JSON.stringify(albaTemplate));
  general.properties = {
    ...general.properties,
    alert_id: "demo_ab_heat_orange",
    source: "general",
    tip: "general",
    judet_cod: "AB",
    judet_nume: "Alba",
    cod_culoare: 2,
    cod_culoare_nume: "Portocaliu",
    fenomen_principal: "caniculă",
    fenomene_vizate: "caniculă",
    mesaj_plain: "Alertă demo locală pentru testarea suprapunerii dintre General ANM și Nowcasting.",
    mesaj_html: "<p>Alertă demo locală: cod portocaliu de caniculă pentru județul Alba.</p>",
    interval_text: intervalText,
    interval_start: intervalStart,
    interval_end: intervalEnd,
    data_aparitiei: intervalStart,
    data_expirare: intervalEnd,
    durata_ore: 1,
    demo_fixture: "nowcasting",
  };

  const nowcasting = JSON.parse(JSON.stringify(albaTemplate));
  nowcasting.properties = {
    ...nowcasting.properties,
    alert_id: "demo_ab_nowcasting_yellow",
    source: "nowcasting",
    tip: "nowcasting",
    judet_cod: "AB",
    judet_nume: "Alba",
    zona_nume: "Alba - zona montană",
    cod_culoare: 1,
    cod_culoare_nume: "Galben",
    fenomen_principal: "averse torențiale / descărcări electrice",
    fenomene_vizate: "averse / vijelii",
    mesaj_plain: "Alertă demo locală pentru testarea nowcasting: averse torențiale, descărcări electrice și vijelii.",
    mesaj_html: "<p>Alertă demo locală nowcasting: cod galben de averse torențiale, descărcări electrice și vijelii în Alba - zona montană.</p>",
    interval_text: intervalText,
    interval_start: intervalStart,
    interval_end: intervalEnd,
    data_aparitiei: intervalStart,
    data_expirare: intervalEnd,
    durata_ore: 1,
    demo_fixture: "nowcasting",
  };

  const features = [...retainedFeatures, general, nowcasting];
  clone.features = features;

  clone.metadata = clone.metadata || {};
  clone.metadata.demo_nowcasting = true;
  clone.metadata.active_alerts = (Array.isArray(clone.metadata.active_alerts) ? clone.metadata.active_alerts : [])
    .filter((record) => !String(record.alert_id || "").startsWith("demo_ab_"));
  clone.metadata.active_alerts.push({
    alert_id: "demo_ab_heat_orange",
    source: "general",
    interval_text: intervalText,
    interval_start: intervalStart,
    interval_end: intervalEnd,
    durata_ore: 1,
    cod_culoare_max: 2,
    fenomene_pe_cod: { 2: "caniculă" },
    judete_afectate: ["AB"],
    judete_count: 1,
    judete_culori: { AB: 2 },
    color_counts: { 2: 1 },
    text_alerta_html: "<p>Alertă demo locală: cod portocaliu de caniculă pentru județul Alba.</p>",
  });
  clone.metadata.active_alerts.push({
    alert_id: "demo_ab_nowcasting_yellow",
    source: "nowcasting",
    interval_text: intervalText,
    interval_start: intervalStart,
    interval_end: intervalEnd,
    durata_ore: 1,
    cod_culoare_max: 1,
    fenomene_pe_cod: { 1: "averse torențiale / descărcări electrice" },
    judete_afectate: ["AB"],
    judete_count: 1,
    judete_culori: { AB: 1 },
    color_counts: { 1: 1 },
    text_alerta_html: "<p>Alertă demo locală nowcasting: cod galben de averse torențiale, descărcări electrice și vijelii în Alba - zona montană.</p>",
  });
  clone.metadata.alert_count = countDistinctAlerts(features);
  clone.metadata.feature_count = features.length;
  clone.metadata.nowcasting_count = features.filter(isNowcastingFeature).length;
  return clone;
}

async function loadBaseCounties() {
  try {
    const data = await fetchJson("data/judete.geojson");
    baseCountyLayer = L.geoJSON(data, {
      style: () => ({ color: "#64748B", weight: 0.8, opacity: 0.42, fillColor: "#64748B", fillOpacity: 0.035 }),
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

  const counties = (Array.isArray(historyStats.counties) ? historyStats.counties : [])
    .filter((county) => COUNTY_CODES.has(String(county.judet_cod || "")))
    .sort((a, b) => String(a.judet_nume || a.judet_cod).localeCompare(String(b.judet_nume || b.judet_cod), "ro"));

  if (!counties.length || !countySelector) {
    countyHistoryElement.classList.add("empty-state");
    countyHistoryElement.innerHTML = "Nu există statistici încărcate.";
    return;
  }

  countySelector.innerHTML = counties
    .map((county) => `<option value="${escapeHtml(county.judet_cod)}">${escapeHtml(county.judet_nume || county.judet_cod)}</option>`)
    .join("");
  renderCountyHistory(counties[0].judet_cod);
}

function renderCountyHistory(countyCode) {
  const counties = (Array.isArray(historyStats.counties) ? historyStats.counties : []).filter((county) => COUNTY_CODES.has(String(county.judet_cod || "")));
  const county = counties.find((item) => item.judet_cod === countyCode);
  if (!county) {
    countyHistoryElement.classList.add("empty-state");
    countyHistoryElement.innerHTML = "Nu există statistici pentru județul selectat.";
    return;
  }
  const counts = county.color_counts || {};
  const total = safeNumber(county.alert_count, 0);
  countyHistoryElement.classList.remove("empty-state");
  countyHistoryElement.innerHTML = `
    <div class="history-stat">
      <span>${escapeHtml(county.judet_nume || county.judet_cod)}</span>
      ${codeChip(county.max_color)}
    </div>
    <div class="history-grid">
      <div><span class="field-label">Total avertizări arhivate</span><strong>${escapeHtml(total)}</strong></div>
      <div><span class="field-label">Cod galben</span><strong>${escapeHtml(safeNumber(counts["1"], 0))}</strong></div>
      <div><span class="field-label">Cod portocaliu</span><strong>${escapeHtml(safeNumber(counts["2"], 0))}</strong></div>
      <div><span class="field-label">Cod roșu</span><strong>${escapeHtml(safeNumber(counts["3"], 0))}</strong></div>
      <div><span class="field-label">Ultima alertă</span><strong>${escapeHtml(formatAlertDateTime(county.last_alert_end) || "-")}</strong></div>
      <div><span class="field-label">Cod maxim istoric</span>${codeChip(county.max_color)}</div>
    </div>
    ${total < 10 ? `<p class="history-note">Istoricul este încă la început și va deveni mai relevant după mai multe rulări.</p>` : ""}
  `;
}

async function renderDownloads() {
  if (!downloadsTableBody) return;
  try {
    const manifest = await fetchJson("istoric/index.json");
    const months = Array.isArray(manifest.months) ? manifest.months : [];
    if (!months.length) {
      downloadsTableBody.innerHTML = `<tr><td colspan="5">Nu există arhivă disponibilă.</td></tr>`;
      return;
    }
    downloadsTableBody.innerHTML = months
      .map((month) => `
        <tr>
          <td>${escapeHtml(month.month)}</td>
          <td>${escapeHtml(month.alert_count)}</td>
          <td>${escapeHtml(month.first_alert || "-")} - ${escapeHtml(month.last_alert || "-")}</td>
          <td>${codeChip(month.max_color)}</td>
          <td><a href="${escapeHtml(month.path)}" download>Descarcă CSV</a></td>
        </tr>
      `)
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
  const weekdays = ["L", "Ma", "Mi", "J", "V", "S", "D"].map((day) => `<div class="cal-weekday">${day}</div>`).join("");
  let cells = "";

  for (let index = 0; index < offset; index += 1) cells += `<div class="cal-cell empty"></div>`;

  for (let day = 1; day <= days; day += 1) {
    const iso = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const info = dataIndex.dates?.[iso];
    const code = safeNumber(info?.max_color, 0);
    const codeClass = info && code > 0
      ? `cod-${code}`
      : info?.has_nowcasting
        ? "has-nowcasting"
        : info?.has_archive && !info?.has_geojson
          ? "archived-only"
          : "no-data";
    const selectedClass = iso === selectedDate ? "selected" : "";
    const title = info
      ? info.has_archive && !info.has_geojson
        ? `${pluralAnmAlerts(info.alert_count)} în arhivă · fără hartă GeoJSON`
        : `${pluralAnmAlerts(info.alert_count)} · ${info.nowcasting_count || 0} nowcasting · cod maxim ${COD_NAME[code] || "-"}`
      : "fără date";
    const ncBadge = info?.has_nowcasting ? `<span class="nc-badge" aria-hidden="true">NC</span>` : "";
    cells += `<button type="button" class="cal-cell ${codeClass} ${selectedClass}" data-iso="${iso}" title="${escapeHtml(title)}">${day}${ncBadge}</button>`;
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
    if (viewMonth < 0) { viewMonth = 11; viewYear -= 1; }
    renderCalendar();
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    viewMonth += 1;
    if (viewMonth > 11) { viewMonth = 0; viewYear += 1; }
    renderCalendar();
  });
  calendarElement.querySelectorAll("[data-iso]").forEach((button) => button.addEventListener("click", () => showDate(button.dataset.iso)));
}

function addLegend() {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const container = L.DomUtil.create("div", "leaflet-control legend dashboard-legend");
    L.DomEvent.disableClickPropagation(container);
    const rows = [1, 2, 3].map((code) => `
      <button type="button" class="legend-row legend-filter" data-severity="${code}">
        <span class="legend-swatch" style="background:${COD_COLOR[code]}"></span>
        <span>${COD_NAME[code]}</span>
      </button>
    `).join("");
    container.innerHTML = `<div class="legend-title">Filtru cod</div><button type="button" class="legend-row legend-filter" data-severity="all"><span class="legend-swatch neutral"></span><span>Toate codurile</span></button>${rows}`;
    setTimeout(() => {
      container.querySelectorAll(".legend-filter").forEach((button) => {
        button.addEventListener("click", () => {
          if (severityFilter) severityFilter.value = button.dataset.severity || "all";
          updateDashboard();
        });
      });
      updateLegendActiveState();
    }, 0);
    return container;
  };
  legend.addTo(map);
}

function updateLegendActiveState() {
  const active = selectedSeverity || "all";
  document.querySelectorAll(".legend-filter").forEach((button) => {
    button.classList.toggle("active", (button.dataset.severity || "all") === active);
  });
}

function refitMapToCurrentLayer() {
  map.invalidateSize(true);
  if (alertsLayer && alertsLayer.getLayers().length > 0 && alertsLayer.getBounds().isValid()) {
    map.fitBounds(alertsLayer.getBounds(), { padding: [30, 30], maxZoom: 8 });
  } else {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  }
}

function clearAlertsLayer() {
  if (alertsLayer) {
    map.removeLayer(alertsLayer);
    alertsLayer = null;
  }
}

function populatePhenomenonFilter() {
  if (!phenomenonFilter) return;
  phenomenonFilter.innerHTML = PHENOMENA.map((item) => `<option value="${item.value}">${item.label}</option>`).join("");
}

function normalizePhenomenon(feature) {
  const text = stripDiacritics(featureText(feature)).toLowerCase();
  if (/(canicula|caldura|temperaturi|tropical|disconfort termic|arsita)/.test(text)) return "heat";
  if (/(ploaie|ploi|averse|precipitatii|torential|cantitati de apa)/.test(text)) return "rain";
  if (/(vijelie|vijelii|furtuna|descarcari electrice|grindina|instabilitate)/.test(text)) return "storm";
  if (/(ninsoare|ninsori|zapada)/.test(text)) return "snow";
  if (/(viscol|spulberat)/.test(text)) return "blizzard";
  if (/(ceata|vizibilitate redusa)/.test(text)) return "fog";
  if (/(polei|chiciura|gheata|inghet)/.test(text)) return "ice";
  return "other";
}

function featureText(feature) {
  const props = feature.properties || {};
  return props.fenomen_principal || props.fenomene_vizate || props.mesaj_plain || props.mesaj || PHENOMENON_FALLBACK;
}

function recordAsFeature(record) {
  return {
    properties: {
      source: record.source,
      cod_culoare: record.cod_culoare_max,
      fenomen_principal: recordPrimaryPhenomenon(record),
      alert_id: record.alert_id,
    },
  };
}

function activePhenomenaLabels(features) {
  const labels = sortedUnique(features.map((feature) => phenomenonLabel(normalizePhenomenon(feature))).filter(Boolean));
  return labels.join(" · ");
}

function phenomenonLabel(value) {
  return PHENOMENA.find((item) => item.value === value)?.label.replace(" / caniculă", "") || "Alte fenomene";
}

function countyKey(feature) {
  const props = feature.properties || {};
  return props.judet_cod || props.cod_judet || props.judet_nume || props.alert_id || "zona";
}

function uniqueFeaturesByAlert(features) {
  const seen = new Set();
  return features.filter((feature) => {
    const id = feature.properties?.alert_id || `${feature.properties?.judet_cod}-${feature.properties?.cod_culoare}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function countDistinctAlerts(features) {
  return new Set(features.map((feature) => feature.properties?.alert_id).filter(Boolean)).size || (features.length ? 1 : 0);
}

function countDistinctCounties(features) {
  return new Set(features.map(countyKey).filter(Boolean)).size;
}

function maxCodeFromFeatures(features) {
  return features.reduce((max, feature) => Math.max(max, safeNumber(feature.properties?.cod_culoare, 0)), 0);
}

function countsFromFeatures(features) {
  const counts = {};
  for (const feature of features) {
    const code = safeNumber(feature.properties?.cod_culoare, 0);
    if (code > 0) counts[String(code)] = (counts[String(code)] || 0) + 1;
  }
  return counts;
}

function phenomenaByCodeFromFeatures(features) {
  const result = {};
  for (const feature of features) {
    const code = safeNumber(feature.properties?.cod_culoare, 0);
    if (code > 0 && !result[String(code)]) result[String(code)] = featureText(feature);
  }
  return result;
}

function recordPrimaryPhenomenon(record) {
  const entries = Object.entries(record.fenomene_pe_cod || {}).sort((a, b) => safeNumber(b[0], 0) - safeNumber(a[0], 0));
  const text = entries[0]?.[1] || (record.features?.[0] ? featureText(record.features[0]) : PHENOMENON_FALLBACK);
  return compactPhenomenon(text);
}

function isNowcastingFeature(feature) {
  return String(feature.properties?.source || feature.properties?.tip || "").toLowerCase().includes("nowcasting");
}

function isNowcastingRecord(record) {
  return String(record.source || "").toLowerCase().includes("nowcasting");
}

function renderLastUpdated(value) {
  if (!lastUpdatedElement) return;
  lastUpdatedElement.textContent = `Ultima actualizare: ${formatUtcStamp(value) || "necunoscută"}`;
}

function setCalendarView(dateString) {
  const parsed = parseIsoDate(dateString);
  if (!parsed) return;
  viewYear = parsed.getFullYear();
  viewMonth = parsed.getMonth();
}

function isDateAvailable(dateString) {
  return Boolean(dataIndex.dates?.[dateString]);
}

function indexDates() {
  if (dataIndex.dates && !Array.isArray(dataIndex.dates)) return Object.keys(dataIndex.dates).sort();
  if (!Array.isArray(dataIndex.files)) return [];
  return dataIndex.files.map((file) => (typeof file === "string" ? file.replace(/\.geojson$/, "") : file?.date)).filter(Boolean).sort();
}

function preferredInitialDate() {
  const dates = indexDates();
  const today = dataIndex.today || todayIso();
  if (dates.includes(today)) return today;
  return dates[dates.length - 1] || today;
}

function summaryCard(label, value, extraClass = "") {
  return `<article class="summary-card ${extraClass}"><span class="summary-label">${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></article>`;
}

function detailRow(label, value) {
  return `<div class="detail-row"><dt class="detail-label">${escapeHtml(label)}</dt><dd>${escapeHtml(value || "-")}</dd></div>`;
}

function cleanDisplayText(value, fallback) {
  const text = typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
  if (!text || /^(undefined|null|\[object Object\])$/i.test(text)) return fallback;
  return text;
}

function formatValidity(props) {
  return cleanDisplayText(
    props.interval_text || props.intervalul || formatRange(props.interval_start || props.data_aparitiei, props.interval_end || props.data_expirare),
    "interval indisponibil"
  );
}

function formatRange(start, end) {
  return [formatAlertDateTime(start), formatAlertDateTime(end)].filter(Boolean).join(" – ");
}

function formatAlertDateTime(value) {
  if (!value) return "";
  const date = new Date(String(value).length === 16 ? `${value}:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  const dayMonth = new Intl.DateTimeFormat("ro-RO", { day: "numeric", month: "long" }).format(date);
  const time = new Intl.DateTimeFormat("ro-RO", { hour: "2-digit", minute: "2-digit" }).format(date);
  return `${dayMonth}, ora ${time}`;
}

function localIsoMinute(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:00`;
}

function formatDisplayDate(value) {
  const parsed = parseIsoDate(value);
  if (!parsed) return value || "-";
  return new Intl.DateTimeFormat("ro-RO", { day: "numeric", month: "long", year: "numeric" }).format(parsed);
}

function formatUtcStamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")} ${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")} UTC`;
}

function compactPhenomenon(text) {
  const clean = String(text || PHENOMENON_FALLBACK).replace(/\s+/g, " ").trim();
  const firstPart = clean.split(/[;,]/)[0]?.trim() || clean;
  return firstPart.charAt(0).toUpperCase() + firstPart.slice(1);
}

function sourceLabel(source) {
  if (!source) return "General ANM";
  return String(source).toLowerCase().includes("nowcasting") ? "Nowcasting" : "General ANM";
}

function sourceBadge(source) {
  const isNowcasting = String(source || "").toLowerCase().includes("nowcasting");
  return `<span class="source-badge ${isNowcasting ? "nowcasting" : "general"}">${escapeHtml(isNowcasting ? "Nowcasting" : "General ANM")}</span>`;
}

function presentCodesHtml(record) {
  const entries = Object.keys(record.color_counts || {}).map((code) => safeNumber(code, 0)).filter((code) => code > 0).sort((a, b) => a - b);
  if (!entries.length) return "-";
  return `<span class="codes-present">${entries.map((code) => codeChip(code)).join("<span class=\"slash\">/</span>")}</span>`;
}

function phenomenaListHtml(phenomenaByCode) {
  const entries = Object.entries(phenomenaByCode || {}).map(([code, text]) => [safeNumber(code, 0), text]).filter(([code, text]) => code > 0 && text).sort((a, b) => a[0] - b[0]);
  if (!entries.length) return `<p class="phenomenon-fallback">${escapeHtml(PHENOMENON_FALLBACK)}</p>`;
  return `<ul class="phenomena-list">${entries.map(([code, text]) => `<li><strong>Cod ${escapeHtml(String(COD_NAME[code] || "").toLowerCase())}:</strong> ${escapeHtml(text)}</li>`).join("")}</ul>`;
}

function codeChip(code) {
  const normalized = safeNumber(code, 0);
  if (!normalized) return `<span class="cod cod-neutral">Fără cod</span>`;
  return `<span class="cod cod-${normalized}">${escapeHtml(COD_NAME[normalized] || "-")}</span>`;
}

function pluralAnmAlerts(count) {
  const n = safeNumber(count, 0);
  if (n === 1) return "1 avertizare ANM";
  if (n >= 20) return `${n} de avertizări ANM`;
  return `${n} avertizări ANM`;
}

function pluralActiveAlerts(count) {
  const n = safeNumber(count, 0);
  if (n === 1) return "1 avertizare activă";
  if (n >= 20) return `${n} de avertizări active`;
  return `${n} avertizări active`;
}

function pluralZones(count) {
  const n = safeNumber(count, 0);
  if (n === 1) return "1 zonă afectată";
  if (n >= 20) return `${n} de zone afectate`;
  return `${n} zone afectate`;
}

function stripDiacritics(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function sortedUnique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "ro"));
}

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function parseIsoDate(value) {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function setStatus(message) {
  if (statusElement) statusElement.textContent = message;
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
