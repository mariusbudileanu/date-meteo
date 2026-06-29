"""Transform ANM XML alert records into WGS84 GeoJSON features."""

from __future__ import annotations

import html
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

from lxml import etree
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping
from shapely.ops import transform, unary_union

try:
    from shapely.validation import make_valid
except ImportError:  # pragma: no cover - Shapely 2 includes make_valid.
    make_valid = None


COLOR_NAMES = {
    0: "Verde",
    1: "Galben",
    2: "Portocaliu",
    3: "Roșu",
}

MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

ROMANIA_BOUNDS = (20.0, 43.0, 30.0, 49.0)

FIELD_ALIASES = {
    "data_aparitiei": {
        "dataaparitiei",
        "dataaparitie",
        "dataemiterii",
        "emisla",
        "issued",
        "issuedat",
    },
    "data_expirarii": {
        "dataexpirarii",
        "dataexpirare",
        "expirala",
        "expires",
        "expiresat",
    },
    "culoare": {
        "culoare",
        "codculoare",
        "codulculorii",
        "nivel",
        "level",
        "color",
        "colour",
    },
    "mesaj": {
        "mesaj",
        "message",
        "descriere",
        "description",
        "fenomene",
        "fenomen",
    },
    "fenomene_vizate": {
        "fenomenevizate",
        "fenomene",
        "phenomena",
    },
    "intervalul": {
        "intervalul",
        "interval",
        "validitate",
    },
    "zona_afectata": {
        "zonaafectata",
        "zoneafectate",
        "arii",
        "area",
    },
    "coord_gis": {
        "coordgis",
        "coordonategis",
        "geometry",
        "geom",
        "wkt",
    },
}

TRANSFORMER_3857_TO_4326 = Transformer.from_crs(
    "EPSG:3857",
    "EPSG:4326",
    always_xy=True,
)


def parse_xml(xml_bytes: bytes) -> etree._Element:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    return etree.fromstring(xml_bytes, parser=parser)


def features_from_xml(xml_bytes: bytes, source: str, scraped_at_utc: str) -> tuple[list[dict[str, Any]], list[str]]:
    root = parse_xml(xml_bytes)
    warnings: list[str] = []
    features: list[dict[str, Any]] = []
    alert_elements = list(root.xpath("//*[local-name()='avertizare']"))

    if alert_elements:
        for index, alert_element in enumerate(alert_elements, start=1):
            source_features, source_warnings = features_from_alert(alert_element, source, scraped_at_utc, index)
            features.extend(source_features)
            warnings.extend(source_warnings)
        return features, warnings

    for index, geometry_element in enumerate(iter_geometry_elements(root), start=1):
        try:
            context = build_orphan_context(geometry_element, source, scraped_at_utc, index)
            features.append(feature_from_geometry_element(geometry_element, context))
        except ValueError as exc:
            warnings.append(f"{source} geometry #{index}: {exc}")

    return features, warnings


def xml_diagnostics(xml_bytes: bytes) -> dict[str, int]:
    root = parse_xml(xml_bytes)
    raw_alert_count = 0
    coord_gis_count = 0

    for element in root.iter():
        name = normalized_name(element.tag)
        if name in {"avertizare", "avertizarenowcasting", "alert", "warning"}:
            raw_alert_count += 1
        if element_has_field(element, "coord_gis"):
            coord_gis_count += 1

    return {
        "raw_alert_count": raw_alert_count,
        "coord_gis_count": coord_gis_count,
    }


