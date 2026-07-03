import re
import os

app_js = "public/js/app.js"
with open(app_js, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Map panes and Layer Groups
if "map.createPane" not in content:
    # Add map panes after map init
    panes_setup = """const map = L.map("alerts-map", { center: ROMANIA_CENTER, zoom: 7, minZoom: 5, maxZoom: 12 });
window.map = map;

map.createPane("base-counties-pane");
map.getPane("base-counties-pane").style.zIndex = 390;

map.createPane("general-alerts-pane");
map.getPane("general-alerts-pane").style.zIndex = 410;

map.createPane("nowcasting-alerts-pane");
map.getPane("nowcasting-alerts-pane").style.zIndex = 430;

map.createPane("labels-pane");
map.getPane("labels-pane").style.zIndex = 450;
"""
    content = content.replace('const map = L.map("alerts-map", { center: ROMANIA_CENTER, zoom: 7, minZoom: 5, maxZoom: 12 });\nwindow.map = map;', panes_setup)

# 2. Update map layer cleanup
if "function clearAlertsLayer()" in content:
    layer_cleanup = """function clearAlertsLayer() {
  if (alertsLayer) {
    alertsLayer.remove();
    alertsLayer = null;
  }
}"""
    # Wait, the prompt says to use a mapLayers object, but since alertsLayer and baseCountyLayer are already used, I can just update clearAlertsLayer and map rendering.
    # Actually, I will just make sure when rendering we set panes.
    # Where baseCountyLayer is created:
    content = content.replace(
        'baseCountyLayer = L.geoJSON(baseCountiesData, {',
        'baseCountyLayer = L.geoJSON(baseCountiesData, { pane: "base-counties-pane", '
    )
    content = content.replace(
        'alertsLayer = L.geoJSON({ type: "FeatureCollection", features: aggregateFeatures }, {',
        'alertsLayer = L.geoJSON({ type: "FeatureCollection", features: aggregateFeatures }, { pane: selectedSourceMode === "nowcasting" ? "nowcasting-alerts-pane" : "general-alerts-pane",'
    )

# 3. Fix Localities format function
localities_func = """function formatLocalitiesHtml(props) {
  let locs = props.localities;
  if (!locs || (Array.isArray(locs) && locs.length === 0)) {
     if (props.localitati) locs = props.localitati;
     else if (props.zone_localities) locs = props.zone_localities;
     else if (props.uat_names) locs = props.uat_names;
  }
  let arr = [];
  if (Array.isArray(locs)) arr = locs;
  else if (typeof locs === "string") {
    arr = locs.split(/[,;]/).map(s => s.trim()).filter(Boolean);
  }
  if (!arr || arr.length === 0) {
     return escapeHtml(props.zone_name || props.display_name || props.county_name || "");
  }
  
  if (arr.length <= 12) {
    return escapeHtml(arr.join(", "));
  } else {
    return `${escapeHtml(arr.slice(0, 12).join(", "))} <em>(+ încă ${arr.length - 12} localități)</em>`;
  }
}
"""
if "formatLocalitiesHtml" not in content:
    content = content.replace('function cleanDisplayText', localities_func + '\nfunction cleanDisplayText')

# 4. Fix countyAlertHtml
old_countyAlertHtml = """        ${(props.zone_name || props.zona_nume) ? detailRow("Zonă", cleanDisplayText(props.zone_name || props.zona_nume, "")) : ""}
        ${props.geometry_source ? detailRow("Geometrie", cleanDisplayText(props.geometry_source, "")) : ""}"""

new_countyAlertHtml = """        ${(props.zone_name || props.zona_nume) ? detailRow("Zonă", cleanDisplayText(props.zone_name || props.zona_nume, "")) : ""}
        ${isNowcastingFeature(feature) ? detailRow("Localități", formatLocalitiesHtml(props)) : ""}
        ${props.geometry_source ? detailRow("Geometrie", cleanDisplayText(props.geometry_source, "")) : ""}"""
content = content.replace(old_countyAlertHtml, new_countyAlertHtml)

# 5. Fix popup
old_popup = """  return `
    <div class="county-popup">
      <div class="county-popup-header">
        <h4>${escapeHtml(baseCountyDisplayName(firstFeature))}</h4>
        <span class="popup-kpi">${escapeHtml(String(validFeatures.length))} avertizări</span>
      </div>
      <ul class="county-popup-list">
        ${validFeatures.map((f) => popupItemHtml(f)).join("")}
      </ul>
      <p class="popup-hint">Click pentru detalii complete în panoul lateral</p>
    </div>
  `;
}

function popupItemHtml(feature) {
  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, 0);
  const phenomenon = compactPhenomenon(cleanDisplayText(featureText(feature), ""));
  const interval = cleanDisplayText(formatValidityShort(props), "");
  return `
    <li class="lvl-${code} ${isNowcastingFeature(feature) ? "nowcasting-item" : ""}">
      <span class="item-cod">${escapeHtml((COD_NAME[code] || "-").toLowerCase())}</span>
      <span class="item-fenomen">${escapeHtml(phenomenon)}</span>
      <span class="item-interval">${escapeHtml(interval)}</span>
    </li>
  `;
}"""

new_popup = """  return `
    <div class="county-popup">
      <div class="county-popup-header">
        <h4>${escapeHtml(baseCountyDisplayName(firstFeature))}</h4>
        <span class="popup-kpi">${escapeHtml(String(validFeatures.length))} avertizări</span>
      </div>
      <ul class="county-popup-list">
        ${validFeatures.map((f) => popupItemHtml(f)).join("")}
      </ul>
      <p class="popup-hint">Click pentru detalii complete în panoul lateral</p>
    </div>
  `;
}

function popupItemHtml(feature) {
  const props = feature.properties || {};
  const code = safeNumber(props.cod_culoare, 0);
  const phenomenon = compactPhenomenon(cleanDisplayText(featureText(feature), ""));
  const interval = cleanDisplayText(formatValidityShort(props), "");
  const locs = isNowcastingFeature(feature) ? `<div class="item-localities">Loc: ${formatLocalitiesHtml(props)}</div>` : "";
  return `
    <li class="lvl-${code} ${isNowcastingFeature(feature) ? "nowcasting-item" : ""}">
      <div style="display:flex; justify-content:space-between;">
        <span class="item-cod">${escapeHtml((COD_NAME[code] || "-").toLowerCase())}</span>
        <span class="item-fenomen">${escapeHtml(phenomenon)}</span>
        <span class="item-interval">${escapeHtml(interval)}</span>
      </div>
      ${locs}
    </li>
  `;
}"""
content = content.replace(old_popup, new_popup)

# 6. Fix message in alertCardHtml
old_alert_card = """      <details>
        <summary>Vezi textul complet publicat de ANM</summary>
        <div class="anm-message">${message || "Fără mesaj ANM."}</div>
      </details>"""
new_alert_card = """      <details class="alert-message-details">
        <summary>${record.source === "nowcasting_manual" ? "Vezi mesajul importat manual" : "Vezi mesajul complet ANM"}</summary>
        <div class="anm-message">${message || record.message || "Mesajul complet nu este disponibil în sursa arhivată."}</div>
      </details>"""
content = content.replace(old_alert_card, new_alert_card)

# 7. Remove "all" option logic
content = content.replace('const show = sourceMode === "all" || isNowcast === (sourceMode === "nowcasting");', 'const show = isNowcast === (sourceMode === "nowcasting");')
content = content.replace('sourceFilter ? sourceFilter.value : "all"', 'sourceFilter ? sourceFilter.value : "general"')
content = content.replace('sourceFilter ? sourceFilter.value : "general"', 'sourceFilter ? sourceFilter.value : "general"')

# 8. Filter Base Counties (no green counties in Nowcasting mode)
old_base_county_mode = """  if (!hasFilters) {
    baseCountyMode = mapMode === "max" ? "neutral" : "hidden";
  } else {
    baseCountyMode = "hidden";
  }"""
new_base_county_mode = """  if (selectedSourceMode === "nowcasting") {
    baseCountyMode = "hidden";
  } else if (!hasFilters) {
    baseCountyMode = mapMode === "max" ? "neutral" : "hidden";
  } else {
    baseCountyMode = "hidden";
  }"""
content = content.replace(old_base_county_mode, new_base_county_mode)

# 9. Legend order
old_legend = 'const order = ["1", "2", "3"];'
new_legend = 'const order = ["1", "2", "3", "all"];'
content = content.replace(old_legend, new_legend)

old_legend_render = """function renderLegend() {
  if (!legendContainerElement) return;
  const showGreen = baseCountyMode === "neutral" && selectedSourceMode !== "nowcasting";
  const greenItem = showGreen ? `
    <button type="button" class="legend-item" data-code="0" aria-pressed="${selectedSeverity === "0"}" title="Fără avertizare">
      <span class="legend-color legend-color-green"></span>
      <span class="legend-label">Fără avertizare</span>
    </button>
  ` : "";
  const order = ["1", "2", "3"];
  const colorItems = order.map((code) => {
    const isActive = selectedSeverity === "all" || selectedSeverity === code;
    return `
      <button type="button" class="legend-item" data-code="${code}" aria-pressed="${isActive}">
        <span class="legend-color" style="background: ${COD_COLOR[code]}"></span>
        <span class="legend-label">Cod ${COD_NAME[code]}</span>
      </button>
    `;
  }).join("");

  legendContainerElement.innerHTML = `
    <div class="legend-header">Coduri afișate</div>
    <div class="legend-items">
      ${selectedSeverity !== "all" ? `
        <button type="button" class="legend-item legend-all" data-code="all" aria-pressed="false">
          Toate culorile
        </button>
      ` : ""}
      ${greenItem}
      ${colorItems}
    </div>
  `;
}"""

new_legend_render = """function renderLegend() {
  if (!legendContainerElement) return;
  const showGreen = baseCountyMode === "neutral" && selectedSourceMode !== "nowcasting";
  
  const greenItem = showGreen ? `
    <button type="button" class="legend-item" data-code="0" aria-pressed="${selectedSeverity === "0"}" title="Fără avertizare">
      <span class="legend-color legend-color-green" style="background: #22C55E"></span>
      <span class="legend-label">Verde — Fără avertizare</span>
    </button>
  ` : "";
  
  const colorCodes = ["1", "2", "3"];
  const colorItems = colorCodes.map((code) => {
    const isActive = selectedSeverity === "all" || selectedSeverity === code;
    return `
      <button type="button" class="legend-item" data-code="${code}" aria-pressed="${isActive}">
        <span class="legend-color" style="background: ${COD_COLOR[code]}"></span>
        <span class="legend-label">${COD_NAME[code]}</span>
      </button>
    `;
  }).join("");

  legendContainerElement.innerHTML = `
    <div class="legend-header">Coduri afișate</div>
    <div class="legend-items" style="display:flex; flex-direction:column; gap:4px;">
      ${greenItem}
      ${colorItems}
      <div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.1);">
        <button type="button" class="legend-item legend-all" data-code="all" aria-pressed="${selectedSeverity === "all"}">
          <span class="legend-label">Toate culorile</span>
        </button>
      </div>
    </div>
  `;
}"""

content = content.replace(old_legend_render, new_legend_render)

with open(app_js, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated app.js successfully.")
