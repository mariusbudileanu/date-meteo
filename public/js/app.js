const ROMANIA_CENTER = [45.9432, 24.9668];
const ROMANIA_BOUNDS = [
  [43.5, 20.0],
  [48.8, 30.0],
];

const NO_ALERTS_MESSAGE = "Nu există avertizări înregistrate pentru această dată.";
const EMPTY_MESSAGE = "Nu au fost emise sau valabile avertizări pentru această dată.";
const PHENOMENON_FALLBACK = "conform textului avertizării ANM";
const COD_COLOR = { 0: "#34D399", 1: "#FACC15", 2: "#FB923C", 3: "#F43F5E" };
const COD_NAME = { 0: "Verde", 1: "Galben", 2: "Portocaliu", 3: "Roșu" };

const statusElement = document.getElementById("status");
const lastUpdatedElement = document.getElementById("last-updated");
const daySummaryElement = document.getElementById("day-summary");
const datePicker = document.getElementById("alert-date-picker"); // optional
const latestButton = document.getElementById("latest-alerts-button");
const nowcastingToggle = document.getElementById("toggle-nowcasting");
const calendarElement = document.getElementById("calendar");
const featureDetailsElement = document.getElementById("feature-details");
const alertsSummaryElement = document.getElementById("alerts-summary");
const countySelector = document.getElementById("county-selector");
const countyHistoryElement = document.getElementById("county-history");
const downloadsTableBody = document.getElementById("downloads-table-body");

let dataIndex = { dates: {}, files: [] };
let historyStats = { counties: [] };
let alertsLayer = null;
let nowcastingLayer = null;
let baseCountyLayer = null;
let selectedDate = "";
let viewYear = new Date().getFullYear();
let viewMonth = new Date().getMonth();
let showNowcasting = false;
let currentData = null;
let currentDateLabel = "";

const map = L.map("alerts-map", { center: ROMANIA_CENTER, zoom: 7, minZoom: 5, maxZoom: 12 });

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap, © CARTO",
  subdomains: "abcd",
  maxZoom: 19,
}).addTo(map);

map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
setTimeout(() => map.invalidateSize(true), 500);
setTimeout(() => map.invalidateSize(true), 1500);

addLegend();
start();

function setDatePicker(value) {
  if (datePicker) datePicker.value = value;
}

async function start() {
  dataIndex = await loadIndex();
  renderLastUpdated(dataIndex.generated_at_utc);

  const initialDate = dataIndex.latest_date || preferredInitialDate();
  selectedDate = initialDate;
  setDatePicker(initialDate || todayIso());
  setCalendarView(initialDate || todayIso());
  renderCalendar();
  renderDaySummary({ date: initialDate }, [], initialDate);

  if (datePicker) datePicker.addEventListener("change", () => showDate(datePicker.value));
  if (latestButton) latestButton.addEventListener("click", () => loadLatestAlerts());
  if (countySelector) countySelector.addEventListener("change", () => renderCountyHistory(countySelector.value));
  if (nowcastingToggle) {
    showNowcasting = nowcastingToggle.checked;
    nowcastingToggle.addEventListener("change", () => {
      showNowcasting = nowcastingToggle.checked;
      if (currentData) renderAlertData(currentData, currentDateLabel);
    });
  }

  await Promise.all([loadBaseCounties(), loadHistoryStats(), renderDownloads()]);
  await loadLatestAlerts();
}