def features_from_alert(
    alert_element: etree._Element,
    source: str,
    scraped_at_utc: str,
    index: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    geometry_elements = iter_geometry_elements(alert_element)
    if not geometry_elements:
        return [], [f"{source} alert #{index}: missing coordGis"]

    context = build_alert_context(alert_element, geometry_elements, source, scraped_at_utc, index)
    features: list[dict[str, Any]] = []

    for geometry_index, geometry_element in enumerate(geometry_elements, start=1):
        try:
            features.append(feature_from_geometry_element(geometry_element, context))
        except ValueError as exc:
            warnings.append(f"{source} alert #{index} geometry #{geometry_index}: {exc}")

    return features, warnings


def build_alert_context(
    alert_element: etree._Element,
    geometry_elements: list[etree._Element],
    source: str,
    scraped_at_utc: str,
    index: int,
) -> dict[str, Any]:
    issued_at = extract_own_field(alert_element, "data_aparitiei") or ""
    expires_at = extract_own_field(alert_element, "data_expirarii") or ""
    raw_interval_text = extract_own_field(alert_element, "intervalul") or ""
    message_html = extract_own_field(alert_element, "mesaj", keep_markup=True) or ""
    parent_phenomena = extract_own_field(alert_element, "fenomene_vizate") or ""
    affected_area = extract_own_field(alert_element, "zona_afectata") or ""
    message_interval_texts = extract_interval_texts_from_message(message_html)
    interval_text = display_interval_text(raw_interval_text, message_interval_texts)
    interval_start, interval_end = parse_interval_window(
        raw_interval_text=raw_interval_text,
        message_interval_texts=message_interval_texts,
        expires_at=expires_at,
        issued_at=issued_at,
    )
    interval_start_iso = format_alert_datetime(interval_start)
    interval_end_iso = format_alert_datetime(interval_end)
    duration_hours, duration_days_text = calculate_duration(interval_start, interval_end)
    active_days = covered_dates(interval_start, interval_end)
    text_plain = html_to_plain_text(message_html)
    phenomena_by_code = extract_phenomena_by_code(message_html)
    geometry_infos = geometry_info_from_elements(geometry_elements)
    affected_codes = sorted(info["code"] for info in geometry_infos if info["color_code"] > 0)
    id_codes = affected_codes or sorted(info["code"] for info in geometry_infos)
    judete_culori = [(info["code"], info["color_code"]) for info in geometry_infos]
    alert_id = make_alert_id(source, interval_start_iso, interval_end_iso, id_codes)
    content_hash = make_content_hash(text_plain, judete_culori)
    max_color = max((info["color_code"] for info in geometry_infos), default=0)

    return {
        "alert_id": alert_id,
        "source": source,
        "scraped_at_utc": scraped_at_utc,
        "alert_index": index,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "interval_text": interval_text,
        "raw_interval_text": raw_interval_text,
        "interval_start": interval_start_iso,
        "interval_end": interval_end_iso,
        "duration_hours": duration_hours,
        "duration_days_text": duration_days_text,
        "active_days": active_days,
        "message_html": message_html,
        "text_plain": text_plain,
        "parent_phenomena": parent_phenomena,
        "affected_area": affected_area,
        "phenomena_by_code": phenomena_by_code,
        "content_hash": content_hash,
        "max_color": max_color,
    }


def build_orphan_context(
    geometry_element: etree._Element,
    source: str,
    scraped_at_utc: str,
    index: int,
) -> dict[str, Any]:
    issued_at = extract_context_field(geometry_element, "data_aparitiei") or ""
    expires_at = extract_context_field(geometry_element, "data_expirarii") or ""
    raw_interval_text = extract_context_field(geometry_element, "intervalul") or ""
    message_html = extract_context_field(geometry_element, "mesaj", keep_markup=True) or ""
    message_interval_texts = extract_interval_texts_from_message(message_html)
    interval_start, interval_end = parse_interval_window(
        raw_interval_text=raw_interval_text,
        message_interval_texts=message_interval_texts,
        expires_at=expires_at,
        issued_at=issued_at,
    )
    interval_start_iso = format_alert_datetime(interval_start)
    interval_end_iso = format_alert_datetime(interval_end)
    code = extract_own_attribute(geometry_element, "cod") or f"zona-{index}"
    color_code, _ = normalize_color(extract_own_field(geometry_element, "culoare"))
    text_plain = html_to_plain_text(message_html)
    alert_id = make_alert_id(source, interval_start_iso, interval_end_iso, [code])

    return {
        "alert_id": alert_id,
        "source": source,
        "scraped_at_utc": scraped_at_utc,
        "alert_index": index,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "interval_text": display_interval_text(raw_interval_text, message_interval_texts),
        "raw_interval_text": raw_interval_text,
        "interval_start": interval_start_iso,
        "interval_end": interval_end_iso,
        "duration_hours": calculate_duration(interval_start, interval_end)[0],
        "duration_days_text": calculate_duration(interval_start, interval_end)[1],
        "active_days": covered_dates(interval_start, interval_end),
        "message_html": message_html,
        "text_plain": text_plain,
        "parent_phenomena": extract_context_field(geometry_element, "fenomene_vizate") or "",
        "affected_area": extract_context_field(geometry_element, "zona_afectata") or "",
        "phenomena_by_code": extract_phenomena_by_code(message_html),
        "content_hash": make_content_hash(text_plain, [(code, color_code)]),
        "max_color": color_code,
    }


def feature_from_geometry_element(geometry_element: etree._Element, context: dict[str, Any]) -> dict[str, Any]:
    coord_gis = extract_own_field(geometry_element, "coord_gis")
    if not coord_gis:
        raise ValueError("missing coordGis")

    geometry = geojson_geometry_from_coord_gis(coord_gis)
    color_code, color_name = normalize_color(extract_own_field(geometry_element, "culoare"))
    zone_code = extract_own_attribute(geometry_element, "cod") or ""
    phenomena_by_code = context["phenomena_by_code"]
    main_phenomenon = phenomena_by_code.get(str(color_code)) or fallback_phenomenon(context["parent_phenomena"])
    feature_id = build_feature_id(context["alert_id"], zone_code, color_code, coord_gis)

    properties = {
        "alert_id": context["alert_id"],
        "feature_id": feature_id,
        "source": context["source"],
        "tip": context["source"],
        "alert_index": context["alert_index"],
        "element_type": strip_ns(geometry_element.tag),
        "judet_cod": zone_code,
        "judet_nume": zone_code,
        "cod_judet": zone_code,
        "cod_culoare": color_code,
        "cod_culoare_nume": color_name,
        "culoare": str(color_code),
        "cod": color_name,
        "cod_culoare_max": context["max_color"],
        "data_emitere": context["issued_at"],
        "data_expirare": context["expires_at"],
        "data_aparitiei": context["issued_at"],
        "data_expirarii": context["expires_at"],
        "interval_text": context["interval_text"],
        "intervalul": context["interval_text"],
        "interval_start": context["interval_start"],
        "interval_end": context["interval_end"],
        "active_days": context["active_days"],
        "durata_ore": context["duration_hours"],
        "durata_zile_text": context["duration_days_text"],
        "fenomene_vizate": context["parent_phenomena"],
        "fenomene_pe_cod": phenomena_by_code,
        "fenomen_principal": main_phenomenon,
        "zona_afectata": context["affected_area"],
        "zona_afectata_text": context["affected_area"],
        "mesaj": context["message_html"],
        "mesaj_html": context["message_html"],
        "text_alerta_plain": context["text_plain"],
        "content_hash": context["content_hash"],
        "scraped_at_utc": context["scraped_at_utc"],
    }

    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry,
        "properties": properties,
    }


