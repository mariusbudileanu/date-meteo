#!/usr/bin/env python3
"""
MeteoAlertRO — scraper ANM (fără dependențe externe, doar stdlib).

Flux: fetch XML (general + nowcasting) -> parse avertizari -> upsert in arhiva CSV lunara
      -> actualizeaza: data/<zi>.geojson, data/index.json, data/history_stats.json,
         data/latest.geojson, istoric/index.json, istoric/README.md

Reguli importante:
  * O <avertizare> = o fereastra de valabilitate (intervalul) cu culori fixe pe judet.
  * Daily GeoJSON pastreaza toate alertele suprapuse; codul maxim e metadata/UI.
  * General si nowcasting sunt SEPARATE: nowcasting NU coloreaza calendarul si e strat propriu.

Rulare normala:           python scraper.py
Rulare pe un XML local:   python scraper.py --local cale/avertizari.xml [--source general]
"""

import argparse, csv, hashlib, html, json, math, os, re, sys, unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------------ config
ENDPOINTS = {
    "general":    "https://www.meteoromania.ro/avertizari-xml.php",
    "nowcasting": "https://www.meteoromania.ro/avertizari-nowcasting-xml.php",
}
# XML-GIS endpoint: better structure with coordsGis geometry for nowcasting
NOWCASTING_GIS_ENDPOINT = "https://www.meteoromania.ro/avertizari-nowcasting-xml-gis.php"
PUBLIC = os.environ.get("METEO_OUT", "public")  # seteaza "." daca Pages serveste din radacina
DATA    = os.path.join(PUBLIC, "data")
ISTORIC = os.path.join(PUBLIC, "istoric")
GEODATA = os.environ.get("METEO_GEODATA", os.path.join("src", "geodata"))
MANUAL_NOWCASTING = os.path.join("manual_nowcasting")
MANUAL_NOWCASTING_CSV = os.path.join(MANUAL_NOWCASTING, "nowcasting_manual_import.csv")

COD_TO_NUME = {0: "Verde", 1: "Galben", 2: "Portocaliu", 3: "Roșu"}
NUME_TO_COD = {"VERDE": 0, "GALBEN": 1, "PORTOCALIU": 2, "ROSU": 3}
LUNI = {"ianuarie":1,"februarie":2,"martie":3,"aprilie":4,"mai":5,"iunie":6,
        "iulie":7,"august":8,"septembrie":9,"octombrie":10,"noiembrie":11,"decembrie":12}

JUDETE = {
 "AB":"Alba","AR":"Arad","AG":"Argeș","BC":"Bacău","BH":"Bihor","BN":"Bistrița-Năsăud",
 "BT":"Botoșani","BV":"Brașov","BR":"Brăila","BZ":"Buzău","CS":"Caraș-Severin","CL":"Călărași",
 "CJ":"Cluj","CT":"Constanța","CV":"Covasna","DB":"Dâmbovița","DJ":"Dolj","GL":"Galați",
 "GR":"Giurgiu","GJ":"Gorj","HR":"Harghita","HD":"Hunedoara","IL":"Ialomița","IS":"Iași",
 "IF":"Ilfov","MM":"Maramureș","MH":"Mehedinți","MS":"Mureș","NT":"Neamț","OT":"Olt",
 "PH":"Prahova","SM":"Satu Mare","SJ":"Sălaj","SB":"Sibiu","SV":"Suceava","TR":"Teleorman",
 "TM":"Timiș","TL":"Tulcea","VS":"Vaslui","VL":"Vâlcea","VN":"Vrancea","B":"București",
}

# ------------------------------------------------------------------ utils
def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def today_iso():
    return datetime.now(timezone.utc).date().isoformat()

def repair_mojibake(value):
    text = str(value or "")
    if any(marker in text for marker in ("Ã", "Â", "È", "Å", "�")):
        try:
            return text.encode("cp1252").decode("utf-8")
        except UnicodeError:
            return text
    return text

def _norm(s):
    return unicodedata.normalize("NFKD", repair_mojibake(s)).encode("ascii", "ignore").decode().upper()

COUNTY_NAME_TO_CODE = {_norm(name): code for code, name in JUDETE.items()}
COUNTY_NAME_TO_CODE.update({"BUCURESTI": "B", "MUNICIPIUL BUCURESTI": "B"})
NOWCASTING_SOURCES = {"nowcasting", "nowcasting_manual"}
GEODATA_STATS = {
    "county_path": "",
    "county_count": 0,
    "county_crs": "",
    "county_transformed": False,
    "county_schema": {},
    "uat_path": "",
    "uat_count": 0,
    "uat_crs": "",
    "uat_transformed": False,
    "uat_schema": {},
}
GEODATA_FEATURE_CACHE = {}
NOWCASTING_RUNTIME_STATS = {
    "live_alerts": 0,
    "manual_imported": 0,
    "archived_preserved": 0,
    "with_coord_gis": 0,
    "uat_fallback": 0,
    "county_fallback": 0,
    "without_geometry": 0,
    "_archived_preserved_keys": set(),
}

def month_number(name):
    return {_norm(k): v for k, v in LUNI.items()}.get(_norm(name or ""))

def is_nowcasting_source(source):
    return str(source or "").lower() in NOWCASTING_SOURCES or "nowcasting" in str(source or "").lower()

def normalize_ro_name(value):
    text = unicodedata.normalize("NFKD", repair_mojibake(value)).encode("ascii", "ignore").decode()
    text = re.sub(r"\b(municipiul|orasul|oras|comuna|satul|sat|judetul|judet)\b", " ", text, flags=re.I)
    text = re.sub(r"\bsectorul\s+(\d)\b", r"sector \1", text, flags=re.I)
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().upper()

def county_code_for_name(value):
    if not value:
        return ""
    raw = str(value).strip()
    if raw.upper() in JUDETE:
        return raw.upper()
    return COUNTY_NAME_TO_CODE.get(_norm(raw)) or COUNTY_NAME_TO_CODE.get(normalize_ro_name(raw), "")

def first_value(mapping, aliases):
    if not mapping:
        return ""
    normalized = {normalize_ro_name(k): v for k, v in mapping.items()}
    for alias in aliases:
        if normalize_ro_name(alias) in normalized:
            return normalized[normalize_ro_name(alias)]
    return ""

def safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default

def color_code_from_value(value):
    folded = _norm(value or "")
    if "ROSU" in folded or "RED" in folded:
        return 3
    if "PORTOCALIU" in folded or "ORANGE" in folded:
        return 2
    if "GALBEN" in folded or "YELLOW" in folded:
        return 1
    return safe_int(value, 0)

def parse_locality_list(value):
    text = re.sub(r"\([^)]*\)", " ", str(value or ""))
    text = re.sub(r"\b(?:si|și)\b", ";", text, flags=re.I)
    parts = re.split(r"[;,]", text)
    out = []
    for part in parts:
        item = re.sub(r"\s+", " ", part).strip(" .:-")
        if item and len(item) > 1:
            out.append(item)
    return out

def parse_nowcasting_counties_and_localities(text):
    plain = html_to_plain(text)
    # Match "Județul X: localities" — support both ț (U+021B) and ţ (U+0163) plus mojibake variants
    pattern = re.compile(r"Jude[t\u021b\u0163È›Å£]ul\s+([^:;\n]+)\s*:\s*(.*?)(?=Jude[t\u021b\u0163È›Å£]ul\s+[^:;\n]+\s*:|$)", re.I | re.S)
    matches = list(pattern.finditer(plain))
    if matches:
        return [
            {
                "county_name": re.sub(r"\s+", " ", m.group(1)).strip(" .:-"),
                "localities": parse_locality_list(m.group(2)),
            }
            for m in matches
        ]

    county_match = re.search(r"Jude[t\u021b\u0163È›Å£]ul\s+([A-Za-z\u0102\u0082\u00ce\u0218\u021a\u0103\u00e2\u00ee\u0219\u021b\u015f\u0163È›Å£\-\s]+)", plain, re.I)
    if county_match:
        return [{"county_name": county_match.group(1).strip(" .:-"), "localities": []}]
    return []

def parse_nowcasting_hour_interval(text, reference_dt):
    plain = html_to_plain(text)
    match = re.search(r"(?:de la|interval(?:ul)?\s*)\s*(\d{1,2})[.:](\d{2})\s*(?:pana la|p[aâ]n[aă]\s+la|[-–—])\s*(\d{1,2})[.:](\d{2})", plain, re.I)
    if not match:
        return None
    sh, sm, eh, em = map(int, match.groups())
    start = reference_dt.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = reference_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end < start:
        end += timedelta(days=1)
    return start, end, f"{sh:02d}:{sm:02d} - {eh:02d}:{em:02d}"

def merc_to_wgs(x, y):
    R = 6378137.0
    lon = (x / R) * 180.0 / math.pi
    lat = (2.0 * math.atan(math.exp(y / R)) - math.pi / 2.0) * 180.0 / math.pi
    return [round(lon, 6), round(lat, 6)]

def _parse_paren(s, i):
    i += 1
    j = i
    while s[j] == ' ': j += 1
    if s[j] == '(':
        items = []
        while True:
            while s[i] in ' ,': i += 1
            if s[i] == ')': return items, i + 1
            item, i = _parse_paren(s, i)
            items.append(item)
    else:
        k = s.index(')', i)
        coords = []
        for pair in s[i:k].split(','):
            xs, ys = pair.split()
            coords.append([float(xs), float(ys)])
        return coords, k + 1

def wkt_to_geojson_geometry(wkt):
    polys, _ = _parse_paren(wkt, wkt.index('('))
    coords = [[[merc_to_wgs(x, y) for x, y in ring] for ring in poly] for poly in polys]
    return {"type": "MultiPolygon", "coordinates": coords}