async function loadIndex() {
  try {
    const response = await fetch("data/index.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
  setStatus("Se încarcă ultimele avertizări ANM...");
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
  setDatePicker(dateString);
  setCalendarView(dateString);
  renderCalendar();

  if (!isDateAvailable(dateString)) {
    renderEmptyDay(dateString);
    return;
  }

  setStatus("Se încarcă avertizările ANM pentru data selectată...");
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
  currentData = data;
  currentDateLabel = dateLabel;

  const allFeatures = Array.isArray(data.features) ? data.features : [];
  const metadata = data.metadata || {};
  const effectiveDate = dateLabel || metadata.date || selectedDate || dataIndex.latest_date || todayIso();
  selectedDate = effectiveDate;
  setDatePicker(effectiveDate);
  setCalendarView(effectiveDate);
  renderCalendar();

  clearAlertsLayer();
  renderSelectedFeature(null);

  const generalFeatures = allFeatures.filter((f) => (f.properties?.source || "general") !== "nowcasting");
  const nowcastingFeatures = allFeatures.filter((f) => f.properties?.source === "nowcasting");
  const visibleFeatures = showNowcasting ? [...generalFeatures, ...nowcastingFeatures] : generalFeatures;

  if (generalFeatures.length) {
    alertsLayer = L.geoJSON({ type: "FeatureCollection", features: generalFeatures }, {
      style: getAlertStyle,
      onEachFeature: onEachAlertFeature,
    }).addTo(map);
  }
  if (showNowcasting && nowcastingFeatures.length) {
    nowcastingLayer = L.geoJSON({ type: "FeatureCollection", features: nowcastingFeatures }, {
      style: getNowcastingStyle,
      onEachFeature: onEachAlertFeature,
    }).addTo(map);
  }

  renderDaySummary(metadata, visibleFeatures, effectiveDate);
  renderAlertsSummary(metadata, visibleFeatures);

  const hasGeneral = generalFeatures.length > 0;
  const hasNowcasting = nowcastingFeatures.length > 0;

  if (!hasGeneral && (!showNowcasting || !hasNowcasting)) {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
    const ncCount = safeNumber(metadata.nowcasting_count, nowcastingFeatures.length);
    const note = hasNowcasting
      ? `${NO_ALERTS_MESSAGE} (${ncCount} avertizări nowcasting disponibile, activează afișarea pentru a le vedea)`
      : emptyMessageFor(metadata);
    setStatus(note);
    return;
  }

  renderStatus(metadata, visibleFeatures, effectiveDate);

  requestAnimationFrame(() => refitMapToCurrentLayer());
  setTimeout(() => {
    map.invalidateSize(true);
    refitMapToCurrentLayer();
  }, 800);
}

function renderNoAlerts(message, dateLabel) {
  clearAlertsLayer();
  renderSelectedFeature(null);
  renderDaySummary({ date: dateLabel }, [], dateLabel);
  renderAlertsSummary({ active_alerts: [] }, []);
  map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  setStatus(message || (dateLabel ? `${NO_ALERTS_MESSAGE} pentru ${dateLabel}` : NO_ALERTS_MESSAGE));
}

function renderEmptyDay(dateString) {
  currentData = null;
  selectedDate = dateString;
  setDatePicker(dateString);
  setCalendarView(dateString);
  renderCalendar();
  renderNoAlerts(NO_ALERTS_MESSAGE, dateString);
}

function renderLastUpdated(value) {
  if (!lastUpdatedElement) return;
  lastUpdatedElement.textContent = `Ultima actualizare: ${formatUtcStamp(value) || "necunoscută"}`;
}

function renderStatus(metadata, features, dateLabel) {
  const alertCount = safeNumber(metadata?.alert_count, countDistinctAlerts(features));
  const featureCount = safeNumber(metadata?.feature_count, features.length);
  const maxCode = maxCodeFromRecords(normalizedActiveRecords(metadata, features), features, dataIndex.dates?.[dateLabel]?.max_color);
  let text = `${formatDisplayDate(dateLabel)} · ${pluralAnmAlerts(alertCount)} · ${pluralZones(featureCount)} · cod maxim ${COD_NAME[maxCode] || "Verde"}`;
  const nowcasting = safeNumber(metadata?.nowcasting_count, 0);
  if (nowcasting > 0 && !showNowcasting) {
    text += ` · ${nowcasting} nowcasting ascuns`;
  }
  setStatus(text);
}

function renderDaySummary(metadata, features, dateLabel) {
  if (!daySummaryElement) return;

  const indexInfo = dataIndex.dates?.[dateLabel] || {};
  const records = normalizedActiveRecords(metadata, features);
  const alertCount = safeNumber(metadata?.alert_count, safeNumber(indexInfo.alert_count, countDistinctAlerts(features)));
  const featureCount = safeNumber(metadata?.feature_count, safeNumber(indexInfo.feature_count, features.length));
  const maxCode = maxCodeFromRecords(records, features, indexInfo.max_color);
  const hasAlerts = alertCount > 0 || featureCount > 0 || records.length > 0;

  if (!hasAlerts) {
    const reason = metadata?.alerts_found_raw ? (metadata.reason || EMPTY_MESSAGE) : NO_ALERTS_MESSAGE;
    daySummaryElement.innerHTML = `
      <div class="summary-card summary-card-date">
        <span class="summary-label">Data selectată</span>
        <strong>${escapeHtml(formatDisplayDate(dateLabel || selectedDate || todayIso()))}</strong>
      </div>
      <div class="summary-empty">
        <strong>${escapeHtml(reason)}</strong>
        <span>Harta rămâne centrată pe România.</span>
      </div>
    `;
    return;
  }

  daySummaryElement.innerHTML = `
    ${summaryCard("Data selectată", formatDisplayDate(dateLabel))}
    ${summaryCard("Avertizări ANM", alertCount)}
    ${summaryCard("Zone afectate", featureCount)}
    ${summaryCard("Cod maxim", codeChip(maxCode), "summary-code")}
    ${summaryCard("Fenomene", summaryPhenomena(records, features), "summary-wide")}
    ${summaryCard("Interval", summaryInterval(records, features), "summary-wide")}
  `;
}

function renderSelectedFeature(feature) {
  if (!feature) {
    featureDetailsElement.classList.add("empty-state");
    featureDetailsElement.innerHTML = "Click pe un județ colorat pentru detalii despre cod, fenomen și valabilitate.";
    return;
  }

  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, props.culoare || 0);
  const phenomenon = props.fenomen_principal || PHENOMENON_FALLBACK;
  const source = sourceLabel(props.source || props.tip);

  featureDetailsElement.classList.remove("empty-state");
  featureDetailsElement.innerHTML = `
    <div class="selected-zone">
      <span>${escapeHtml(props.judet_nume || props.judet_cod || "Zonă afectată")}</span>
      ${codeChip(code)}
    </div>
    <dl class="detail-list">
      ${detailRow("Județ", props.judet_nume || props.judet_cod || "")}
      ${detailRowHtml("Cod", codeChip(code))}
      ${detailRow("Fenomen", phenomenon)}
      ${detailRow("Valabilitate", formatValidity(props))}
      ${detailRow("Durată", formatDuration(props))}
      ${detailRow("Sursa", source)}
    </dl>
    <p class="alert-summary-text">${escapeHtml(shortFeatureText(props))}</p>
  `;
}

function renderAlertsSummary(metadata, features) {
  let groups = normalizedActiveRecords(metadata, features);
  groups = groups.filter((g) => (g.source || "general") !== "nowcasting" || showNowcasting);

  if (!groups.length) {
    alertsSummaryElement.classList.add("empty-state");
    alertsSummaryElement.innerHTML = NO_ALERTS_MESSAGE;
    return;
  }

  alertsSummaryElement.classList.remove("empty-state");
  alertsSummaryElement.innerHTML = groups.map((record) => alertCardHtml(record)).join("");
}

function normalizedActiveRecords(metadata, features) {
  const activeAlerts = Array.isArray(metadata?.active_alerts) ? metadata.active_alerts : [];
  const groups = activeAlerts.length ? activeAlerts : recordsFromFeatureGroups(features);
  return groups.map((record) => normalizeAlertRecord(record));
}

function normalizeAlertRecord(record) {
  const zones = Array.isArray(record.judete_afectate) ? record.judete_afectate : [];
  const zoneColors = record.judete_culori || {};
  const colorCounts = record.color_counts || countsFromZoneColors(zoneColors);
  const maxCode = safeNumber(record.cod_culoare_max, maxCodeFromColorCounts(colorCounts));
  return {
    ...record,
    alert_id: record.alert_id || "",
    source: record.source || "general",
    cod_culoare_max: maxCode,
    fenomene_pe_cod: record.fenomene_pe_cod || {},
    judete_afectate: zones,
    judete_count: safeNumber(record.judete_count, zones.length),
    judete_culori: zoneColors,
    color_counts: colorCounts,
    text_alerta_html: record.text_alerta_html || "",
  };
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
        interval_end: props.interval_end || props.data_expirare,
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
  const zoneCount = safeNumber(record.judete_count, zones.length);

  return `
    <article class="alert-card lvl-${max}" data-alert-id="${escapeHtml(record.alert_id)}">
      <div class="alert-card-head">
        <div>
          <p class="section-kicker">${escapeHtml(sourceLabel(record.source))}</p>
          <h3>Avertizare meteorologică</h3>
        </div>
        ${codeChip(max)}
      </div>
      <div class="alert-card-grid">
        <div>
          <span class="field-label">Cod maxim</span>
          ${codeChip(max)}
        </div>
        <div>
          <span class="field-label">Coduri prezente</span>
          ${presentCodesHtml(record)}
        </div>
        <div>
          <span class="field-label">Interval</span>
          ${escapeHtml(record.interval_text || formatRange(record.interval_start, record.interval_end) || "-")}
        </div>
        <div>
          <span class="field-label">Zone afectate</span>
          ${escapeHtml(pluralZones(zoneCount))}
        </div>
        <div class="span-2">
          <span class="field-label">Fenomene</span>
          ${phenomenaListHtml(record.fenomene_pe_cod)}
        </div>
      </div>
      <details>
        <summary>Vezi textul complet publicat de ANM</summary>
        <div class="anm-message">${message || "Fără mesaj ANM."}</div>
      </details>
    </article>
  `;
}

function onEachAlertFeature(feature, layer) {
  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, props.culoare || 0);
  const county = props.judet_nume || props.judet_cod || "Zonă afectată";
  const phenomenon = compactPhenomenon(props.fenomen_principal || PHENOMENON_FALLBACK);
  const validUntil = formatAlertDateTime(props.interval_end || props.data_expirare);

  layer.bindPopup(`
    <div class="compact-popup">
      <strong>${escapeHtml(county)}</strong>
      <span>Cod ${escapeHtml(String(COD_NAME[code] || "verde").toLowerCase())}</span>
      <span>${escapeHtml(phenomenon)}</span>
      <span>Valabil până la: ${escapeHtml(validUntil || "-")}</span>
    </div>
  `);

  layer.on({
    click: () => renderSelectedFeature(feature),
    mouseover: () => layer.setStyle({ weight: 3, fillOpacity: 0.72 }),
    mouseout: () => {
      const owner = props.source === "nowcasting" ? nowcastingLayer : alertsLayer;
      if (owner) owner.resetStyle(layer);
    },
  });
}

