"""Download ANM warning XML files and write MeteoAlertRO GeoJSON data."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ includes zoneinfo.
    ZoneInfo = None

try:
    from transformer import features_from_xml, xml_diagnostics
except ImportError:  # pragma: no cover - useful when imported as a package.
    from .transformer import features_from_xml, xml_diagnostics


ENDPOINTS = [
    ("General", "https://www.meteoromania.ro/avertizari-xml.php"),
    ("Nowcasting", "https://www.meteoromania.ro/avertizari-nowcasting-xml.php"),
]

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "public" / "data"


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    scraped_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_date = current_bucharest_date()

    features: list[dict] = []
    raw_alert_count = 0
    coord_gis_count = 0
    source_diagnostics: dict[str, dict] = {}

    for source, url in ENDPOINTS:
        try:
            xml_bytes = download_xml(url)
        except requests.RequestException as exc:
            warn(f"{source}: download failed: {exc}")
            continue

        if not xml_bytes.strip():
            warn(f"{source}: empty XML response")
            continue

        try:
            diagnostics = xml_diagnostics(xml_bytes)
            source_diagnostics[source] = {
                "bytes": len(xml_bytes),
                **diagnostics,
            }
            raw_alert_count += diagnostics["raw_alert_count"]
            coord_gis_count += diagnostics["coord_gis_count"]
            source_features, source_warnings = features_from_xml(xml_bytes, source, scraped_at_utc)
        except Exception as exc:
            warn(f"{source}: XML parsing failed: {exc}")
            continue

        for warning in source_warnings:
            warn(warning)

        features.extend(source_features)
        print(f"{source} XML bytes: {len(xml_bytes)}")
        print(f"{source} avertizare elements: {diagnostics['raw_alert_count']}")
        print(f"{source} geometry elements with coordGis: {diagnostics['coord_gis_count']}")
        if source == "Nowcasting" and diagnostics["raw_alert_count"] == 0 and diagnostics["coord_gis_count"] == 0:
            print("Nowcasting: 0 avertizări, 0 geometrii.")

    metadata = build_metadata(
        generated_at_utc=scraped_at_utc,
        features=features,
        raw_alert_count=raw_alert_count,
        coord_gis_count=coord_gis_count,
        source_diagnostics=source_diagnostics,
    )

    bbox_is_valid = True
    print(f"GeoJSON feature count before bbox validation: {len(features)}")
    if len(features) > 0:
        bbox_is_valid = validate_feature_bbox(features)
    if not bbox_is_valid:
        return 1

    write_outputs(features, run_date, scraped_at_utc, metadata)
    print(f"Generated GeoJSON features: {len(features)}")
    return 0


def download_xml(url: str) -> bytes:
    headers = {
        "Accept": "application/xml,text/xml,*/*;q=0.8",
        "User-Agent": "MeteoAlertRO/1.0 (+https://github.com/) requests",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content


def build_metadata(
    generated_at_utc: str,
    features: list[dict],
    raw_alert_count: int,
    coord_gis_count: int,
    source_diagnostics: dict[str, dict],
) -> dict:
    alerts_found_raw = raw_alert_count > 0
    reason = None

    if alerts_found_raw and coord_gis_count == 0:
        reason = "XML contains alerts but no coordGis geometry was found"
    elif alerts_found_raw and not features:
        reason = "XML contains alerts and coordGis geometry, but no valid GeoJSON features could be generated"

    return {
        "generated_at_utc": generated_at_utc,
        "alerts_found_raw": alerts_found_raw,
        "raw_alert_count": raw_alert_count,
        "coord_gis_count": coord_gis_count,
        "features_with_geometry": len(features),
        "bbox": calculate_feature_bbox(features),
        "reason": reason,
        "sources": source_diagnostics,
    }


def validate_feature_bbox(features: list[dict]) -> bool:
    bbox = calculate_feature_bbox(features)
    if bbox is None:
        return True

    min_lon, min_lat, max_lon, max_lat = bbox
    print(f"GeoJSON bbox min_lon: {min_lon}")
    print(f"GeoJSON bbox max_lon: {max_lon}")
    print(f"GeoJSON bbox min_lat: {min_lat}")
    print(f"GeoJSON bbox max_lat: {max_lat}")

    is_valid = (
        18 <= min_lon <= 31
        and 18 <= max_lon <= 31
        and 42 <= min_lat <= 50
        and 42 <= max_lat <= 50
    )
    if not is_valid:
        print(
            "ERROR: GeoJSON bbox is outside Romania. CRS transform or coordinate order is wrong.",
            file=sys.stderr,
        )
    return is_valid


def calculate_feature_bbox(features: list[dict]) -> list[float] | None:
    longitudes: list[float] = []
    latitudes: list[float] = []

    def collect_coordinates(value: object) -> None:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            longitudes.append(float(value[0]))
            latitudes.append(float(value[1]))
            return

        if isinstance(value, (list, tuple)):
            for item in value:
                collect_coordinates(item)

    for feature in features:
        collect_coordinates(feature.get("geometry", {}).get("coordinates", []))

    if not longitudes or not latitudes:
        return None

    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def write_outputs(features: list[dict], run_date: str, generated_at_utc: str, metadata: dict) -> None:
    latest_geojson = {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }

    write_json(DATA_DIR / "latest.geojson", latest_geojson)
    print("Saved: public/data/latest.geojson")

    index = load_index()
    dates = list(dict.fromkeys(index.get("dates", [])))
    files = list(dict.fromkeys(index.get("files", [])))

    if features:
        dated_name = f"{run_date}.geojson"
        write_json(DATA_DIR / dated_name, latest_geojson)
        print(f"Saved: public/data/{dated_name}")

        if run_date not in dates:
            dates.append(run_date)
        if dated_name not in files:
            files.append(dated_name)
    else:
        print("No valid alerts; dated GeoJSON was not added to index.json")

    dates.sort()
    files.sort()

    write_json(
        DATA_DIR / "index.json",
        {
            "generated_at_utc": generated_at_utc,
            "latest_file": "latest.geojson",
            **metadata,
            "dates": dates,
            "files": files,
        },
    )
    print("Updated: public/data/index.json")


def load_index() -> dict:
    index_path = DATA_DIR / "index.json"
    if not index_path.exists():
        return {}

    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        warn("Existing index.json is invalid; rebuilding it")
        return {}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_bucharest_date() -> str:
    if ZoneInfo is None:
        return datetime.now().date().isoformat()

    try:
        return datetime.now(ZoneInfo("Europe/Bucharest")).date().isoformat()
    except Exception:
        warn("Europe/Bucharest timezone data is unavailable; using the local system date")
        return datetime.now().date().isoformat()


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