def iter_geometry_elements(root: etree._Element) -> list[etree._Element]:
    selected = list(root.xpath(".//*[@coordGis]"))
    if element_has_field(root, "coord_gis"):
        selected.insert(0, root)

    if selected:
        return selected

    seen: set[int] = set()
    for element in root.iter():
        if not element_has_field(element, "coord_gis"):
            continue

        marker = id(element)
        if marker not in seen:
            selected.append(element)
            seen.add(marker)

    return selected


def geometry_info_from_elements(elements: list[etree._Element]) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    for index, element in enumerate(elements, start=1):
        color_code, _ = normalize_color(extract_own_field(element, "culoare"))
        code = extract_own_attribute(element, "cod") or f"zona-{index}"
        infos.append({"code": code, "color_code": color_code})
    return infos


def make_alert_id(source: str, interval_start_iso: str, interval_end_iso: str, zone_codes: list[str]) -> str:
    base = "|".join([source, interval_start_iso, interval_end_iso, ",".join(sorted(zone_codes))])
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    prefix = slugify_identifier(source) or "anm"
    return f"{prefix}-{digest}"


def make_content_hash(message_plain: str, zone_colors: list[tuple[str, int]]) -> str:
    colors = ",".join(f"{code}:{color}" for code, color in sorted(zone_colors))
    base = f"{message_plain or ''}|{colors}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def build_feature_id(alert_id: str, zone_code: str, color_code: int, coord_gis: str) -> str:
    digest = hashlib.sha1(f"{zone_code}|{color_code}|{coord_gis}".encode("utf-8")).hexdigest()[:10]
    zone = slugify_identifier(zone_code) or "zona"
    return f"{alert_id}-{zone}-{color_code}-{digest}"