async function loadBaseCounties() {
  try {
    const data = await fetchJson("data/judete.geojson");
    baseCountyLayer = L.geoJSON(data, {
      style: () => ({ color: "#34D399", weight: 0.8, opacity: 0.35, fillColor: "#34D399", fillOpacity: 0.07 }),
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
  if (!counties.length || !countySelector) {
    if (countyHistoryElement) {
      countyHistoryElement.classList.add("empty-state");
      countyHistoryElement.innerHTML = "Nu există statistici încărcate.";
    }
    return;
  }

  countySelector.innerHTML = counties
    .map((county) => `<option value="${escapeHtml(county.judet_cod)}">${escapeHtml(county.judet_nume || county.judet_cod)}</option>`)
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

  const counts = county.color_counts || {};
  const total = safeNumber(county.alert_count, 0);
  const earlyHistoryNote = total < 10
    ? `<p class="history-note">Istoricul este încă la început și va deveni mai relevant după mai multe rulări.</p>`
    : "";

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
    ${earlyHistoryNote}
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
    let codeClass;
    if (!info) codeClass = "no-data";
    else if (code > 0) codeClass = `cod-${code}`;
    else if (info.has_nowcasting) codeClass = "has-nowcasting";
    else codeClass = "cod-0";
    const futureClass = dataIndex.today && iso > dataIndex.today ? "future" : "";
    const selectedClass = iso === selectedDate ? "selected" : "";
    const title = info
      ? `${pluralAnmAlerts(info.alert_count)} · ${pluralZones(info.feature_count)} · cod maxim ${COD_NAME[code] || "Verde"}${info.has_nowcasting ? ` · ${info.nowcasting_count} nowcasting` : ""}`
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
    if (viewMonth < 0) { viewMonth = 11; viewYear -= 1; }
    renderCalendar();
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    viewMonth += 1;
    if (viewMonth > 11) { viewMonth = 0; viewYear += 1; }
    renderCalendar();
  });
  calendarElement.querySelectorAll("[data-iso]").forEach((button) => {
    button.addEventListener("click", () => showDate(button.dataset.iso));
  });
}

function setCalendarView(dateString) {
  const parsed = parseIsoDate(dateString);
  if (!parsed) return;
  viewYear = parsed.getFullYear();
  viewMonth = parsed.getMonth();
}

function refitMapToCurrentLayer() {
  map.invalidateSize(true);
  let bounds = null;
  const layers = [alertsLayer, showNowcasting ? nowcastingLayer : null];
  for (const layer of layers) {
    if (layer && layer.getLayers().length > 0 && layer.getBounds().isValid()) {
      bounds = bounds ? bounds.extend(layer.getBounds()) : L.latLngBounds(layer.getBounds());
    }
  }
  if (bounds && bounds.isValid()) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 8 });
  } else {
    map.fitBounds(ROMANIA_BOUNDS, { padding: [20, 20] });
  }
}

