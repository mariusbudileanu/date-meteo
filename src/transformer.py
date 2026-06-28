"""Transform ANM XML alert records into WGS84 GeoJSON features."""

from __future__ import annotations

import html
import hashlib
import math
import re
import unicodedata
from datetime import datetime
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
    "0": "Verde",
    "1": "Galben",
    "2": "Portocaliu",
    "3": "Roșu",
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
    features: list[dict[str, Any]] = []
    warnings: list[str] = []
    alert_ids = build_alert_ids(root, source)

    for index, alert_element in enumerate(iter_geometry_elements(root), start=1):
        try:
            parent_alert = find_parent_alert(alert_element)
            parent_key = element_path(parent_alert)
            alert_id = alert_ids.get(parent_key, build_orphan_alert_id(source, index))
            features.append(feature_from_alert_element(alert_element, parent_alert, alert_id, source, scraped_at_utc))
        except ValueError as exc:
            warnings.append(f"{source} alert #{index}: {exc}")

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


def build_alert_ids(root: etree._Element, source: str) -> dict[str, str]:
    alert_ids: dict[str, str] = {}
    for index, alert_element in enumerate(root.xpath("//*[local-name()='avertizare']"), start=1):
        alert_ids[element_path(alert_element)] = build_alert_id(source, alert_element, index)
    return alert_ids


def element_path(element: etree._Element | None) -> str:
    if element is None:
        return ""
    return element.getroottree().getpath(element)


def build_alert_id(source: str, alert_element: etree._Element, index: int) -> str:
    key_parts = [
        source,
        str(index),
        extract_own_field(alert_element, "data_aparitiei") or "",
        extract_own_field(alert_element, "data_expirarii") or "",
        extract_own_field(alert_element, "intervalul") or "",
        extract_own_field(alert_element, "mesaj", keep_markup=True) or "",
    ]
    digest = hashlib.sha1("|".join(key_parts).encode("utf-8")).hexdigest()[:12]
    return f"{slugify_identifier(source) or 'anm'}-{index:03d}-{digest}"


def build_orphan_alert_id(source: str, index: int) -> str:
    return f"{slugify_identifier(source) or 'anm'}-orphan-{index:03d}"


def build_feature_id(alert_id: str, county_code: str, color_code: str, coord_gis: str) -> str:
    digest = hashlib.sha1(f"{county_code}|{color_code}|{coord_gis}".encode("utf-8")).hexdigest()[:10]
    county = slugify_identifier(county_code) or "zona"
    return f"{alert_id}-{county}-{color_code}-{digest}"


def iter_geometry_elements(root: etree._Element) -> list[etree._Element]:
    selected = list(root.xpath("//*[@coordGis]"))
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


def feature_from_alert_element(
    alert_element: etree._Element,
    parent_alert: etree._Element | None,
    alert_id: str,
    source: str,
    scraped_at_utc: str,
) -> dict[str, Any]:
    coord_gis = extract_own_field(alert_element, "coord_gis")
    if not coord_gis:
        raise ValueError("missing coordGis")

    geometry = geojson_geometry_from_coord_gis(coord_gis)
    color_code, color_name = normalize_color(
        extract_own_field(alert_element, "culoare")
        or (extract_own_field(parent_alert, "culoare") if parent_alert is not None else None)
    )
    county_code = extract_own_attribute(alert_element, "cod") or ""
    message = extract_parent_field(parent_alert, "mesaj", keep_markup=True) or ""
    parent_phenomena = extract_parent_field(parent_alert, "fenomene_vizate") or ""
    phenomena_by_code = extract_phenomena_by_code(message)
    main_phenomenon = phenomena_by_code.get(color_code) or fallback_phenomenon(parent_phenomena)
    issued_at = extract_parent_field(parent_alert, "data_aparitiei") or ""
    expires_at = extract_parent_field(parent_alert, "data_expirarii") or ""
    duration_hours, calendar_days_text = calculate_duration(issued_at, expires_at)
    feature_id = build_feature_id(alert_id, county_code, color_code, coord_gis)

    properties = {
        "alert_id": alert_id,
        "feature_id": feature_id,
        "source": source,
        "tip": source,
        "cod_judet": county_code,
        "element_type": strip_ns(alert_element.tag),
        "data_aparitiei": issued_at,
        "data_expirarii": expires_at,
        "durata_ore": duration_hours,
        "durata_zile_text": calendar_days_text,
        "culoare": color_code,
        "cod": color_name,
        "fenomene_vizate": parent_phenomena,
        "fenomen_principal": main_phenomenon,
        "intervalul": extract_parent_field(parent_alert, "intervalul") or "",
        "zona_afectata": extract_parent_field(parent_alert, "zona_afectata") or "",
        "mesaj": message,
        "scraped_at_utc": scraped_at_utc,
    }

    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry,
        "properties": properties,
    }


def find_parent_alert(element: etree._Element) -> etree._Element | None:
    cursor = element
    while cursor is not None:
        if normalized_name(cursor.tag) == "avertizare":
            return cursor
        cursor = cursor.getparent()
    return None


def extract_parent_field(
    parent: etree._Element | None,
    field_name: str,
    keep_markup: bool = False,
) -> str | None:
    if parent is None:
        return None
    return extract_own_field(parent, field_name, keep_markup)


def extract_field(alert_element: etree._Element, field_name: str, keep_markup: bool = False) -> str | None:
    value = extract_own_field(alert_element, field_name, keep_markup)
    if value:
        return value

    for element in alert_element.iterdescendants():
        value = extract_own_field(element, field_name, keep_markup)
        if value:
            return value

    return None


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


def extract_phenomena_by_code(mesaj_html: str | None) -> dict[str, str]:
    if not mesaj_html:
        return {}

    phenomena: dict[str, str] = {}
    current_code: str | None = None
    lines = html_to_lines(mesaj_html)

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
        r"(?i)\b(?:Zone afectate|Interval de valabilitate|COD\s+(?:GALBEN|PORTOCALIU|RO[ȘS]U|VERDE))\b",
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


def calculate_duration(start_value: str, end_value: str) -> tuple[int | float | None, str]:
    start = parse_alert_datetime(start_value)
    end = parse_alert_datetime(end_value)

    if start is None or end is None or end < start:
        return None, ""

    hours = (end - start).total_seconds() / 3600
    duration_hours: int | float
    if hours.is_integer():
        duration_hours = int(hours)
    else:
        duration_hours = round(hours, 1)

    calendar_days = max(1, (end.date() - start.date()).days + 1)
    day_word = "zi calendaristică" if calendar_days == 1 else "zile calendaristice"
    return duration_hours, f"{calendar_days} {day_word}"


def parse_alert_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_color(value: str | None) -> tuple[str, str]:
    if value is None:
        return "0", COLOR_NAMES["0"]

    raw = str(value).strip()
    folded = fold_ascii(raw).lower()

    if not folded or folded in {"0", "null", "none", "nan", "necunoscut", "unknown"}:
        return "0", COLOR_NAMES["0"]

    if "galben" in folded or "yellow" in folded:
        return "1", COLOR_NAMES["1"]
    if "portocaliu" in folded or "orange" in folded:
        return "2", COLOR_NAMES["2"]
    if "rosu" in folded or "red" in folded:
        return "3", COLOR_NAMES["3"]
    if "verde" in folded or "green" in folded:
        return "0", COLOR_NAMES["0"]

    match = re.search(r"\b([0-3])\b", folded)
    if match:
        code = match.group(1)
        return code, COLOR_NAMES[code]

    return "0", COLOR_NAMES["0"]


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