def load_geojson_file(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data.get("features", [])
    except (OSError, json.JSONDecodeError):
        return []

def iter_geojson_coords(geometry):
    if not geometry:
        return
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "GeometryCollection":
        for item in geometry.get("geometries", []):
            yield from iter_geojson_coords(item)
        return
    if coords is None:
        return
    stack = [coords]
    while stack:
        item = stack.pop()
        if not item:
            continue
        if isinstance(item[0], (int, float)) and len(item) >= 2:
            yield float(item[0]), float(item[1])
        else:
            stack.extend(item)

def geojson_bounds(features):
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    found = False
    for feature in features:
        for x, y in iter_geojson_coords(feature.get("geometry")):
            found = True
            minx = min(minx, x); miny = min(miny, y)
            maxx = max(maxx, x); maxy = max(maxy, y)
    if not found:
        return None
    return minx, miny, maxx, maxy

def detect_geojson_crs_from_bounds(bounds):
    if not bounds:
        return "EPSG:4326"
    minx, miny, maxx, maxy = bounds
    if max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90:
        return "EPSG:3857"
    return "EPSG:4326"

def transform_geometry_3857_to_4326(geometry):
    if not geometry:
        return geometry
    try:
        from pyproj import Transformer
        from shapely.geometry import mapping, shape
        from shapely.ops import transform
        transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        return mapping(transform(transformer.transform, shape(geometry)))
    except Exception:
        def transform_coords(value):
            if not value:
                return value
            if isinstance(value[0], (int, float)) and len(value) >= 2:
                lon, lat = merc_to_wgs(float(value[0]), float(value[1]))
                return [lon, lat] + list(value[2:])
            return [transform_coords(item) for item in value]
        out = dict(geometry)
        if out.get("type") == "GeometryCollection":
            out["geometries"] = [transform_geometry_3857_to_4326(g) for g in out.get("geometries", [])]
        elif "coordinates" in out:
            out["coordinates"] = transform_coords(out["coordinates"])
        return out

def prepare_geodata_features(path, features):
    bounds = geojson_bounds(features)
    detected = detect_geojson_crs_from_bounds(bounds)
    transformed = detected == "EPSG:3857"
    if transformed:
        prepared = []
        for feature in features:
            item = dict(feature)
            item["properties"] = dict(feature.get("properties") or {})
            item["geometry"] = transform_geometry_3857_to_4326(feature.get("geometry"))
            prepared.append(item)
        return prepared, detected, True
    return features, detected, False

def geodata_candidate_paths(kind):
    if kind == "county":
        return [
            os.path.join(GEODATA, "romania_judete.geojson"),
            os.path.join(GEODATA, "ro_judete_poligon_simplify.geojson"),
            os.path.join(PUBLIC, "geodata", "romania_judete.geojson"),
            os.path.join(DATA, "judete.geojson"),
        ]
    return [
        os.path.join(GEODATA, "romania_uat.geojson"),
        os.path.join(GEODATA, "ro_uat_poligon_simplify.geojson"),
        os.path.join(PUBLIC, "geodata", "romania_uat.geojson"),
    ]

def load_first_geojson(kind):
    for path in geodata_candidate_paths(kind):
        cache_key = os.path.abspath(path)
        if cache_key in GEODATA_FEATURE_CACHE:
            prepared, detected, transformed = GEODATA_FEATURE_CACHE[cache_key]
            return path, prepared, detected, transformed
        features = load_geojson_file(path)
        if features:
            prepared, detected, transformed = prepare_geodata_features(path, features)
            GEODATA_FEATURE_CACHE[cache_key] = (prepared, detected, transformed)
            return path, prepared, detected, transformed
    return "", [], "", False

def validator_county_code(value):
    return 10 if str(value or "").strip().upper() in JUDETE else 0

def validator_county_name(value):
    return 8 if county_code_for_name(value) else 0

def validator_siruta(value):
    text = str(value or "").strip()
    return 5 if text.isdigit() and len(text) >= 4 else 0

def detect_property_field(features, aliases, validator=None, sample_size=250):
    normalized_aliases = [normalize_ro_name(alias) for alias in aliases]
    scores = defaultdict(int)
    for feature in features[:sample_size]:
        props = feature.get("properties") or {}
        for key, value in props.items():
            if value in (None, ""):
                continue
            normalized_key = normalize_ro_name(key)
            alias_score = 0
            for index, alias in enumerate(normalized_aliases):
                if normalized_key == alias:
                    alias_score = max(alias_score, 30 - index)
                elif alias and alias in normalized_key:
                    alias_score = max(alias_score, 12 - min(index, 10))
            value_score = validator(value) if validator else 1
            if validator and value_score <= 0:
                continue
            if alias_score or value_score > 1:
                scores[key] += alias_score + value_score
    if not scores:
        return ""
    return max(scores.items(), key=lambda item: item[1])[0]

def detect_county_schema(features):
    return {
        "county_name": detect_property_field(
            features,
            ["judet_nume", "county_name", "name", "judet", "county", "nume"],
            validator_county_name,
        ),
        "county_code": detect_property_field(
            features,
            ["judet_cod", "cod_judet", "county_code", "countyMn", "mnemonic", "code", "cod"],
            validator_county_code,
        ),
    }

def detect_uat_schema(features):
    return {
        "uat_name": detect_property_field(
            features,
            ["uat_name", "localitate", "name", "nume", "uat", "denumire"],
        ),
        "uat_county": detect_property_field(
            features,
            ["judet_cod", "cod_judet", "countyMn", "county_name", "county", "judet", "mnemonic"],
            lambda value: validator_county_code(value) or validator_county_name(value),
        ),
        "siruta": detect_property_field(
            features,
            ["siruta", "cod_siruta", "siruta_code", "natcode", "nat_code", "sirsup"],
            validator_siruta,
        ),
    }

def schema_value(props, field):
    if not field:
        return ""
    value = props.get(field)
    return "" if value in (None, "") else str(value)

def county_geodata_features():
    path, features, detected_crs, transformed = load_first_geojson("county")
    if features and GEODATA_STATS["county_path"] != path:
        GEODATA_STATS["county_path"] = path
        GEODATA_STATS["county_count"] = len(features)
        GEODATA_STATS["county_crs"] = detected_crs
        GEODATA_STATS["county_transformed"] = transformed
        GEODATA_STATS["county_schema"] = detect_county_schema(features)
    if not features:
        GEODATA_STATS["county_path"] = ""
        GEODATA_STATS["county_count"] = 0
        GEODATA_STATS["county_crs"] = ""
        GEODATA_STATS["county_transformed"] = False
        GEODATA_STATS["county_schema"] = {}
    return features

def uat_geodata_features():
    path, features, detected_crs, transformed = load_first_geojson("uat")
    if features and GEODATA_STATS["uat_path"] != path:
        GEODATA_STATS["uat_path"] = path
        GEODATA_STATS["uat_count"] = len(features)
        GEODATA_STATS["uat_crs"] = detected_crs
        GEODATA_STATS["uat_transformed"] = transformed
        GEODATA_STATS["uat_schema"] = detect_uat_schema(features)
    if not features:
        GEODATA_STATS["uat_path"] = ""
        GEODATA_STATS["uat_count"] = 0
        GEODATA_STATS["uat_crs"] = ""
        GEODATA_STATS["uat_transformed"] = False
        GEODATA_STATS["uat_schema"] = {}
    return features

def feature_property(props, aliases):
    for alias in aliases:
        target = normalize_ro_name(alias)
        for key, value in props.items():
            if normalize_ro_name(key) == target and value not in (None, ""):
                return str(value)
    return ""

def county_geometry_index():
    out = {}
    features = county_geodata_features()
    schema = GEODATA_STATS.get("county_schema") or detect_county_schema(features)
    for feature in features:
        props = feature.get("properties") or {}
        code = schema_value(props, schema.get("county_code")).upper()
        name = schema_value(props, schema.get("county_name"))
        if code and code in JUDETE:
            out[code] = feature.get("geometry")
        if name:
            resolved = county_code_for_name(name)
            if resolved:
                out[resolved] = feature.get("geometry")
    return {k: v for k, v in out.items() if v}

def uat_geometry_index():
    out = {}
    bucharest_sector_geometries = []
    features = uat_geodata_features()
    schema = GEODATA_STATS.get("uat_schema") or detect_uat_schema(features)
    for feature in features:
        props = feature.get("properties") or {}
        name = schema_value(props, schema.get("uat_name"))
        county = schema_value(props, schema.get("uat_county"))
        county_code = county_code_for_name(county)
        if not name or not county_code or not feature.get("geometry"):
            continue
        normalized_name = normalize_ro_name(name)
        out[(county_code, normalized_name)] = feature.get("geometry")
        if county_code == "B" and normalized_name.startswith("BUCURESTI SECTOR"):
            bucharest_sector_geometries.append(feature.get("geometry"))
        siruta = schema_value(props, schema.get("siruta"))
        if siruta:
            out[(county_code, normalize_ro_name(siruta))] = feature.get("geometry")
    if bucharest_sector_geometries:
        bucharest_geometry = multipolygon_from_geometries(bucharest_sector_geometries)
        if bucharest_geometry:
            out[("B", "BUCURESTI")] = bucharest_geometry
            out[("B", "MUNICIPIUL BUCURESTI")] = bucharest_geometry
    return out

def multipolygon_from_geometries(geometries):
    polygons = []
    for geom in geometries:
        if not geom:
            continue
        if geom.get("type") == "Polygon":
            polygons.append(geom.get("coordinates", []))
        elif geom.get("type") == "MultiPolygon":
            polygons.extend(geom.get("coordinates", []))
    if not polygons:
        return None
    return {"type": "MultiPolygon", "coordinates": polygons}

def fallback_geometry_for_nowcasting(county_code, localities=None):
    localities = localities or []
    if localities:
        uat_index = uat_geometry_index()
        matches = [
            uat_index[(county_code, normalize_ro_name(locality))]
            for locality in localities
            if (county_code, normalize_ro_name(locality)) in uat_index
        ]
        if matches:
            return multipolygon_from_geometries(matches), "uat_match", "high" if len(matches) == len(localities) else "medium"

    counties = county_geometry_index()
    if county_code in counties:
        return counties[county_code], "county_fallback", "low" if localities else "medium"
    return None, "missing", "low"

# ------------------------------------------------------------------ parsing ANM
MONTH_WORD = r"[A-Za-zĂÂÎȘȚăâîșț]+"
INTERVAL_RE = re.compile(
    rf"(\d{{1,2}})\s+({MONTH_WORD})\s*,?\s*ora\s+(\d{{1,2}})(?::(\d{{2}}))?"
    rf"\s*[-–—]\s*"
    rf"(\d{{1,2}})\s+({MONTH_WORD})\s*,?\s*ora\s+(\d{{1,2}})(?::(\d{{2}}))?",
    re.I,
)
COD_RE = re.compile(r"\bCOD\s+(GALBEN|PORTOCALIU|RO[ȘS]U|ROSU|VERDE)\b", re.I)

def parse_xml_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None

def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return parse_xml_datetime(value)

def parse_interval_text(text, base_year):
    m = INTERVAL_RE.search(html.unescape(text or ""))
    if not m:
        return None
    sd, sm, sh, smin, ed, em, eh, emin = m.groups()
    sm_num, em_num = month_number(sm), month_number(em)
    if not sm_num or not em_num:
        return None
    start = datetime(base_year, sm_num, int(sd), int(sh), int(smin or 0))
    end = datetime(base_year, em_num, int(ed), int(eh), int(emin or 0))
    if end < start:
        end = datetime(base_year + 1, em_num, int(ed), int(eh), int(emin or 0))
    return start, end, re.sub(r"\s+", " ", m.group(0)).strip(" ;.")

def extract_field(segment, label_re, stop_re):
    m = re.search(label_re + r"\s*:?\s*(.+?)(?=" + stop_re + r")", segment, re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip(" ;.")

def extract_sections_from_message(mesaj_html, base_year):
    txt = html_to_plain(mesaj_html)
    heads = list(COD_RE.finditer(txt))
    sections = []
    for i, h in enumerate(heads):
        code = NUME_TO_COD.get(_norm(h.group(1)))
        if code is None:
            continue
        seg = txt[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(txt)]
        interval = parse_interval_text(seg, base_year)
        phenomena = (
            extract_field(seg, r"Fenomene?\s+vizate", r"\n|Zone\s+(?:afectate|avertizate)|$")
            or extract_field(seg, r"Fenomenul\s+vizat", r"\n|Zone\s+(?:afectate|avertizate)|$")
        )
        zones = extract_field(
            seg,
            r"Zone\s+(?:afectate|avertizate)",
            r"\n|Luni|Marți|Marti|Miercuri|Joi|Vineri|Sâmbătă|Sambata|Duminică|Duminica|Notă|Nota|$",
        )
        sections.append({
            "code": str(code),
            "code_name": COD_TO_NUME[code],
            "valid_from": interval[0] if interval else None,
            "valid_to": interval[1] if interval else None,
            "interval_text": interval[2] if interval else "",
            "phenomena": phenomena,
            "zones_text": zones,
        })
    return sections

def parse_interval(intervalul, data_aparitiei, data_expirarii, mesaj_html=""):
    """Return (start_dt, end_dt). Text intervals have priority over XML expiration."""
    exp_dt = parse_xml_datetime(data_expirarii)
    ap_dt = parse_xml_datetime(data_aparitiei)
    base_year = (exp_dt or ap_dt or datetime.now()).year
    if intervalul and "CONFORM TEXTELOR" not in _norm(intervalul):
        parsed = parse_interval_text(intervalul, base_year)
        if parsed:
            return parsed[0], parsed[1]
    if mesaj_html:
        sections = [s for s in extract_sections_from_message(mesaj_html, base_year) if s["valid_from"] and s["valid_to"]]
        if sections:
            start = min(s["valid_from"] for s in sections)
            end = max(s["valid_to"] for s in sections)
            if exp_dt and abs((exp_dt - end).days) >= 2:
                print(f"  ! interval text overrides XML dataExpirarii {data_expirarii} -> {end.isoformat()}", file=sys.stderr)
            return start, end
    if ap_dt and exp_dt:
        return ap_dt, exp_dt
    if exp_dt:
        return exp_dt - timedelta(hours=3), exp_dt
    now = datetime.now()
    return now, now

def zile_acoperite(start_dt, end_dt):
    d, out = start_dt.date(), []
    while d <= end_dt.date():
        out.append(d.isoformat()); d += timedelta(days=1)
    return out

def html_to_plain(mesaj_html):
    txt = re.sub(r"<[^>]+>", "\n", html.unescape(mesaj_html or ""))
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n{2,}", "\n", txt).strip()

def extract_phenomena_by_code(mesaj_html):
    sections = extract_sections_from_message(mesaj_html, datetime.now().year)
    if sections:
        return {s["code"]: s["phenomena"] for s in sections if s["phenomena"]}
    txt = html_to_plain(mesaj_html)
    heads = list(re.finditer(r"COD\s+(GALBEN|PORTOCALIU|RO[ȘS]U|VERDE)", txt, re.I))
    out = {}
    for i, h in enumerate(heads):
        cod = NUME_TO_COD[_norm(h.group(1))]
        seg = txt[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(txt)]
        m = re.search(r"Fenomene?\s+vizate\s*:?\s*(.+?)(?:\n|Zon|$)", seg, re.I)
        if m:
            out[str(cod)] = re.sub(r"\s+", " ", m.group(1)).strip(" ;.")
    return out

def make_alert_id(source, s_iso, e_iso, judete):
    if isinstance(judete, dict):
        judete_key = ",".join(f"{c}:{judete[c]}" for c in sorted(judete))
    else:
        judete_key = ",".join(sorted(judete))
    base = "|".join([source, s_iso, e_iso, judete_key])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

def nowcasting_dedupe_key(source, s_iso, e_iso, judete, feature_meta, fen):
    parts = []
    for code in sorted(judete):
        meta = feature_meta.get(code, {})
        localities = ";".join(sorted(normalize_ro_name(x) for x in meta.get("localities", [])))
        phenomenon = phenomenon_group(" ".join(str(v) for v in fen.values()))
        parts.append("|".join([
            str(source),
            "nowcasting",
            s_iso,
            e_iso,
            str(judete.get(code, "")),
            meta.get("county_name") or JUDETE.get(code, code),
            meta.get("zone_name") or "",
            localities,
            phenomenon,
        ]))
    return "||".join(parts)

def make_content_hash(mesaj_plain, judete_culori):
    base = (mesaj_plain or "") + "|" + ",".join(f"{c}:{col}" for c, col in sorted(judete_culori.items()))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

def _nowcasting_xml_adapt_attribs(av, source):
    """Normalize nowcasting XML attributes to match general XML format.

    Nowcasting XML endpoints use different attribute names:
      - Simple XML: dataInceput/dataSfarsit, zona, semnalare, culoare, numeCuloare
      - XML-GIS:    dataInceput/dataSfarsit, avertizareNivelDenumire, fenomenAvertizat,
                    coordsGis (note the 's'), <zona_afectata text="...">
    This function extracts data into a normalized dict.
    """
    a = dict(av.attrib)
    if not is_nowcasting_source(source):
        return a

    # Map dataInceput/dataSfarsit -> dataAparitiei/dataExpirarii if missing
    if not a.get("dataAparitiei") and a.get("dataInceput"):
        raw = a["dataInceput"].replace(" ", "T")
        a["dataAparitiei"] = raw
    if not a.get("dataExpirarii") and a.get("dataSfarsit"):
        raw = a["dataSfarsit"].replace(" ", "T")
        a["dataExpirarii"] = raw

    # Map numeCuloare / avertizareNivelDenumire -> culoare code
    # IMPORTANT: In nowcasting XML, 'culoare' is an internal ANM index (e.g. 1=portocaliu)
    # while in general XML, culoare matches MeteoAlert codes (1=galben, 2=portocaliu).
    # Always prefer the text name when available.
    nivel = a.get("avertizareNivelDenumire") or a.get("numeCuloare") or ""
    if nivel:
        resolved = color_code_from_value(nivel)
        if resolved > 0:
            a["culoare"] = str(resolved)

    # Map semnalare / fenomenAvertizat -> mesaj fallback
    if not a.get("mesaj"):
        semnalare = a.get("semnalare") or a.get("fenomenAvertizat") or ""
        if semnalare:
            a["_semnalare"] = semnalare

    # Map zona attr -> zonaAfectata
    if not a.get("zonaAfectata") and a.get("zona"):
        a["zonaAfectata"] = a["zona"]

    # Map coordsGis (with 's') -> coordGis
    if not a.get("coordGis") and a.get("coordsGis"):
        a["coordGis"] = a["coordsGis"]

    # Extract zona_afectata sub-element text (XML-GIS)
    for child in av:
        tag = child.tag.split("}")[-1] if isinstance(child.tag, str) else ""
        if tag == "zona_afectata" and child.attrib.get("text"):
            if not a.get("zonaAfectata"):
                a["zonaAfectata"] = child.attrib["text"]

    return a


def parse_avertizari(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    alerts = []
    # For XML-GIS, root itself may be the <avertizare> element
    root_tag = root.tag.split("}")[-1] if isinstance(root.tag, str) else ""
    if root_tag == "avertizare":
        alert_elements = [root]
    else:
        alert_elements = [el for el in root.iter() if isinstance(el.tag, str) and el.tag.split("}")[-1] == "avertizare"]
    for av in alert_elements:
        a = _nowcasting_xml_adapt_attribs(av, source)
        if not a.get("dataExpirarii") and not is_nowcasting_source(source):
            continue
        exp_dt = parse_xml_datetime(a.get("dataExpirarii"))
        ap_dt = parse_xml_datetime(a.get("dataAparitiei"))
        base_year = (exp_dt or ap_dt or datetime.now()).year
        mesaj_html = a.get("mesaj", "")
        mesaj_plain = html_to_plain(mesaj_html)
        # For nowcasting without mesaj, use semnalare/fenomenAvertizat as plain text
        if not mesaj_plain and is_nowcasting_source(source):
            mesaj_plain = a.get("_semnalare", "")
        sections = extract_sections_from_message(mesaj_html, base_year)
        sections_by_code = {}
        for sec in sections:
            if sec["code"] in sections_by_code:
                print(f"  ! multiple sections for code {sec['code']} in one ANM message; keeping first", file=sys.stderr)
                continue
            sections_by_code[sec["code"]] = sec

        s, e = parse_interval(a.get("intervalul", ""), a.get("dataAparitiei", ""), a.get("dataExpirarii", ""), mesaj_html)
        if is_nowcasting_source(source):
            hour_interval = parse_nowcasting_hour_interval(mesaj_plain or a.get("intervalul", ""), ap_dt or s or datetime.now())
            if hour_interval:
                s, e, parsed_interval_text = hour_interval
            else:
                parsed_interval_text = ""
        else:
            parsed_interval_text = ""

        judete = [j for j in av.iter() if isinstance(j.tag, str) and j.tag.split("}")[-1] == "judet"]
        jud_cul, geom, feature_meta = {}, {}, {}
        coord_count = 0
        fallback_count = 0
        default_color = color_code_from_value(a.get("culoare") or a.get("cod") or a.get("codCuloare"))
        if default_color <= 0:
            code_match = COD_RE.search(mesaj_plain)
            if code_match:
                default_color = NUME_TO_COD.get(_norm(code_match.group(1)), 0)

        # Check for alert-level coordGis (XML-GIS has it on the avertizare element itself)
        alert_level_geom = None
        alert_level_coord_gis = a.get("coordGis") or a.get("coordsGis") or ""
        if alert_level_coord_gis and is_nowcasting_source(source):
            try:
                alert_level_geom = wkt_to_geojson_geometry(alert_level_coord_gis)
            except Exception as ex:
                print(f"  ! alert-level coordGis parse fail: {ex}", file=sys.stderr)

        for j in judete:
            cod = (j.attrib.get("cod") or j.attrib.get("codJudet") or "").upper()
            if not cod:
                cod = county_code_for_name(j.attrib.get("nume") or j.attrib.get("judet") or "")
            if not cod:
                continue
            cul = safe_int(j.attrib.get("culoare"), default_color)
            jud_cul[cod] = cul
            zone_name = j.attrib.get("zona") or j.attrib.get("zonaNume") or JUDETE.get(cod, cod)
            localities = parse_locality_list(j.attrib.get("localitati") or j.attrib.get("localitatiAfectate") or "")
            geometry_source = "missing"
            match_confidence = "low"
            coord_gis_value = j.attrib.get("coordGis") or j.attrib.get("coordsGis") or ""
            if coord_gis_value:
                try:
                    geom[cod] = wkt_to_geojson_geometry(coord_gis_value)
                    coord_count += 1
                    geometry_source = "coordGis"
                    match_confidence = "high"
                except Exception as ex:
                    print(f"  ! coordGis parse fail {cod}: {ex}", file=sys.stderr)
            if cod not in geom and is_nowcasting_source(source):
                fallback_geom, geometry_source, match_confidence = fallback_geometry_for_nowcasting(cod, localities)
                if fallback_geom:
                    geom[cod] = fallback_geom
                    fallback_count += 1
            feature_meta[cod] = {
                "county_code": cod,
                "county_name": JUDETE.get(cod, cod),
                "zone_name": zone_name,
                "display_name": zone_name or JUDETE.get(cod, cod),
                "localities": localities,
                "geometry_source": geometry_source,
                "match_confidence": match_confidence,
            }

        if not jud_cul and is_nowcasting_source(source):
            # Try to extract counties from zona/zonaAfectata/zona_afectata text
            zona_text = a.get("zonaAfectata") or a.get("zona") or ""
            parsed_zones = parse_nowcasting_counties_and_localities(mesaj_plain or zona_text)
            if not parsed_zones and zona_text:
                parsed_zones = parse_nowcasting_counties_and_localities(zona_text)
            for zone in parsed_zones:
                cod = county_code_for_name(zone.get("county_name"))
                if not cod:
                    continue
                cul = default_color or 1
                localities = zone.get("localities") or []
                geometry_source = "missing"
                match_confidence = "low"
                # Use alert-level geometry if available (XML-GIS)
                if alert_level_geom:
                    geom[cod] = alert_level_geom
                    coord_count += 1
                    geometry_source = "coordGis"
                    match_confidence = "high"
                else:
                    fallback_geom, geometry_source, match_confidence = fallback_geometry_for_nowcasting(cod, localities)
                    if fallback_geom:
                        geom[cod] = fallback_geom
                        fallback_count += 1
                jud_cul[cod] = cul
                zone_name = f"{JUDETE.get(cod, zone.get('county_name', cod))} - localitati" if localities else JUDETE.get(cod, cod)
                feature_meta[cod] = {
                    "county_code": cod,
                    "county_name": JUDETE.get(cod, zone.get("county_name", cod)),
                    "zone_name": zone_name,
                    "display_name": zone_name,
                    "localities": localities,
                    "geometry_source": geometry_source,
                    "match_confidence": match_confidence,
                }

        if not jud_cul:
            continue

        fen = {code: sec["phenomena"] for code, sec in sections_by_code.items() if sec.get("phenomena")}
        if not fen:
            fen = extract_phenomena_by_code(mesaj_html)
        if not fen and is_nowcasting_source(source):
            # Fallback: use semnalare, fenomenAvertizat, fenomene, or mesaj_plain
            fallback_fen = (
                a.get("_semnalare")
                or a.get("fenomenAvertizat")
                or a.get("semnalare")
                or a.get("fenomene")
                or a.get("fenomeneVizate")
                or mesaj_plain
            )
            if fallback_fen:
                fen[str(max(jud_cul.values()) or default_color or 1)] = fallback_fen

        section_days = [
            set(zile_acoperite(sec["valid_from"], sec["valid_to"]))
            for sec in sections
            if sec.get("valid_from") and sec.get("valid_to")
        ]
        zile = sorted(set().union(*section_days)) if section_days else zile_acoperite(s, e)
        interval_text = a.get("intervalul", "") or parsed_interval_text
        section_intervals = []
        for sec in sections:
            if sec.get("interval_text") and sec["interval_text"] not in section_intervals:
                section_intervals.append(sec["interval_text"])
        if section_intervals and ("CONFORM TEXTELOR" in _norm(interval_text) or not interval_text):
            interval_text = "; ".join(section_intervals)
        if parsed_interval_text and not interval_text:
            interval_text = parsed_interval_text

        alert_id = make_alert_id(source, s.isoformat(), e.isoformat(), jud_cul)
        if is_nowcasting_source(source):
            key = nowcasting_dedupe_key(source, s.isoformat(), e.isoformat(), jud_cul, feature_meta, fen)
            alert_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

        zona_afectata_text = a.get("zonaAfectata") or a.get("zona") or ""
        data_emitere = a.get("dataAparitiei") or a.get("dataCreareAvertizare") or ""

        alerts.append({
            "source": source,
            "alert_type": "nowcasting" if is_nowcasting_source(source) else "general",
            "alert_id": alert_id,
            "content_hash": make_content_hash(mesaj_plain, jud_cul),
            "data_emitere": data_emitere,
            "interval_text": interval_text,
            "interval_start": s.isoformat(),
            "interval_end": e.isoformat(),
            "durata_ore": round((e - s).total_seconds() / 3600, 1),
            "cod_culoare_max": max(jud_cul.values()),
            "zona_afectata_text": zona_afectata_text,
            "zile": zile,
            "jud": jud_cul,
            "geom": geom,
            "fen": fen,
            "sections": sections,
            "sections_by_code": sections_by_code,
            "feature_meta": feature_meta,
            "coord_gis_count": coord_count,
            "fallback_geometry_count": fallback_count,
            "mesaj_html": mesaj_html,
            "mesaj_plain": mesaj_plain,
        })
    return alerts

def fetch_xml(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MeteoAlertRO/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def fetch_xml_with_status(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MeteoAlertRO/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        return data, getattr(r, "status", 200)

def xml_diagnostics(xml_bytes):
    root = ET.fromstring(xml_bytes)
    root_tag = root.tag.split("}")[-1] if isinstance(root.tag, str) else ""
    if root_tag == "avertizare":
        raw_alerts = [root]
    else:
        raw_alerts = [el for el in root.iter() if isinstance(el.tag, str) and el.tag.split("}")[-1] == "avertizare"]
    coord_count = 0
    for el in root.iter():
        if any(k.lower().endswith("coordgis") or k.lower().endswith("coordsgis") for k in el.attrib):
            coord_count += 1
    # Also check root attribs (XML-GIS has coords on root)
    if any(k.lower().endswith("coordgis") or k.lower().endswith("coordsgis") for k in root.attrib):
        coord_count = max(coord_count, 1)
    return {"raw_alert_count": len(raw_alerts), "coord_gis_count": coord_count}

# ------------------------------------------------------------------ arhiva CSV
CSV_FIELDS = ["alert_id","prima_aparitie_utc","ultima_actualizare_utc","revizuit","content_hash",
              "source","alert_type","data_emitere","interval_text","interval_start","interval_end","durata_ore",
              "cod_culoare_max","fenomene_pe_cod_json","zona_afectata_text",
              "judete_afectate","judete_count","judete_culori_json","feature_meta_json",
              "text_alerta_plain","text_alerta_html","source_url","source_label","notes"]

def csv_path_for(alert):
    ym = alert["interval_start"][:7]
    d = os.path.join(ISTORIC, ym[:4]); os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{ym}.csv")

def alert_to_row(alert, prima, ultima, revizuit):
    return {
        "alert_id": alert["alert_id"], "prima_aparitie_utc": prima,
        "ultima_actualizare_utc": ultima, "revizuit": str(revizuit).lower(),
        "content_hash": alert["content_hash"], "source": alert["source"],
        "alert_type": alert.get("alert_type", "nowcasting" if is_nowcasting_source(alert.get("source")) else "general"),
        "data_emitere": alert["data_emitere"], "interval_text": alert["interval_text"],
        "interval_start": alert["interval_start"], "interval_end": alert["interval_end"],
        "durata_ore": alert["durata_ore"], "cod_culoare_max": alert["cod_culoare_max"],
        "fenomene_pe_cod_json": json.dumps(alert["fen"], ensure_ascii=False),
        "zona_afectata_text": alert["zona_afectata_text"],
        "judete_afectate": ";".join(sorted(alert["jud"].keys())),
        "judete_count": len(alert["jud"]),
        "judete_culori_json": json.dumps(alert["jud"], ensure_ascii=False),
        "feature_meta_json": json.dumps(alert.get("feature_meta", {}), ensure_ascii=False),
        "text_alerta_plain": alert["mesaj_plain"], "text_alerta_html": alert["mesaj_html"],
        "source_url": alert.get("source_url", ""),
        "source_label": alert.get("source_label", ""),
        "notes": alert.get("notes", ""),
    }

def upsert_archive(alerts):
    by_file = defaultdict(list)
    for al in alerts:
        by_file[csv_path_for(al)].append(al)
    for path, group in by_file.items():
        rows = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    rows[r["alert_id"]] = r
        for al in group:
            superseded_prima = []
            for old_id, old_row in list(rows.items()):
                same_source = old_row.get("source") == al["source"]
                same_content = old_row.get("content_hash") == al["content_hash"]
                if old_id != al["alert_id"] and same_source and same_content:
                    superseded_prima.append(old_row.get("prima_aparitie_utc") or now_utc())
                    del rows[old_id]

            cur = rows.get(al["alert_id"])
            if cur is None:
                prima = min(superseded_prima + [now_utc()])
                rows[al["alert_id"]] = alert_to_row(al, prima, now_utc(), bool(superseded_prima))
            elif cur.get("content_hash") != al["content_hash"] or superseded_prima:
                prima = min(superseded_prima + [cur["prima_aparitie_utc"]])
                rows[al["alert_id"]] = alert_to_row(al, prima, now_utc(), True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS); w.writeheader()
            for r in sorted(rows.values(), key=lambda x: x["interval_start"]):
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})

MANUAL_NOWCASTING_FIELDS = [
    "date", "valid_from", "valid_to", "code", "code_name", "county_name",
    "localities", "phenomenon", "phenomenon_group", "message",
    "source_url", "source_label", "notes",
]

def ensure_manual_nowcasting_seed():
    os.makedirs(MANUAL_NOWCASTING, exist_ok=True)
    if os.path.exists(MANUAL_NOWCASTING_CSV):
        return
    row = {
        "date": "2026-06-30",
        "valid_from": "2026-06-30T20:50:00+03:00",
        "valid_to": "2026-06-30T21:40:00+03:00",
        "code": "2",
        "code_name": "Portocaliu",
        "county_name": "Bucuresti",
        "localities": "Bucuresti",
        "phenomenon": "ploi torentiale; descarcari electrice",
        "phenomenon_group": "ploi/vijelii",
        "message": "Import manual pentru episod nowcasting Bucuresti 30 iunie / 1 iulie. Detaliile complete nu au fost capturate de scraper la momentul activ.",
        "source_url": "",
        "source_label": "import manual",
        "notes": "detalii incomplete; match_confidence=low; geometry_source=county_fallback",
    }
    with open(MANUAL_NOWCASTING_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_NOWCASTING_FIELDS)
        writer.writeheader()
        writer.writerow(row)

def parse_manual_nowcasting_datetime(value, fallback_date):
    parsed = parse_iso_datetime(value)
    if parsed:
        return parsed
    if re.match(r"^\d{1,2}:\d{2}$", str(value or "")):
        h, m = map(int, str(value).split(":"))
        base = datetime.fromisoformat(fallback_date)
        return base.replace(hour=h, minute=m)
    return datetime.fromisoformat(fallback_date)

def load_manual_nowcasting_alerts():
    ensure_manual_nowcasting_seed()
    if not os.path.exists(MANUAL_NOWCASTING_CSV):
        return []
    alerts = []
    with open(MANUAL_NOWCASTING_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            date_value = (row.get("date") or today_iso()).strip()
            county_name = (row.get("county_name") or "").strip()
            county_code = county_code_for_name(county_name)
            if not county_code:
                print(f"[nowcasting_manual] judet necunoscut: {county_name}", file=sys.stderr)
                continue
            start = parse_manual_nowcasting_datetime(row.get("valid_from"), date_value)
            end = parse_manual_nowcasting_datetime(row.get("valid_to"), date_value)
            if end < start:
                end += timedelta(days=1)
            code = color_code_from_value(row.get("code") or row.get("code_name") or "1") or 1
            localities = parse_locality_list(row.get("localities", ""))
            geometry, geometry_source, match_confidence = fallback_geometry_for_nowcasting(county_code, localities)
            phenomenon = row.get("phenomenon") or "nowcasting"
            feature_meta = {
                county_code: {
                    "county_code": county_code,
                    "county_name": JUDETE.get(county_code, county_name),
                    "zone_name": row.get("county_name") or JUDETE.get(county_code, county_code),
                    "display_name": row.get("county_name") or JUDETE.get(county_code, county_code),
                    "localities": localities,
                    "geometry_source": geometry_source,
                    "match_confidence": match_confidence,
                }
            }
            jud = {county_code: code}
            fen = {str(code): phenomenon}
            key = nowcasting_dedupe_key("nowcasting_manual", start.isoformat(), end.isoformat(), jud, feature_meta, fen)
            alert_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
            alerts.append({
                "source": "nowcasting_manual",
                "alert_type": "nowcasting",
                "alert_id": alert_id,
                "content_hash": make_content_hash(row.get("message", ""), jud),
                "data_emitere": start.isoformat(),
                "interval_text": row.get("interval_valabilitate_text") or f"{start.isoformat(timespec='minutes')} - {end.isoformat(timespec='minutes')}",
                "interval_start": start.isoformat(),
                "interval_end": end.isoformat(),
                "durata_ore": round((end - start).total_seconds() / 3600, 1),
                "cod_culoare_max": code,
                "zona_afectata_text": row.get("county_name") or JUDETE.get(county_code, county_code),
                "zile": zile_acoperite(start, end),
                "jud": jud,
                "geom": {county_code: geometry} if geometry else {},
                "fen": fen,
                "sections": [],
                "sections_by_code": {},
                "feature_meta": feature_meta,
                "coord_gis_count": 0,
                "fallback_geometry_count": 1 if geometry else 0,
                "source_url": row.get("source_url", ""),
                "source_label": row.get("source_label", "import manual"),
                "notes": row.get("notes", ""),
                "mesaj_html": html.escape(row.get("message", "")),
                "mesaj_plain": row.get("message", ""),
            })
    print(f"[nowcasting_manual] {len(alerts)} avertizari importate din {MANUAL_NOWCASTING_CSV.replace(os.sep, '/')}")
    return alerts

# ------------------------------------------------------------------ generare derivate
def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

def phenomenon_group(text):
    t = _norm(text or "")
    if re.search(r"CANICUL|CALDURA|TEMPERATURI|TROPICAL|DISCONFORT", t):
        return "temperaturi extreme"
    if re.search(r"PLOI|PLOAIE|AVERSE|VIJEL|FURTUN|GRINDIN|INSTABILITATE|DESCARCARI", t):
        return "ploi/vijelii"
    if re.search(r"NINSO|ZAPADA|VISCOL", t):
        return "ninsori/viscol"
    if re.search(r"CEATA", t):
        return "ceata"
    return "alte fenomene"

def _section_for_code(al, cul):
    return al.get("sections_by_code", {}).get(str(cul))

def _feature_interval(al, cul):
    sec = _section_for_code(al, cul)
    if sec and sec.get("valid_from") and sec.get("valid_to"):
        return sec["valid_from"], sec["valid_to"], sec.get("interval_text") or al["interval_text"]
    return datetime.fromisoformat(al["interval_start"]), datetime.fromisoformat(al["interval_end"]), al["interval_text"]

def _all_features(alerts_subset, day):
    """All active features for a day. Overlapping alerts are preserved."""
    feats = []
    for al in alerts_subset:
        for jcod, cul in sorted(al["jud"].items()):
            if cul <= 0 or jcod not in al["geom"]:
                continue
            fs, fe, interval_text = _feature_interval(al, cul)
            if day not in zile_acoperite(fs, fe):
                continue
            fenomen = al["fen"].get(str(cul), "")
            sec = _section_for_code(al, cul) or {}
            meta = al.get("feature_meta", {}).get(jcod, {})
            county_name = meta.get("county_name") or JUDETE.get(jcod, jcod)
            zone_name = meta.get("zone_name") or meta.get("display_name") or county_name
            source = al.get("source", "general")
            feats.append({
                "type": "Feature", "geometry": al["geom"][jcod],
                "properties": {
                    "alert_id": al["alert_id"], "source": source,
                    "alert_type": al.get("alert_type", "nowcasting" if is_nowcasting_source(source) else "general"),
                    "feature_id": hashlib.sha1(f"{al['alert_id']}|{jcod}|{cul}|{day}".encode("utf-8")).hexdigest()[:18],
                    "judet_cod": jcod, "judet_nume": county_name,
                    "county_code": jcod, "county_name": county_name,
                    "cod_judet": jcod,
                    "cod_culoare": cul, "cod_culoare_nume": COD_TO_NUME[cul],
                    "culoare": str(cul), "cod": COD_TO_NUME[cul],
                    "fenomen_principal": fenomen,
                    "fenomen_group": phenomenon_group(fenomen),
                    "zona_text": sec.get("zones_text") or al["zona_afectata_text"],
                    "zona_nume": zone_name,
                    "zone_name": zone_name,
                    "display_name": meta.get("display_name") or zone_name,
                    "localities": meta.get("localities", []),
                    "geometry_source": meta.get("geometry_source", "coordGis" if jcod in al.get("geom", {}) else "missing"),
                    "match_confidence": meta.get("match_confidence", "high" if jcod in al.get("geom", {}) else "low"),
                    "interval_text": interval_text, "interval_start": fs.isoformat(),
                    "valid_from": fs.isoformat(), "valid_to": fe.isoformat(),
                    "interval_valabilitate_text": interval_text,
                    "interval_end": fe.isoformat(), "data_expirare": fe.isoformat(),
                    "mesaj_plain": al.get("mesaj_plain", ""),
                    "source_url": al.get("source_url", ""),
                    "source_label": al.get("source_label", ""),
                    "notes": al.get("notes", ""),
                    "durata_ore": round((fe - fs).total_seconds() / 3600, 1), "zi": day,
                },
            })
    return feats

def _county_metadata(features):
    grouped = defaultdict(list)
    for feature in features:
        grouped[feature["properties"]["judet_cod"]].append(feature)
    alerts_by_county, max_by_county = {}, {}
    for jcod, feats in sorted(grouped.items()):
        entries = []
        alert_ids = set()
        max_color = 0
        phenomena = set()
        for feature in feats:
            p = feature["properties"]
            color = int(p.get("cod_culoare") or 0)
            alert_ids.add(p.get("alert_id"))
            max_color = max(max_color, color)
            phenomena.add(p.get("fenomen_group") or phenomenon_group(p.get("fenomen_principal", "")))
            entries.append({
                "alert_id": p.get("alert_id"),
                "cod": COD_TO_NUME.get(color, "Verde"),
                "culoare": str(color),
                "fenomen_group": p.get("fenomen_group") or phenomenon_group(p.get("fenomen_principal", "")),
                "source": p.get("source", "general"),
            })
        alerts_by_county[jcod] = entries
        max_by_county[jcod] = {
            "max_color": max_color,
            "alert_count": len(alert_ids),
            "phenomena": sorted(phenomena),
        }
    return alerts_by_county, max_by_county

def _alert_card(al):
    color_counts = {}
    for cul in al["jud"].values():
        if cul > 0:
            color_counts[str(cul)] = color_counts.get(str(cul), 0) + 1
    return {
        "alert_id": al["alert_id"], "source": al["source"],
        "alert_type": al.get("alert_type", "nowcasting" if is_nowcasting_source(al.get("source")) else "general"),
        "interval_text": al["interval_text"], "interval_start": al["interval_start"],
        "interval_end": al["interval_end"], "durata_ore": al["durata_ore"],
        "valid_from": al["interval_start"], "valid_to": al["interval_end"],
        "cod_culoare_max": al["cod_culoare_max"], "fenomene_pe_cod": al["fen"],
        "judete_afectate": sorted([c for c, v in al["jud"].items() if v > 0]),
        "judete_count": sum(1 for v in al["jud"].values() if v > 0),
        "judete_culori": al["jud"], "color_counts": color_counts,
        "text_alerta_html": al["mesaj_html"],
        "message": al.get("mesaj_plain", ""),
        "feature_meta": al.get("feature_meta", {}),
        "source_url": al.get("source_url", ""),
        "source_label": al.get("source_label", ""),
        "notes": al.get("notes", ""),
    }

def build_daily_geojson(alerts, day):
    active = [a for a in alerts if day in a["zile"]]
    general = [a for a in active if not is_nowcasting_source(a.get("source"))]
    nowcast = [a for a in active if is_nowcasting_source(a.get("source"))]
    general_feats = _all_features(general, day)
    nowcast_feats = _all_features(nowcast, day)
    feats = general_feats + nowcast_feats
    cards = [_alert_card(a) for a in general] + [_alert_card(a) for a in nowcast]
    fc = {
        "type": "FeatureCollection",
        "metadata": {"date": day, "active_alerts": cards},
        "features": feats,
    }
    refresh_geojson_metadata(fc, day)
    return fc

def refresh_geojson_metadata(fc, day):
    feats = fc.get("features", [])
    cards = fc.get("metadata", {}).get("active_alerts", [])
    general_cards = [r for r in cards if not is_nowcasting_source(r.get("source"))]
    nowcast_cards = [r for r in cards if is_nowcasting_source(r.get("source"))]
    manual_cards = [r for r in nowcast_cards if str(r.get("source", "")).lower() == "nowcasting_manual"]
    general_feats = [f for f in feats if not is_nowcasting_source(f.get("properties", {}).get("source"))]
    nowcast_feats = [f for f in feats if is_nowcasting_source(f.get("properties", {}).get("source"))]
    alerts_by_county, max_by_county = _county_metadata(feats)
    sources = sorted({r.get("source") for r in cards if r.get("source")} | {f.get("properties", {}).get("source") for f in feats if f.get("properties", {}).get("source")})
    has_nowcasting = bool(nowcast_cards or nowcast_feats)
    has_manual_nowcasting = bool(manual_cards)
    fc.setdefault("metadata", {})
    fc["metadata"].update({
        "date": day,
        "alert_count": len({r.get("alert_id") for r in cards if r.get("alert_id")}),
        "general_alert_count": len({r.get("alert_id") for r in general_cards if r.get("alert_id")}),
        "nowcasting_alert_count": len({r.get("alert_id") for r in nowcast_cards if r.get("alert_id")}),
        "manual_nowcasting_alert_count": len({r.get("alert_id") for r in manual_cards if r.get("alert_id")}),
        "feature_count": len(feats),
        "general_feature_count": len(general_feats),
        "nowcasting_feature_count": len(nowcast_feats),
        "max_color": max((safe_int(f.get("properties", {}).get("cod_culoare"), 0) for f in feats), default=0),
        "general_max_color": max((safe_int(f.get("properties", {}).get("cod_culoare"), 0) for f in general_feats), default=0),
        "nowcasting_count": len({r.get("alert_id") for r in nowcast_cards if r.get("alert_id")}),
        "has_nowcasting": has_nowcasting,
        "has_manual_nowcasting": has_manual_nowcasting,
        "calendar_badge": "NC*" if has_manual_nowcasting else "NC" if has_nowcasting else "",
        "sources": sources,
        "alerts_by_county": alerts_by_county,
        "max_by_county": max_by_county,
    })
    return fc

def daily_geojson_paths():
    if not os.path.isdir(DATA):
        return []
    return [
        os.path.join(DATA, name)
        for name in sorted(os.listdir(DATA))
        if re.match(r"^\d{4}-\d{2}-\d{2}\.geojson$", name)
    ]

def index_entry_from_geojson(day, fc):
    feats = fc.get("features", [])
    meta = fc.get("metadata", {})
    records = meta.get("active_alerts", [])
    general_feats = [f for f in feats if not is_nowcasting_source(f.get("properties", {}).get("source"))]
    nowcast_feats = [f for f in feats if is_nowcasting_source(f.get("properties", {}).get("source"))]
    general_records = [r for r in records if not is_nowcasting_source(r.get("source"))]
    nowcast_records = [r for r in records if is_nowcasting_source(r.get("source"))]
    manual_records = [r for r in nowcast_records if str(r.get("source", "")).lower() == "nowcasting_manual"]
    codes = sorted({
        int(f.get("properties", {}).get("cod_culoare") or 0)
        for f in feats
        if int(f.get("properties", {}).get("cod_culoare") or 0) > 0
    })
    phenomena = sorted({
        f.get("properties", {}).get("fenomen_group")
        or phenomenon_group(f.get("properties", {}).get("fenomen_principal", ""))
        for f in feats
        if f.get("properties")
    })
    sources = sorted({f.get("properties", {}).get("source") for f in feats if f.get("properties", {}).get("source")} | {r.get("source") for r in records if r.get("source")})
    max_color = meta.get("max_color")
    if max_color is None:
        max_color = max(codes, default=0)
    has_nowcasting = bool(meta.get("has_nowcasting", nowcast_records or nowcast_feats))
    has_manual_nowcasting = bool(meta.get("has_manual_nowcasting", manual_records))
    return {
        "date": day,
        "general_alert_count": meta.get("general_alert_count", len({r.get("alert_id") for r in general_records if r.get("alert_id")})),
        "nowcasting_alert_count": meta.get("nowcasting_alert_count", len({r.get("alert_id") for r in nowcast_records if r.get("alert_id")})),
        "manual_nowcasting_alert_count": meta.get("manual_nowcasting_alert_count", len({r.get("alert_id") for r in manual_records if r.get("alert_id")})),
        "alert_count": meta.get("alert_count", len({r.get("alert_id") for r in records if r.get("alert_id")})),
        "feature_count": meta.get("feature_count", len(feats)),
        "general_feature_count": meta.get("general_feature_count", len(general_feats)),
        "nowcasting_feature_count": meta.get("nowcasting_feature_count", len(nowcast_feats)),
        "max_color": max_color,
        "max_code": max_color,
        "general_max_color": meta.get("general_max_color", max((safe_int(f.get("properties", {}).get("cod_culoare"), 0) for f in general_feats), default=0)),
        "nowcasting_count": meta.get("nowcasting_count", len({r.get("alert_id") for r in nowcast_records if r.get("alert_id")})),
        "has_nowcasting": has_nowcasting,
        "has_manual_nowcasting": has_manual_nowcasting,
        "calendar_badge": "NC*" if has_manual_nowcasting else "NC" if has_nowcasting else "",
        "sources": sources,
        "has_geojson": True,
        "has_archive": False,
        "file": f"{day}.geojson",
        "codes": codes,
        "phenomena": phenomena,
    }

def point_in_polygon(x, y, poly):
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def get_county_for_wgs(lon, lat):
    try:
        with open(os.path.join(DATA, "judete.geojson"), encoding="utf-8") as f:
            judete = json.load(f)
    except Exception:
        return None
    for feat in judete.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") == "MultiPolygon":
            for poly in geom.get("coordinates", []):
                for ring in poly:
                    if point_in_polygon(lon, lat, ring):
                        return feat.get("properties", {}).get("judet_cod")
        elif geom.get("type") == "Polygon":
            for ring in geom.get("coordinates", []):
                if point_in_polygon(lon, lat, ring):
                    return feat.get("properties", {}).get("judet_cod")
    return None

def fetch_and_save_current_weather():
    url = "https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii"
    out_path = os.path.join(DATA, "current_weather.json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MeteoAlertRO/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        stations = []
        by_county = defaultdict(list)
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            lon, lat = 0, 0
            if len(coords) == 2:
                # API returns EPSG:3857 coordinates
                lon, lat = merc_to_wgs(float(coords[0]), float(coords[1]))
            county_code = get_county_for_wgs(lon, lat)
            county_name = JUDETE.get(county_code, county_code) if county_code else "Necunoscut"
            st = {
                "station_name": props.get("nume", "Necunoscut"),
                "county_name": county_name,
                "temperature_c": float(props.get("tempe")) if props.get("tempe") and props.get("tempe") != "indisponibil" else None,
                "weather": props.get("nebulozitate") or props.get("fenomen_e") or "",
                "humidity": props.get("umezeala"),
                "wind": props.get("vant"),
                "raw": props
            }
            stations.append(st)
            if county_name != "Necunoscut":
                by_county[county_name].append(st)
        
        result = {
            "fetched_at_utc": now_utc(),
            "source": "meteoromania.ro",
            "stations": stations,
            "by_county": dict(by_county)
        }
        write_json(out_path, result)
        print(f"[current_weather] Salvat {len(stations)} statii in {out_path}")
    except Exception as e:
        print(f"[current_weather] Avertisment: Nu s-a putut descarca starea vremii: {e}", file=sys.stderr)

def archive_index_entries():
    by_day = defaultdict(lambda: {
        "alert_ids": set(),
        "general_ids": set(),
        "nowcasting_ids": set(),
        "manual_nowcasting_ids": set(),
        "sources": set(),
        "codes": set(),
        "phenomena": set(),
        "max_color": 0,
    })
    for path in sorted(glob_csv()):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                start = parse_iso_datetime(r.get("interval_start"))
                end = parse_iso_datetime(r.get("interval_end"))
                if not start or not end:
                    continue
                code = int(r.get("cod_culoare_max") or 0)
                try:
                    fen_by_code = json.loads(r.get("fenomene_pe_cod_json") or "{}")
                except json.JSONDecodeError:
                    fen_by_code = {}
                phenomena = {
                    phenomenon_group(text)
                    for text in fen_by_code.values()
                    if str(text).strip()
                }
                source = str(r.get("source") or "")
                is_nc = is_nowcasting_source(source)
                is_manual_nc = source.lower() == "nowcasting_manual"
                alert_id = r.get("alert_id") or r.get("content_hash") or ""
                for day in zile_acoperite(start, end):
                    entry = by_day[day]
                    entry["alert_ids"].add(alert_id or day)
                    if source:
                        entry["sources"].add(source)
                    if not is_nc and alert_id:
                        entry["general_ids"].add(alert_id)
                    if is_nc and alert_id:
                        entry["nowcasting_ids"].add(alert_id)
                    if is_manual_nc and alert_id:
                        entry["manual_nowcasting_ids"].add(alert_id)
                    if code > 0:
                        entry["codes"].add(code)
                    entry["phenomena"].update(phenomena)
                    entry["max_color"] = max(entry["max_color"], code)
    return by_day

def rebuild_data_index():
    t = today_iso()
    dates = {}
    for path in daily_geojson_paths():
        day = os.path.basename(path)[:-8]
        try:
            with open(path, encoding="utf-8") as f:
                fc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        dates[day] = index_entry_from_geojson(day, fc)

    for day, archived in archive_index_entries().items():
        if day in dates:
            dates[day]["has_archive"] = True
            dates[day]["archive_alert_count"] = len(archived["alert_ids"])
            dates[day]["archive_nowcasting_alert_count"] = len(archived["nowcasting_ids"])
            dates[day]["has_nowcasting"] = bool(dates[day].get("has_nowcasting") or archived["nowcasting_ids"])
            dates[day]["has_manual_nowcasting"] = bool(dates[day].get("has_manual_nowcasting") or archived["manual_nowcasting_ids"])
            dates[day]["nowcasting_alert_count"] = max(safe_int(dates[day].get("nowcasting_alert_count"), 0), len(archived["nowcasting_ids"]))
            dates[day]["manual_nowcasting_alert_count"] = max(safe_int(dates[day].get("manual_nowcasting_alert_count"), 0), len(archived["manual_nowcasting_ids"]))
            dates[day]["sources"] = sorted(set(dates[day].get("sources", [])) | archived["sources"])
            continue
        dates[day] = {
            "date": day,
            "file": None,
            "has_geojson": False,
            "has_archive": True,
            "alert_count": len(archived["alert_ids"]),
            "general_alert_count": len(archived["general_ids"]),
            "nowcasting_alert_count": len(archived["nowcasting_ids"]),
            "manual_nowcasting_alert_count": len(archived["manual_nowcasting_ids"]),
            "feature_count": 0,
            "max_color": None,
            "max_code": None,
            "nowcasting_count": len(archived["nowcasting_ids"]),
            "has_nowcasting": len(archived["nowcasting_ids"]) > 0,
            "has_manual_nowcasting": len(archived["manual_nowcasting_ids"]) > 0,
            "sources": sorted(archived["sources"]),
            "codes": sorted(archived["codes"]),
            "phenomena": sorted(archived["phenomena"]),
        }

    geojson_days = [day for day, entry in dates.items() if entry.get("has_geojson")]
    current_geojson_days = [day for day in geojson_days if day <= t]
    latest_day = max(current_geojson_days) if current_geojson_days else (max(geojson_days) if geojson_days else None)
    index = {
        "generated_at_utc": now_utc(),
        "today": t,
        "latest_date": latest_day,
        "dates": {day: dates[day] for day in sorted(dates)},
    }
    write_json(os.path.join(DATA, "index.json"), index)
    return index, latest_day

def record_key(record):
    return record.get("alert_id") or hashlib.sha1(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]

def feature_key(feature):
    props = feature.get("properties", {})
    return props.get("feature_id") or "|".join([
        str(props.get("alert_id", "")),
        str(props.get("judet_cod") or props.get("county_code") or ""),
        str(props.get("zone_name") or props.get("zona_nume") or ""),
        str(props.get("cod_culoare") or ""),
        str(props.get("interval_start") or props.get("valid_from") or ""),
        str(props.get("interval_end") or props.get("valid_to") or ""),
    ])

def merge_persistent_nowcasting(day, fc):
    path = os.path.join(DATA, f"{day}.geojson")
    if not os.path.exists(path):
        refresh_geojson_metadata(fc, day)
        return fc
    try:
        with open(path, encoding="utf-8") as f:
            old_fc = json.load(f)
    except (OSError, json.JSONDecodeError):
        refresh_geojson_metadata(fc, day)
        return fc

    preserve_all_existing = day < today_iso()

    def should_preserve_record(record):
        return preserve_all_existing or is_nowcasting_source(record.get("source"))

    def should_preserve_feature(feature):
        return preserve_all_existing or is_nowcasting_source(feature.get("properties", {}).get("source"))

    new_record_ids = {record_key(r) for r in fc.get("metadata", {}).get("active_alerts", [])}
    old_records = [
        r for r in old_fc.get("metadata", {}).get("active_alerts", [])
        if should_preserve_record(r) and record_key(r) not in new_record_ids
    ]
    for record in old_records:
        if not is_nowcasting_source(record.get("source")):
            continue
        preserve_key = f"{day}|{record_key(record)}"
        if preserve_key not in NOWCASTING_RUNTIME_STATS["_archived_preserved_keys"]:
            NOWCASTING_RUNTIME_STATS["_archived_preserved_keys"].add(preserve_key)
            NOWCASTING_RUNTIME_STATS["archived_preserved"] += 1
    if old_records:
        fc.setdefault("metadata", {}).setdefault("active_alerts", []).extend(old_records)

    new_feature_keys = {feature_key(f) for f in fc.get("features", [])}
    new_alert_ids = {f.get("properties", {}).get("alert_id") for f in fc.get("features", [])}
    old_features = []
    for feature in old_fc.get("features", []):
        props = feature.get("properties", {})
        if not should_preserve_feature(feature):
            continue
        if props.get("alert_id") in new_alert_ids or feature_key(feature) in new_feature_keys:
            continue
        old_features.append(feature)
    if old_features:
        fc.setdefault("features", []).extend(old_features)

    refresh_geojson_metadata(fc, day)
    return fc

def generate_all(alerts):
    all_days = sorted(set().union(*[set(a["zile"]) for a in alerts])) if alerts else []
    for day in all_days:
        fc = build_daily_geojson(alerts, day)
        fc = merge_persistent_nowcasting(day, fc)
        write_json(os.path.join(DATA, f"{day}.geojson"), fc)

    index, latest_day = rebuild_data_index()
    if latest_day:
        latest_path = os.path.join(DATA, f"{latest_day}.geojson")
        if latest_day in all_days:
            latest = build_daily_geojson(alerts, latest_day)
            latest = merge_persistent_nowcasting(latest_day, latest)
        else:
            with open(latest_path, encoding="utf-8") as f:
                latest = json.load(f)
        latest["metadata"]["latest_for_date"] = latest_day
        refresh_geojson_metadata(latest, latest_day)
        write_json(os.path.join(DATA, "latest.geojson"), latest)

    rebuild_history_stats()
    rebuild_istoric_manifest()
    rebuild_nowcasting_archive()
    rebuild_all_alerts_csv()
    return index, latest_day

NOWCASTING_CSV_FIELDS = [
    "date", "valid_from", "valid_to", "source", "county_name", "zone_name",
    "localities", "code", "code_name", "phenomenon", "phenomenon_group",
    "geometry_source", "match_confidence", "alert_id", "message",
    "source_url", "source_label",
]

def rebuild_nowcasting_archive():
    rows_by_month = defaultdict(list)
    for path in daily_geojson_paths():
        day = os.path.basename(path)[:-8]
        try:
            with open(path, encoding="utf-8") as f:
                fc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for feature in fc.get("features", []):
            props = feature.get("properties", {})
            if not is_nowcasting_source(props.get("source")):
                continue
            start = props.get("valid_from") or props.get("interval_start") or day
            month = str(start)[:7]
            rows_by_month[month].append({
                "date": day,
                "valid_from": start,
                "valid_to": props.get("valid_to") or props.get("interval_end") or "",
                "source": props.get("source", ""),
                "county_name": props.get("county_name") or props.get("judet_nume") or "",
                "zone_name": props.get("zone_name") or props.get("zona_nume") or "",
                "localities": "; ".join(props.get("localities") or []),
                "code": props.get("cod_culoare") or props.get("culoare") or "",
                "code_name": props.get("cod_culoare_nume") or props.get("cod") or "",
                "phenomenon": props.get("fenomen_principal") or "",
                "phenomenon_group": props.get("fenomen_group") or phenomenon_group(props.get("fenomen_principal", "")),
                "geometry_source": props.get("geometry_source") or "",
                "match_confidence": props.get("match_confidence") or "",
                "alert_id": props.get("alert_id") or "",
                "message": props.get("mesaj_plain") or "",
                "source_url": props.get("source_url") or "",
                "source_label": props.get("source_label") or "",
            })

        # Keep records without geometry visible in the separate archive too.
        feature_alerts = {f.get("properties", {}).get("alert_id") for f in fc.get("features", [])}
        for record in fc.get("metadata", {}).get("active_alerts", []):
            if not is_nowcasting_source(record.get("source")) or record.get("alert_id") in feature_alerts:
                continue
            start = record.get("valid_from") or record.get("interval_start") or day
            month = str(start)[:7]
            rows_by_month[month].append({
                "date": day,
                "valid_from": start,
                "valid_to": record.get("valid_to") or record.get("interval_end") or "",
                "source": record.get("source", ""),
                "county_name": "",
                "zone_name": "",
                "localities": "",
                "code": record.get("cod_culoare_max") or "",
                "code_name": COD_TO_NUME.get(safe_int(record.get("cod_culoare_max"), 0), ""),
                "phenomenon": "; ".join(str(v) for v in (record.get("fenomene_pe_cod") or {}).values()),
                "phenomenon_group": phenomenon_group(" ".join(str(v) for v in (record.get("fenomene_pe_cod") or {}).values())),
                "geometry_source": "missing",
                "match_confidence": "low",
                "alert_id": record.get("alert_id") or "",
                "message": record.get("message") or "",
                "source_url": record.get("source_url") or "",
                "source_label": record.get("source_label") or "",
            })

    out_dir = os.path.join(ISTORIC, "nowcasting")
    os.makedirs(out_dir, exist_ok=True)
    for month, rows in rows_by_month.items():
        path = os.path.join(out_dir, f"{month}.csv")
        unique = {}
        for row in rows:
            key = "|".join([row.get("alert_id", ""), row.get("county_name", ""), row.get("zone_name", ""), row.get("valid_from", "")])
            unique[key] = row
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NOWCASTING_CSV_FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in sorted(unique.values(), key=lambda r: (r["valid_from"], r["county_name"], r["zone_name"])):
                writer.writerow({k: row.get(k, "") for k in NOWCASTING_CSV_FIELDS})

def rebuild_all_alerts_csv():
    rows = {}
    for path in sorted(glob_csv()):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = row.get("alert_id") or stable_hash(json.dumps(row, sort_keys=True, ensure_ascii=False))
                current = rows.get(key)
                if not current or row.get("ultima_actualizare_utc", "") >= current.get("ultima_actualizare_utc", ""):
                    rows[key] = row
    out_path = os.path.join(ISTORIC, "toate-alertele.csv")
    os.makedirs(ISTORIC, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: (r.get("interval_start", ""), r.get("source", ""), r.get("alert_id", ""))):
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})

def glob_csv():
    import glob
    return [path for path in glob.glob(os.path.join(ISTORIC, "*", "*.csv")) if os.path.basename(os.path.dirname(path)).isdigit()]

def rebuild_history_stats():
    acc = {}
    for path in sorted(glob_csv()):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                end = r["interval_end"]
                for jcod, cul in json.loads(r["judete_culori_json"]).items():
                    cul = int(cul)
                    c = acc.setdefault(jcod, {"judet_cod": jcod, "judet_nume": JUDETE.get(jcod, jcod),
                                              "alert_count": 0, "max_color": 0,
                                              "last_alert_end": None, "color_counts": {}})
                    c["alert_count"] += 1
                    c["max_color"] = max(c["max_color"], cul)
                    if cul > 0:
                        c["color_counts"][str(cul)] = c["color_counts"].get(str(cul), 0) + 1
                    if c["last_alert_end"] is None or end > c["last_alert_end"]:
                        c["last_alert_end"] = end
    counties = sorted(acc.values(), key=lambda x: x["judet_cod"])
    write_json(os.path.join(DATA, "history_stats.json"),
               {"generated_at_utc": now_utc(), "counties": counties})

def rebuild_istoric_manifest():
    months = []
    for path in sorted(glob_csv()):
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if not rows: continue
        dates = [r["interval_start"][:10] for r in rows]
        months.append({
            "month": os.path.basename(path)[:7],
            "path": os.path.relpath(path, PUBLIC).replace(os.sep, "/"),
            "alert_count": len(rows), "first_alert": min(dates), "last_alert": max(dates),
            "max_color": max(int(r["cod_culoare_max"] or 0) for r in rows),
            "size_bytes": os.path.getsize(path),
        })
    months.sort(key=lambda m: m["month"], reverse=True)
    write_json(os.path.join(ISTORIC, "index.json"), {"generated_at_utc": now_utc(), "months": months})
    lines = ["# Arhivă avertizări ANM (MeteoAlertRO)", "",
             "CSV lunar, un rând per avertizare logică. Encoding UTF-8 (BOM).", "",
             "| Lună | Alerte | Interval | Cod max | Fișier |", "|---|---|---|---|---|"]
    for m in months:
        fn = os.path.basename(m["path"])
        rel = m["path"].split("istoric/", 1)[-1]
        lines.append(f"| {m['month']} | {m['alert_count']} | {m['first_alert']}–{m['last_alert']} "
                     f"| {COD_TO_NUME[m['max_color']]} | [{fn}]({rel}) |")
    os.makedirs(ISTORIC, exist_ok=True)
    with open(os.path.join(ISTORIC, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

# (duplicate main/glob_csv/rebuild_history_stats/rebuild_istoric_manifest removed — see below)

def reset_nowcasting_runtime_stats():
    for key in ("live_alerts", "manual_imported", "archived_preserved", "with_coord_gis", "uat_fallback", "county_fallback", "without_geometry"):
        NOWCASTING_RUNTIME_STATS[key] = 0
    NOWCASTING_RUNTIME_STATS["_archived_preserved_keys"].clear()

def update_nowcasting_geometry_stats(alerts):
    counts = {
        "with_coord_gis": 0,
        "uat_fallback": 0,
        "county_fallback": 0,
        "without_geometry": 0,
    }
    for alert in alerts:
        if not is_nowcasting_source(alert.get("source")):
            continue
        geometry_sources = {
            (meta or {}).get("geometry_source")
            for meta in (alert.get("feature_meta") or {}).values()
            if meta
        }
        if alert.get("coord_gis_count", 0) > 0 or "coordGis" in geometry_sources:
            counts["with_coord_gis"] += 1
        elif "uat_match" in geometry_sources:
            counts["uat_fallback"] += 1
        elif "county_fallback" in geometry_sources:
            counts["county_fallback"] += 1
        else:
            counts["without_geometry"] += 1
    NOWCASTING_RUNTIME_STATS.update(counts)

def log_geodata_status():
    county_geodata_features()
    uat_geodata_features()
    county_schema = GEODATA_STATS.get("county_schema") or {}
    uat_schema = GEODATA_STATS.get("uat_schema") or {}
    county_crs = GEODATA_STATS.get("county_crs") or "-"
    uat_crs = GEODATA_STATS.get("uat_crs") or "-"
    print(
        "[geodata] "
        f"judete_path={GEODATA_STATS.get('county_path') or '-'} "
        f"judete={GEODATA_STATS.get('county_count', 0)} "
        f"schema_judet_nume={county_schema.get('county_name') or '-'} "
        f"schema_judet_cod={county_schema.get('county_code') or '-'}"
    )
    print(
        "[geodata] "
        f"judete_crs_detected={county_crs} "
        f"transformed_to={'EPSG:4326' if GEODATA_STATS.get('county_transformed') else county_crs}"
    )
    print(
        "[geodata] "
        f"uat_path={GEODATA_STATS.get('uat_path') or '-'} "
        f"uat={GEODATA_STATS.get('uat_count', 0)} "
        f"schema_uat_nume={uat_schema.get('uat_name') or '-'} "
        f"schema_uat_judet={uat_schema.get('uat_county') or '-'} "
        f"schema_siruta={uat_schema.get('siruta') or '-'}"
    )
    print(
        "[geodata] "
        f"uat_crs_detected={uat_crs} "
        f"transformed_to={'EPSG:4326' if GEODATA_STATS.get('uat_transformed') else uat_crs}"
    )

def log_nowcasting_runtime_stats():
    print(
        "[nowcasting] "
        f"workflow_frequency=15min cron='*/15 * * * *' "
        f"live={NOWCASTING_RUNTIME_STATS['live_alerts']} "
        f"manual_imported={NOWCASTING_RUNTIME_STATS['manual_imported']} "
        f"archived_preserved={NOWCASTING_RUNTIME_STATS['archived_preserved']} "
        f"coordGis={NOWCASTING_RUNTIME_STATS['with_coord_gis']} "
        f"uat_fallback={NOWCASTING_RUNTIME_STATS['uat_fallback']} "
        f"county_fallback={NOWCASTING_RUNTIME_STATS['county_fallback']} "
        f"without_geometry={NOWCASTING_RUNTIME_STATS['without_geometry']}"
    )

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="cale catre un XML local (test)")
    ap.add_argument("--source", default="general", choices=["general", "nowcasting"])
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True); os.makedirs(ISTORIC, exist_ok=True)
    reset_nowcasting_runtime_stats()
    print("[workflow] frequency=15min cron='*/15 * * * *'")
    log_geodata_status()
    alerts = []
    if args.local:
        with open(args.local, "rb") as f:
            alerts += parse_avertizari(f.read(), args.source)
        if is_nowcasting_source(args.source):
            NOWCASTING_RUNTIME_STATS["live_alerts"] = len(alerts)
        print(f"[local:{args.source}] {args.local}: {len(alerts)} avertizari")
    else:
        for source, url in ENDPOINTS.items():
            try:
                xml_bytes, status = fetch_xml_with_status(url)
                diagnostics = xml_diagnostics(xml_bytes)
                got = parse_avertizari(xml_bytes, source)
                alerts += got
                if source == "nowcasting":
                    NOWCASTING_RUNTIME_STATS["live_alerts"] = len(got)
                    feature_count = sum(len(a.get("geom", {})) for a in got)
                    fallback_count = sum(a.get("fallback_geometry_count", 0) for a in got)
                    _register_debug_bytes("xml", xml_bytes, status)
                    print(
                        f"[nowcasting] {url}: status={status} bytes={len(xml_bytes)} "
                        f"raw_alerts={diagnostics['raw_alert_count']} coordGis={diagnostics['coord_gis_count']} "
                        f"avertizari={len(got)} feature-uri={feature_count} fallback={fallback_count}"
                    )
                else:
                    print(f"[{source}] {url}: {len(got)} avertizari")
            except Exception as ex:
                print(f"[{source}] EROARE: {ex}", file=sys.stderr)

        # Also fetch XML-GIS endpoint for better nowcasting geometry
        try:
            gis_bytes, gis_status = fetch_xml_with_status(NOWCASTING_GIS_ENDPOINT)
            _register_debug_bytes("xml_gis", gis_bytes, gis_status)
            gis_diagnostics = xml_diagnostics(gis_bytes)
            gis_alerts = parse_avertizari(gis_bytes, "nowcasting")
            # Merge GIS alerts: prefer GIS geometry over simple XML
            existing_keys = set()
            for al in alerts:
                if is_nowcasting_source(al.get("source")):
                    existing_keys.add((al["interval_start"], al["interval_end"]))
            gis_added = 0
            gis_upgraded = 0
            for gis_al in gis_alerts:
                key = (gis_al["interval_start"], gis_al["interval_end"])
                if key in existing_keys:
                    # Upgrade existing alert with GIS geometry if it has coordGis
                    if gis_al.get("coord_gis_count", 0) > 0:
                        for i, al in enumerate(alerts):
                            if is_nowcasting_source(al.get("source")) and (al["interval_start"], al["interval_end"]) == key:
                                # Merge geometry and metadata
                                for cod, g in gis_al["geom"].items():
                                    al["geom"][cod] = g
                                    if cod in gis_al.get("feature_meta", {}):
                                        al["feature_meta"][cod] = gis_al["feature_meta"][cod]
                                al["coord_gis_count"] = max(al.get("coord_gis_count", 0), gis_al.get("coord_gis_count", 0))
                                gis_upgraded += 1
                                break
                else:
                    alerts.append(gis_al)
                    existing_keys.add(key)
                    NOWCASTING_RUNTIME_STATS["live_alerts"] += 1
                    gis_added += 1
            print(
                f"[nowcasting_gis] {NOWCASTING_GIS_ENDPOINT}: status={gis_status} bytes={len(gis_bytes)} "
                f"raw_alerts={gis_diagnostics['raw_alert_count']} coordGis={gis_diagnostics['coord_gis_count']} "
                f"parsed={len(gis_alerts)} added={gis_added} upgraded={gis_upgraded}"
            )
        except Exception as ex:
            print(f"[nowcasting_gis] EROARE: {ex}", file=sys.stderr)

    manual_alerts = load_manual_nowcasting_alerts()
    NOWCASTING_RUNTIME_STATS["manual_imported"] = sum(
        1 for alert in manual_alerts if is_nowcasting_source(alert.get("source"))
    )
    alerts += manual_alerts
    update_nowcasting_geometry_stats(alerts)

    fetch_and_save_current_weather()

    if alerts:
        upsert_archive(alerts)
    index, latest = generate_all(alerts)
    log_nowcasting_runtime_stats()
    print(f"Zile generate: {list(index['dates'].keys())}")
    print(f"latest.geojson -> {latest}")

    # Write heartbeat status.json at every run (even with no data changes)
    write_status_json(alerts, index)

    # Save debug snapshot of nowcasting raw XMLs
    if not args.local:
        save_debug_snapshots()


def write_status_json(alerts, index):
    """Write public/data/status.json at every scraper run — heartbeat for frontend."""
    try:
        now = datetime.now(timezone.utc)
        now_ro = now.astimezone(timezone(timedelta(hours=3)))  # UTC+3 (Romania summer)
        nc_alerts = [a for a in alerts if is_nowcasting_source(a.get("source")) and a.get("source") != "nowcasting_manual"]
        manual_nc = [a for a in alerts if a.get("source") == "nowcasting_manual"]
        general_alerts = [a for a in alerts if not is_nowcasting_source(a.get("source"))]
        counties_nc = sorted({
            JUDETE.get(cod, cod)
            for al in nc_alerts
            for cod in al.get("jud", {})
        })
        codes_nc = sorted({
            COD_TO_NUME.get(max(al.get("jud", {}).values(), default=0), "")
            for al in nc_alerts
            if al.get("jud")
        })

        # Determine last data change from index
        latest_entry = index.get("dates", {}).get(index.get("latest_date", ""), {})
        last_data_change_utc = latest_entry.get("generated_at_utc") or now_utc()

        status = {
            "last_checked_at_utc": now.isoformat(timespec="seconds"),
            "last_checked_at_ro": now_ro.isoformat(timespec="seconds"),
            "workflow_frequency": "15min",
            "cron": "*/15 * * * *",
            "general": {
                "status": 200,
                "alert_count": len(general_alerts),
                "feature_count": sum(len(a.get("geom", {})) for a in general_alerts),
            },
            "nowcasting": {
                "xml_status": 200,
                "xml_alert_count": NOWCASTING_RUNTIME_STATS.get("live_alerts", 0),
                "xml_gis_alert_count": NOWCASTING_RUNTIME_STATS.get("with_coord_gis", 0),
                "parsed_count": len(nc_alerts),
                "manual_count": len(manual_nc),
                "coordGis": NOWCASTING_RUNTIME_STATS.get("with_coord_gis", 0),
                "uat_fallback": NOWCASTING_RUNTIME_STATS.get("uat_fallback", 0),
                "county_fallback": NOWCASTING_RUNTIME_STATS.get("county_fallback", 0),
                "without_geometry": NOWCASTING_RUNTIME_STATS.get("without_geometry", 0),
                "counties": counties_nc,
                "codes": [c for c in codes_nc if c],
            },
            "last_data_change_at_utc": last_data_change_utc,
            "index_generated_at_utc": index.get("generated_at_utc", ""),
        }
        write_json(os.path.join(DATA, "status.json"), status)
        print(f"[status] Scris status.json: verificat={now_ro.strftime('%H:%M')} nowcasting_live={len(nc_alerts)}")
    except Exception as ex:
        print(f"[status] EROARE scriere status.json: {ex}", file=sys.stderr)


# ------------------------------------------------------------------ debug snapshots
DEBUG_SNAPSHOTS_DIR = os.path.join(PUBLIC, "debug", "nowcasting")
DEBUG_SNAPSHOT_MAX = 96  # keep max 96 snapshots (~24h la 15min)

_debug_xml_bytes = {}   # filled by main() during fetch, keyed by "xml" / "xml_gis"
_debug_xml_status = {}

def _register_debug_bytes(key, data, status):
    """Called by main() after each fetch to register raw bytes for snapshot."""
    _debug_xml_bytes[key] = data
    _debug_xml_status[key] = status


def save_debug_snapshots():
    """Save raw XML snapshots + summary.json to public/debug/nowcasting/."""
    try:
        os.makedirs(DEBUG_SNAPSHOTS_DIR, exist_ok=True)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d_%H%M")

        # Save XMLs
        for key, suffix in [("xml", "nowcasting"), ("xml_gis", "nowcasting_gis")]:
            data = _debug_xml_bytes.get(key)
            if data:
                snap_path = os.path.join(DEBUG_SNAPSHOTS_DIR, f"{ts}_{suffix}.xml")
                with open(snap_path, "wb") as f:
                    f.write(data)

        # Save summary.json
        summary = {
            "checked_at_utc": now.isoformat(timespec="seconds"),
            "xml_status": _debug_xml_status.get("xml", 0),
            "xml_bytes": len(_debug_xml_bytes.get("xml", b"")),
            "xml_alert_count": NOWCASTING_RUNTIME_STATS.get("live_alerts", 0),
            "xml_gis_status": _debug_xml_status.get("xml_gis", 0),
            "xml_gis_bytes": len(_debug_xml_bytes.get("xml_gis", b"")),
            "xml_gis_alert_count": NOWCASTING_RUNTIME_STATS.get("with_coord_gis", 0),
            "parsed_nowcasting_count": NOWCASTING_RUNTIME_STATS.get("live_alerts", 0),
            "coordGis": NOWCASTING_RUNTIME_STATS.get("with_coord_gis", 0),
            "uat_fallback": NOWCASTING_RUNTIME_STATS.get("uat_fallback", 0),
            "county_fallback": NOWCASTING_RUNTIME_STATS.get("county_fallback", 0),
            "without_geometry": NOWCASTING_RUNTIME_STATS.get("without_geometry", 0),
        }
        write_json(os.path.join(DEBUG_SNAPSHOTS_DIR, f"{ts}_summary.json"), summary)

        # Cleanup: keep only last DEBUG_SNAPSHOT_MAX snapshots
        cleanup_old_snapshots()
        print(f"[debug] Snapshot salvat: {ts}")
    except Exception as ex:
        print(f"[debug] EROARE snapshot: {ex}", file=sys.stderr)


def cleanup_old_snapshots():
    """Keep only the most recent DEBUG_SNAPSHOT_MAX snapshots."""
    try:
        all_files = sorted([
            os.path.join(DEBUG_SNAPSHOTS_DIR, f)
            for f in os.listdir(DEBUG_SNAPSHOTS_DIR)
            if re.match(r"^\d{4}-\d{2}-\d{2}_\d{4}_", f)
        ])
        # Group by timestamp prefix (YYYY-MM-DD_HHMM)
        timestamps = sorted({
            re.match(r"^(\d{4}-\d{2}-\d{2}_\d{4})_", os.path.basename(f)).group(1)
            for f in all_files
            if re.match(r"^(\d{4}-\d{2}-\d{2}_\d{4})_", os.path.basename(f))
        })
        if len(timestamps) > DEBUG_SNAPSHOT_MAX:
            to_delete_ts = timestamps[: len(timestamps) - DEBUG_SNAPSHOT_MAX]
            for f in all_files:
                base = os.path.basename(f)
                m = re.match(r"^(\d{4}-\d{2}-\d{2}_\d{4})_", base)
                if m and m.group(1) in to_delete_ts:
                    os.remove(f)
            print(f"[debug] Cleanup: sterse {len(to_delete_ts)} seturi vechi de snapshot-uri")
    except Exception as ex:
        print(f"[debug] EROARE cleanup snapshot: {ex}", file=sys.stderr)


if __name__ == "__main__":
    main()