function clearAlertsLayer() {
  if (alertsLayer) { map.removeLayer(alertsLayer); alertsLayer = null; }
  if (nowcastingLayer) { map.removeLayer(nowcastingLayer); nowcastingLayer = null; }
}

function setStatus(message) {
  if (statusElement) statusElement.textContent = message;
}

function emptyMessageFor(metadata) {
  if (metadata?.alerts_found_raw && metadata?.features_with_geometry === 0) {
    return metadata.reason || EMPTY_MESSAGE;
  }
  return NO_ALERTS_MESSAGE;
}

function getAlertStyle(feature) {
  const code = safeNumber(feature.properties?.cod_culoare, feature.properties?.culoare || 0);
  const color = COD_COLOR[code] || COD_COLOR[0];
  return { color, fillColor: color, weight: 1.5, opacity: 1, fillOpacity: code === 3 ? 0.62 : 0.55 };
}

function getNowcastingStyle(feature) {
  const code = safeNumber(feature.properties?.cod_culoare, 0);
  const color = COD_COLOR[code] || COD_COLOR[0];
  return { color, fillColor: color, weight: 1.5, opacity: 0.9, dashArray: "4 3", fillOpacity: 0.28 };
}

function addLegend() {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const container = L.DomUtil.create("div", "leaflet-control legend");
    const rows = [0, 1, 2, 3]
      .map((code) => `
          <div class="legend-row">
            <span class="legend-swatch" style="background:${COD_COLOR[code]}"></span>
            <span>${COD_NAME[code]}</span>
          </div>
        `)
      .join("");
    container.innerHTML = `<div class="legend-title">Coduri</div>${rows}`;
    return container;
  };
  legend.addTo(map);
}

