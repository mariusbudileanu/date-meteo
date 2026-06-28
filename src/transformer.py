"""Transform ANM XML alert records into WGS84 GeoJSON features."""

from __future__ import annotations

import html
import math
import re
import unicodedata
from typing import Any

from lxml import etree
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping
from shapely.ops import transform as shapely_transform, unary_union

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

PROJECT_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def parse_xml(xml_bytes: bytes) -> etree._Element:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    return etree.fromstring(xml_bytes, parser=parser)


def features_from_xml(xml_bytes: bytes, source: str, scraped_at_utc: str) -> tuple[list[dict[str, Any]], list[str]]:
    root = parse_xml(xml_bytes)
    features: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, alert_element in enumerate(iter_geometry_elements(root), start=1):
        try:
            features.append(feature_from_alert_element(alert_element, source, scraped_at_utc))
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
    source: str,
    scraped_at_utc: str,
) -> dict[str, Any]:
    coord_gis = extract_own_field(alert_element, "coord_gis")
    if not coord_gis:
        raise ValueError("missing coordGis")

    parent_alert = find_parent_alert(alert_element)
    geometry = geojson_geometry_from_coord_gis(coord_gis)
    color_code, color_name = normalize_color(
        extract_own_field(alert_element, "culoare")
        or (extract_own_field(parent_alert, "culoare") if parent_alert is not None else None)
    )
    code = extract_own_attribute(alert_element, "cod") or ""

    properties = {
        "source": source,
        "tip": source,
        "cod_judet": code,
        "element_type": strip_ns(alert_element.tag),
        "data_aparitiei": extract_parent_field(parent_alert, "data_aparitiei") or "",
        "data_expirarii": extract_parent_field(parent_alert, "data_expirarii") or "",
        "culoare": color_code,
        "cod": color_name,
        "fenomene_vizate": extract_parent_field(parent_alert, "fenomene_vizate") or "",
        "intervalul": extract_parent_field(parent_alert, "intervalul") or "",
        "zona_afectata": extract_parent_field(parent_alert, "zona_afectata") or "",
        "mesaj": extract_parent_field(parent_alert, "mesaj", keep_markup=True) or "",
        "scraped_at_utc": scraped_at_utc,
    }

    return {
        "type": "Feature",
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
    geometry = polygonal_geometry_from_wkt(coord_gis)
    geometry = repair_geometry(geometry)
    geometry_wgs84 = shapely_transform(PROJECT_TO_WGS84.transform, geometry)
    geometry_wgs84 = repair_geometry(geometry_wgs84)

    if not geometry_in_romania_bounds(geometry_wgs84):
        bounds = ", ".join(f"{value:.4f}" for value in geometry_wgs84.bounds)
        raise ValueError(f"geometry outside Romania bounds after EPSG:4326 transform ({bounds})")

    return mapping(geometry_wgs84)


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
