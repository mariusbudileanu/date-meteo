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
    from transformer import features_from_xml
except ImportError:  # pragma: no cover - useful when imported as a package.
    from .transformer import features_from_xml


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
            source_features, source_warnings = features_from_xml(xml_bytes, source, scraped_at_utc)
        except Exception as exc:
            warn(f"{source}: XML parsing failed: {exc}")
            continue

        for warning in source_warnings:
            warn(warning)

        features.extend(source_features)
        print(f"{source}: {len(source_features)} valid feature(s)")

    write_outputs(features, run_date, scraped_at_utc)
    print(f"Total valid features: {len(features)}")
    return 0


def download_xml(url: str) -> bytes:
    headers = {
        "Accept": "application/xml,text/xml,*/*;q=0.8",
        "User-Agent": "MeteoAlertRO/1.0 (+https://github.com/) requests",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content


def write_outputs(features: list[dict], run_date: str, generated_at_utc: str) -> None:
    latest_geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    write_json(DATA_DIR / "latest.geojson", latest_geojson)
    print(f"Wrote public/data/latest.geojson")

    index = load_index()
    dates = list(dict.fromkeys(index.get("dates", [])))
    files = list(dict.fromkeys(index.get("files", [])))

    if features:
        dated_name = f"{run_date}.geojson"
        write_json(DATA_DIR / dated_name, latest_geojson)
        print(f"Wrote public/data/{dated_name}")

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
            "dates": dates,
            "files": files,
        },
    )
    print("Wrote public/data/index.json")


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