function preferredInitialDate() {
  const dates = indexDates();
  const today = dataIndex.today || todayIso();
  if (dates.includes(today)) return today;
  return dates[dates.length - 1] || today;
}

function isDateAvailable(dateString) {
  return Boolean(dataIndex.dates?.[dateString]);
}

function indexDates() {
  if (dataIndex.dates && !Array.isArray(dataIndex.dates)) {
    return Object.keys(dataIndex.dates).sort();
  }
  if (!Array.isArray(dataIndex.files)) return [];
  return dataIndex.files
    .map((file) => (typeof file === "string" ? file.replace(/\.geojson$/, "") : file?.date))
    .filter(Boolean)
    .sort();
}

function countDistinctAlerts(features) {
  const alertIds = new Set(features.map((feature) => feature.properties?.alert_id).filter(Boolean));
  return alertIds.size || (features.length ? 1 : 0);
}

function summaryCard(label, value, extraClass = "") {
  const isHtml = String(value).includes("<");
  return `
    <article class="summary-card ${extraClass}">
      <span class="summary-label">${escapeHtml(label)}</span>
      <strong>${isHtml ? value : escapeHtml(value || "-")}</strong>
    </article>
  `;
}

function summaryPhenomena(records, features) {
  const byCode = new Map();
  for (const record of records) {
    for (const [code, text] of Object.entries(record.fenomene_pe_cod || {})) {
      if (text) byCode.set(safeNumber(code, 0), compactPhenomenon(text));
    }
  }
  if (byCode.size) {
    return [...byCode.entries()]
      .filter(([code]) => code > 0)
      .sort((a, b) => b[0] - a[0])
      .map(([, text]) => text)
      .filter(Boolean)
      .slice(0, 3)
      .join(", ");
  }
  const phenomena = sortedUnique(features.map((feature) => compactPhenomenon(feature.properties?.fenomen_principal)).filter(Boolean));
  return phenomena.slice(0, 3).join(", ") || PHENOMENON_FALLBACK;
}