def parse_interval_window(
    raw_interval_text: str,
    message_interval_texts: list[str],
    expires_at: str,
    issued_at: str,
) -> tuple[datetime, datetime]:
    end_dt = parse_alert_datetime(expires_at)
    if end_dt is None:
        end_dt = parse_interval_end(raw_interval_text or " ".join(message_interval_texts))
    if end_dt is None:
        end_dt = parse_alert_datetime(issued_at)
    if end_dt is None:
        end_dt = datetime.utcnow().replace(second=0, microsecond=0)

    candidates: list[str] = []
    if raw_interval_text and "conform" not in fold_ascii(raw_interval_text).lower():
        candidates.append(raw_interval_text)
    candidates.extend(message_interval_texts)

    start_dt = None
    for candidate in candidates:
        start_dt = parse_interval_start(candidate, end_dt)
        if start_dt is not None:
            break

    if start_dt is None:
        start_dt = parse_alert_datetime(issued_at) or end_dt

    if end_dt < start_dt:
        text_end_dt = parse_interval_end(candidates[0] if candidates else "")
        if text_end_dt is not None and text_end_dt >= start_dt:
            end_dt = text_end_dt

    return start_dt, end_dt


def parse_interval_start(value: str, end_dt: datetime) -> datetime | None:
    match = interval_datetime_matches(value)
    if not match:
        return None

    return datetime_from_interval_match(match[0], end_dt)


def parse_interval_end(value: str) -> datetime | None:
    reference = datetime.utcnow().replace(second=0, microsecond=0)
    matches = interval_datetime_matches(value)
    if len(matches) < 2:
        return None
    return datetime_from_interval_match(matches[-1], reference)


def interval_datetime_matches(value: str) -> list[re.Match[str]]:
    pattern = re.compile(
        r"(\d{1,2})\s+([A-Za-zăâîșşțţĂÂÎȘŞȚŢ]+)\s*,?\s*ora\s*(\d{1,2})(?::(\d{2}))?",
        flags=re.IGNORECASE,
    )
    return list(pattern.finditer(clean_text(value) or ""))


def datetime_from_interval_match(match: re.Match[str], end_dt: datetime) -> datetime | None:
    day = int(match.group(1))
    month_name = fold_ascii(match.group(2)).lower()
    month = MONTHS.get(month_name)
    if month is None:
        return None

    hour = int(match.group(3))
    minute = int(match.group(4) or 0)
    year = end_dt.year - (1 if month > end_dt.month else 0)
    candidate = datetime(year, month, day, hour, minute)

    if candidate > end_dt and month == end_dt.month:
        try:
            candidate = candidate.replace(year=year - 1)
        except ValueError:
            pass

    return candidate


def display_interval_text(raw_interval_text: str, message_interval_texts: list[str]) -> str:
    raw = clean_text(raw_interval_text) or ""
    if raw and "conform" not in fold_ascii(raw).lower():
        return raw

    unique = []
    for value in message_interval_texts:
        cleaned = clean_text(value)
        if cleaned and cleaned not in unique:
            unique.append(cleaned)

    return "; ".join(unique) or raw


def extract_interval_texts_from_message(message_html: str | None) -> list[str]:
    if not message_html:
        return []

    intervals: list[str] = []
    lines = html_to_lines(message_html)
    for index, line in enumerate(lines):
        folded_key = re.sub(r"[^a-z]", "", fold_ascii(line).lower())
        if "intervaldevalabilitate" not in folded_key:
            continue

        value = value_after_colon(line)
        if not value and index + 1 < len(lines):
            value = lines[index + 1]

        value = truncate_section_value(value)
        if value:
            intervals.append(value)

    return intervals


def covered_dates(start_dt: datetime, end_dt: datetime) -> list[str]:
    if end_dt < start_dt:
        return [start_dt.date().isoformat()]

    current = start_dt.date()
    last = end_dt.date()
    days: list[str] = []
    while current <= last:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def calculate_duration(start_dt: datetime, end_dt: datetime) -> tuple[int | float | None, str]:
    if end_dt < start_dt:
        return None, ""

    hours = (end_dt - start_dt).total_seconds() / 3600
    duration_hours: int | float
    if hours.is_integer():
        duration_hours = int(hours)
    else:
        duration_hours = round(hours, 1)

    calendar_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
    day_word = "zi calendaristică" if calendar_days == 1 else "zile calendaristice"
    return duration_hours, f"{calendar_days} {day_word}"