function summaryInterval(records, features) {
  const intervals = sortedUnique(records.map((record) => record.interval_text).filter(Boolean));
  if (intervals.length === 1) return intervals[0];

  const starts = records.map((record) => record.interval_start).filter(Boolean).sort();
  const ends = records.map((record) => record.interval_end).filter(Boolean).sort();
  if (starts.length && ends.length) return formatRange(starts[0], ends[ends.length - 1]);

  const featureIntervals = sortedUnique(features.map((feature) => feature.properties?.interval_text).filter(Boolean));
  if (featureIntervals.length === 1) return featureIntervals[0];
  return intervals.length ? "intervale multiple, conform avertizărilor ANM" : "-";
}

function maxCodeFromRecords(records, features, fallback = 0) {
  const recordMax = records.reduce((max, record) => Math.max(max, safeNumber(record.cod_culoare_max, 0)), 0);
  const featureMax = features.reduce((max, feature) => Math.max(max, safeNumber(feature.properties?.cod_culoare, 0)), 0);
  return Math.max(safeNumber(fallback, 0), recordMax, featureMax);
}

function countsFromZoneColors(zoneColors) {
  const counts = {};
  for (const color of Object.values(zoneColors || {})) {
    const code = String(color);
    if (safeNumber(code, 0) > 0) counts[code] = (counts[code] || 0) + 1;
  }
  return counts;
}

function maxCodeFromColorCounts(colorCounts) {
  return Object.keys(colorCounts || {}).reduce((max, code) => Math.max(max, safeNumber(code, 0)), 0);
}

function detailRow(label, value) {
  return detailRowHtml(label, escapeHtml(value || "-"));
}

function detailRowHtml(label, html) {
  return `
    <div class="detail-row">
      <dt class="detail-label">${escapeHtml(label)}</dt>
      <dd>${html || "-"}</dd>
    </div>
  `;
}

function formatValidity(props) {
  return props.interval_text || props.intervalul || formatRange(props.interval_start || props.data_aparitiei, props.interval_end || props.data_expirare);
}

function formatRange(start, end) {
  return [formatAlertDateTime(start), formatAlertDateTime(end)].filter(Boolean).join(" – ");
}

function formatDuration(props) {
  const hours = Number(props.durata_ore);
  if (!Number.isFinite(hours) || hours <= 0) return "-";
  const roundedHours = Number.isInteger(hours) ? hours : Math.round(hours * 10) / 10;
  const hourText = `${roundedHours} ${roundedHours === 1 ? "oră" : "ore"}`;
  const calendarDays = calendarDaySpan(props.interval_start || props.data_aparitiei, props.interval_end || props.data_expirare);
  return calendarDays > 1 ? `${hourText} / ${calendarDays} zile calendaristice` : hourText;
}

function calendarDaySpan(start, end) {
  if (!start || !end) return 0;
  const startDate = new Date(String(start).length === 16 ? `${start}:00` : start);
  const endDate = new Date(String(end).length === 16 ? `${end}:00` : end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return 0;
  const startMidnight = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
  const endMidnight = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());
  return Math.max(1, Math.round((endMidnight - startMidnight) / 86400000) + 1);
}

function formatAlertDateTime(value) {
  if (!value) return "";
  const date = new Date(String(value).length === 16 ? `${value}:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  const dayMonth = new Intl.DateTimeFormat("ro-RO", { day: "numeric", month: "long" }).format(date);
  const time = new Intl.DateTimeFormat("ro-RO", { hour: "2-digit", minute: "2-digit" }).format(date);
  return `${dayMonth}, ora ${time}`;
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
  const yyyy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const min = String(date.getUTCMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
}

function shortFeatureText(props) {
  const code = String(props.cod_culoare_nume || COD_NAME[safeNumber(props.cod_culoare, 0)] || "Verde").toLowerCase();
  const phenomenon = compactPhenomenon(props.fenomen_principal || PHENOMENON_FALLBACK).toLowerCase();
  return `Această zonă este afectată de cod ${code} pentru ${phenomenon}.`;
}

function compactPhenomenon(text) {
  const clean = String(text || PHENOMENON_FALLBACK).replace(/\s+/g, " ").trim();
  const firstPart = clean.split(/[;,]/)[0]?.trim() || clean;
  return firstPart.charAt(0).toUpperCase() + firstPart.slice(1);
}

function sourceLabel(source) {
  if (!source) return "ANM";
  return String(source).toLowerCase().includes("nowcasting") ? "ANM Nowcasting" : "ANM General";
}

function presentCodesHtml(record) {
  const counts = record.color_counts || countsFromZoneColors(record.judete_culori);
  const entries = Object.keys(counts)
    .map((code) => safeNumber(code, 0))
    .filter((code) => code > 0)
    .sort((a, b) => a - b);
  if (!entries.length) return codeChip(0);
  return `<span class="codes-present">${entries.map((code) => codeChip(code)).join("<span class=\"slash\">/</span>")}</span>`;
}

function colorCountsHtml(colorCounts, fallbackColors = {}) {
  const counts = { ...(colorCounts || {}) };
  if (!Object.keys(counts).length && fallbackColors) {
    Object.assign(counts, countsFromZoneColors(fallbackColors));
  }
  const entries = Object.entries(counts)
    .map(([code, count]) => [safeNumber(code, 0), count])
    .filter(([code]) => code > 0)
    .sort((a, b) => a[0] - b[0]);
  if (!entries.length) return codeChip(0);
  return entries.map(([code, count]) => `${codeChip(code)} <span class="count-badge">${escapeHtml(count)}</span>`).join(" ");
}

function phenomenaListHtml(phenomenaByCode) {
  const entries = Object.entries(phenomenaByCode || {})
    .map(([code, text]) => [safeNumber(code, 0), text])
    .filter(([code, text]) => code > 0 && text)
    .sort((a, b) => a[0] - b[0]);
  if (!entries.length) return `<p class="phenomenon-fallback">${escapeHtml(PHENOMENON_FALLBACK)}</p>`;
  return `
    <ul class="phenomena-list">
      ${entries.map(([code, text]) => `<li><strong>Cod ${escapeHtml(String(COD_NAME[code] || "").toLowerCase())}:</strong> ${escapeHtml(text)}</li>`).join("")}
    </ul>
  `;
}

function codeChip(code) {
  const normalized = safeNumber(code, 0);
  return `<span class="cod cod-${normalized}">${escapeHtml(COD_NAME[normalized] || "Verde")}</span>`;
}

function pluralAnmAlerts(count) {
  const n = safeNumber(count, 0);
  if (n === 1) return "1 avertizare ANM";
  if (n >= 20) return `${n} de avertizări ANM`;
  return `${n} avertizări ANM`;
}

function pluralZones(count) {
  const n = safeNumber(count, 0);
  if (n === 1) return "1 zonă afectată";
  if (n >= 20) return `${n} de zone afectate`;
  return `${n} zone afectate`;
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