def format_alert_datetime(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def parse_alert_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def geojson_geometry_from_coord_gis(coord_gis: str) -> dict[str, Any]:
    geometry_wgs84 = parse_and_transform_wkt(coord_gis)

    if not geometry_in_romania_bounds(geometry_wgs84):
        bounds = ", ".join(f"{value:.4f}" for value in geometry_wgs84.bounds)
        raise ValueError(f"geometry outside Romania bounds after EPSG:4326 transform ({bounds})")

    return mapping(geometry_wgs84)


def parse_and_transform_wkt(coord_text: str) -> Polygon | MultiPolygon:
    geom_3857 = polygonal_geometry_from_wkt(coord_text)
    geom_3857 = repair_geometry(geom_3857)
    geom_4326 = transform(TRANSFORMER_3857_TO_4326.transform, geom_3857)
    return repair_geometry(geom_4326)


def polygonal_geometry_from_wkt(coord_gis: str) -> Polygon | MultiPolygon:
    text = clean_wkt(coord_gis)
    try:
        geometry = wkt.loads(text)
    except Exception as exc:
        raise ValueError(f"invalid WKT in coordGis: {exc}") from exc

    return polygonal_only(geometry)


def clean_wkt(value: str) -> str:
    text = clean_text(value) or ""
    text = text.replace("\ufeff", "")
    text = re.sub(r"^SRID=\d+;", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)

    match = re.search(r"(MULTIPOLYGON|POLYGON)\s*\(", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError("coordGis does not contain POLYGON or MULTIPOLYGON WKT")

    text = text[match.start() :]
    last_parenthesis = text.rfind(")")
    if last_parenthesis != -1:
        text = text[: last_parenthesis + 1]

    return text.strip()


def repair_geometry(geometry: Polygon | MultiPolygon | GeometryCollection) -> Polygon | MultiPolygon:
    geometry = polygonal_only(geometry)

    if geometry.is_empty:
        raise ValueError("empty geometry")

    if geometry.is_valid:
        return geometry

    repaired = None
    if make_valid is not None:
        repaired = make_valid(geometry)
        repaired = polygonal_only(repaired)

    if repaired is None or repaired.is_empty or not repaired.is_valid:
        repaired = polygonal_only(geometry.buffer(0))

    if repaired.is_empty or not repaired.is_valid:
        raise ValueError("invalid geometry could not be repaired")

    return repaired


def polygonal_only(geometry: Any) -> Polygon | MultiPolygon:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry

    if isinstance(geometry, GeometryCollection):
        polygon_parts = []
        for part in geometry.geoms:
            if isinstance(part, Polygon):
                polygon_parts.append(part)
            elif isinstance(part, MultiPolygon):
                polygon_parts.extend(part.geoms)

        if polygon_parts:
            merged = unary_union(polygon_parts)
            if isinstance(merged, (Polygon, MultiPolygon)):
                return merged

    raise ValueError(f"unsupported geometry type: {getattr(geometry, 'geom_type', type(geometry).__name__)}")


def geometry_in_romania_bounds(geometry: Polygon | MultiPolygon) -> bool:
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    if not all(math.isfinite(value) for value in geometry.bounds):
        return False

    romania_min_lon, romania_min_lat, romania_max_lon, romania_max_lat = ROMANIA_BOUNDS
    return (
        min_lon >= romania_min_lon
        and max_lon <= romania_max_lon
        and min_lat >= romania_min_lat
        and max_lat <= romania_max_lat
    )


def extract_phenomena_by_code(message_html: str | None) -> dict[str, str]:
    if not message_html:
        return {}

    phenomena: dict[str, str] = {}
    current_code: str | None = None
    lines = html_to_lines(message_html)

    for index, line in enumerate(lines):
        heading_code = color_code_from_heading(line)
        if heading_code is not None:
            current_code = heading_code

        if current_code is None or "fenomene vizate" not in fold_ascii(line).lower():
            continue

        value = value_after_colon(line)
        if not value and index + 1 < len(lines):
            value = lines[index + 1]

        value = truncate_section_value(value)
        if value:
            phenomena[current_code] = value

    return phenomena


def html_to_plain_text(value: str | None) -> str:
    return "\n".join(html_to_lines(value or ""))


def html_to_lines(value: str) -> list[str]:
    text = html.unescape(str(value)).replace("\xa0", " ")
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)

    lines = []
    for line in text.splitlines():
        cleaned = clean_text(line)
        if cleaned:
            lines.append(cleaned)
    return lines


def color_code_from_heading(value: str) -> str | None:
    folded = fold_ascii(value).upper()
    if "COD GALBEN" in folded:
        return "1"
    if "COD PORTOCALIU" in folded:
        return "2"
    if "COD ROSU" in folded:
        return "3"
    if "COD VERDE" in folded:
        return "0"
    return None


def value_after_colon(value: str) -> str:
    if ":" not in value:
        return ""
    return clean_text(value.split(":", 1)[1]) or ""


def truncate_section_value(value: str) -> str:
    if not value:
        return ""

    match = re.search(
        r"(?i)\b(?:Zone afectate|Interval de val\s*abilitate|COD\s+(?:GALBEN|PORTOCALIU|RO[ȘŞS]U|VERDE))\b",
        value,
    )
    if match:
        value = value[: match.start()]

    return (clean_text(value) or "").rstrip(" ;")


def fallback_phenomenon(value: str | None) -> str:
    cleaned = (clean_text(value) or "").rstrip(" ;")
    folded = fold_ascii(cleaned).lower()
    if cleaned and "conform text" not in folded:
        return cleaned
    return "conform textului avertizării ANM"


def normalize_color(value: str | None) -> tuple[int, str]:
    if value is None:
        return 0, COLOR_NAMES[0]

    raw = str(value).strip()
    folded = fold_ascii(raw).lower()

    if not folded or folded in {"0", "null", "none", "nan", "necunoscut", "unknown"}:
        return 0, COLOR_NAMES[0]

    if "galben" in folded or "yellow" in folded:
        return 1, COLOR_NAMES[1]
    if "portocaliu" in folded or "orange" in folded:
        return 2, COLOR_NAMES[2]
    if "rosu" in folded or "red" in folded:
        return 3, COLOR_NAMES[3]
    if "verde" in folded or "green" in folded:
        return 0, COLOR_NAMES[0]

    match = re.search(r"\b([0-3])\b", folded)
    if match:
        code = int(match.group(1))
        return code, COLOR_NAMES[code]

    return 0, COLOR_NAMES[0]


def extract_context_field(alert_element: etree._Element, field_name: str, keep_markup: bool = False) -> str | None:
    value = extract_field(alert_element, field_name, keep_markup)
    if value:
        return value

    cursor = alert_element.getparent()
    while cursor is not None:
        value = extract_own_field(cursor, field_name, keep_markup)
        if value:
            return value
        cursor = cursor.getparent()

    return None


def extract_field(alert_element: etree._Element, field_name: str, keep_markup: bool = False) -> str | None:
    value = extract_own_field(alert_element, field_name, keep_markup)
    if value:
        return value

    for element in alert_element.iterdescendants():
        value = extract_own_field(element, field_name, keep_markup)
        if value:
            return value

    return None


def extract_own_field(element: etree._Element, field_name: str, keep_markup: bool = False) -> str | None:
    aliases = FIELD_ALIASES[field_name]

    for attribute_name, attribute_value in element.attrib.items():
        if normalized_name(attribute_name) in aliases:
            return clean_text(attribute_value)

    if normalized_name(element.tag) in aliases:
        if keep_markup:
            return clean_text(inner_markup(element))
        return clean_text("".join(element.itertext()))

    return None


def extract_own_attribute(element: etree._Element, attribute_name: str) -> str | None:
    target = normalized_name(attribute_name)
    for current_name, current_value in element.attrib.items():
        if normalized_name(current_name) == target:
            return clean_text(current_value)
    return None


def element_has_field(element: etree._Element, field_name: str) -> bool:
    return extract_own_field(element, field_name) is not None


def normalized_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    try:
        local_name = etree.QName(value).localname
    except ValueError:
        local_name = value.rsplit("}", 1)[-1]

    return re.sub(r"[^a-z0-9]", "", fold_ascii(local_name).lower())


def strip_ns(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    try:
        return etree.QName(value).localname
    except ValueError:
        return value.rsplit("}", 1)[-1]


def slugify_identifier(value: str) -> str:
    folded = fold_ascii(str(value)).lower()
    folded = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return folded


def inner_markup(element: etree._Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        parts.append(etree.tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fold_ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
