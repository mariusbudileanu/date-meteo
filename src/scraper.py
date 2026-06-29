"""Download ANM warning XML files and write MeteoAlertRO data artifacts."""

from __future__ import annotations

import copy
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ includes zoneinfo.
    ZoneInfo = None

try:
    from transformer import COLOR_NAMES, features_from_xml, xml_diagnostics
except ImportError:  # pragma: no cover - useful when imported as a package.
    from .transformer import COLOR_NAMES, features_from_xml, xml_diagnostics


ENDPOINTS = [
    ("General", "https://www.meteoromania.ro/avertizari-xml.php"),
    ("Nowcasting", "https://www.meteoromania.ro/avertizari-nowcasting-xml.php"),
]

ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT_DIR / "public"
DATA_DIR = PUBLIC_DIR / "data"
HISTORY_DIR = PUBLIC_DIR / "istoric"

CSV_COLUMNS = [
    "alert_id",
    "prima_aparitie_utc",
    "ultima_actualizare_utc",
    "revizuit",
    "content_hash",
    "source",
    "data_emitere",
    "interval_text",
    "interval_start",
    "interval_end",
    "durata_ore",
    "cod_culoare_max",
    "fenomene_pe_cod_json",
    "zona_afectata_text",
    "judete_afectate",
    "judete_count",
    "judete_culori_json",
    "text_alerta_plain",
    "text_alerta_html",
]


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    scraped_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_date = current_bucharest_date()

    features: list[dict[str, Any]] = []
    raw_alert_count = 0
    coord_gis_count = 0
    source_diagnostics: dict[str, dict[str, Any]] = {}

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

    print(f"Raw GeoJSON feature count before bbox validation: {len(features)}")
    if features and not validate_feature_bbox(features):
        return 1

    summary = write_outputs(features, run_date, scraped_at_utc, metadata)
    print(f"Generated raw GeoJSON features: {len(features)}")
    print(f"Generated latest GeoJSON features: {summary['latest_feature_count']}")
    print(f"Updated public/data files: {', '.join(summary['data_files']) or '-'}")
    print(f"Updated public/istoric files: {', '.join(summary['history_files']) or '-'}")
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
    features: list[dict[str, Any]],
    raw_alert_count: int,
    coord_gis_count: int,
    source_diagnostics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
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
        "raw_feature_count": len(features),
        "alert_count": distinct_alert_count(features),
        "features_with_geometry": len(features),
        "feature_count": len(features),
        "bbox": calculate_feature_bbox(features),
        "reason": reason,
        "sources": source_diagnostics,
    }


def validate_feature_bbox(features: list[dict[str, Any]]) -> bool:
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


def write_outputs(
    features: list[dict[str, Any]],
    run_date: str,
    generated_at_utc: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    alert_records = build_alert_records(features)
    history_files = upsert_archive(alert_records, generated_at_utc)
    all_archive_rows = load_all_archive_rows()
    history_files.extend(write_history_artifacts(all_archive_rows, generated_at_utc))

    data_files: list[str] = []
    data_files.extend(write_base_counties(features, generated_at_utc))
    data_files.extend(write_history_stats(all_archive_rows, generated_at_utc))

    daily_collections = build_daily_collections(features, alert_records, run_date, generated_at_utc, metadata)
    data_files.extend(remove_stale_daily_files(set(daily_collections)))

    for day, collection in sorted(daily_collections.items()):
        path = DATA_DIR / f"{day}.geojson"
        if write_json_if_changed(path, collection):
            data_files.append(f"data/{path.name}")
            print(f"Saved: public/data/{path.name}")

    latest_collection, latest_date = choose_latest_collection(daily_collections, run_date, generated_at_utc, metadata)
    if write_json_if_changed(DATA_DIR / "latest.geojson", latest_collection):
        data_files.append("data/latest.geojson")
        print("Saved: public/data/latest.geojson")

    if write_json_if_changed(DATA_DIR / "index.json", build_data_index(daily_collections, run_date, latest_date, generated_at_utc)):
        data_files.append("data/index.json")
        print("Updated: public/data/index.json")

    return {
        "latest_feature_count": len(latest_collection.get("features", [])),
        "data_files": data_files,
        "history_files": history_files,
    }


def build_daily_collections(
    features: list[dict[str, Any]],
    alert_records: list[dict[str, Any]],
    run_date: str,
    generated_at_utc: str,
    global_metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    all_days = sorted({day for record in alert_records for day in record["active_days"]})
    collections: dict[str, dict[str, Any]] = {}

    for day in all_days:
        active_records = [record for record in alert_records if day in record["active_days"]]
        daily_features = build_daily_features(features, day, len(active_records))
        max_color = max((int(feature["properties"].get("cod_culoare", 0)) for feature in daily_features), default=0)
        color_counts = Counter(str(feature["properties"].get("cod_culoare", 0)) for feature in daily_features)
        metadata = {
            **global_metadata,
            "generated_at_utc": generated_at_utc,
            "today": run_date,
            "date": day,
            "alert_count": len(active_records),
            "features_with_geometry": len(daily_features),
            "feature_count": len(daily_features),
            "max_color": max_color,
            "color_counts": dict(sorted(color_counts.items())),
            "bbox": calculate_feature_bbox(daily_features),
            "active_alerts": [summarize_alert_record(record) for record in active_records],
        }
        collections[day] = {
            "type": "FeatureCollection",
            "metadata": metadata,
            "features": daily_features,
        }

    return collections


def build_daily_features(features: list[dict[str, Any]], day: str, active_alert_count: int) -> list[dict[str, Any]]:
    winners: dict[str, dict[str, Any]] = {}

    for feature in features:
        props = feature.get("properties", {})
        active_days = props.get("active_days") or []
        if day not in active_days:
            continue

        color = int(props.get("cod_culoare") or props.get("culoare") or 0)
        if color <= 0:
            continue

        zone_code = str(props.get("judet_cod") or props.get("cod_judet") or "")
        if not zone_code:
            continue

        current = winners.get(zone_code)
        current_color = int(current.get("properties", {}).get("cod_culoare", 0)) if current else -1
        current_start = str(current.get("properties", {}).get("interval_start", "")) if current else ""
        next_start = str(props.get("interval_start", ""))
        if current is None or color > current_color or (color == current_color and next_start > current_start):
            winners[zone_code] = feature

    daily_features: list[dict[str, Any]] = []
    for zone_code, feature in sorted(winners.items()):
        selected = copy.deepcopy(feature)
        props = selected.setdefault("properties", {})
        props["zi"] = day
        props["calendar_date"] = day
        props["selected_from_alert_id"] = props.get("alert_id")
        props["active_alert_count_for_day"] = active_alert_count
        selected["id"] = f"{day}-{slugify_identifier(zone_code)}"
        props["feature_id"] = selected["id"]
        daily_features.append(selected)

    return daily_features


def choose_latest_collection(
    daily_collections: dict[str, dict[str, Any]],
    run_date: str,
    generated_at_utc: str,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if not daily_collections:
        empty_metadata = {
            **metadata,
            "generated_at_utc": generated_at_utc,
            "today": run_date,
            "date": run_date,
            "alert_count": 0,
            "features_with_geometry": 0,
            "feature_count": 0,
            "max_color": 0,
            "color_counts": {},
            "bbox": None,
            "active_alerts": [],
        }
        return {"type": "FeatureCollection", "metadata": empty_metadata, "features": []}, None

    if run_date in daily_collections:
        latest_date = run_date
    else:
        latest_date = nearest_date(sorted(daily_collections), run_date)

    collection = copy.deepcopy(daily_collections[latest_date])
    collection.setdefault("metadata", {})["latest_for_date"] = latest_date
    return collection, latest_date


def nearest_date(dates: list[str], target: str) -> str:
    target_date = date.fromisoformat(target)
    parsed = [(day, date.fromisoformat(day)) for day in dates]
    future_or_today = [item for item in parsed if item[1] >= target_date]
    if future_or_today:
        return min(future_or_today, key=lambda item: item[1])[0]
    return max(parsed, key=lambda item: item[1])[0]


def build_data_index(
    daily_collections: dict[str, dict[str, Any]],
    run_date: str,
    latest_date: str | None,
    generated_at_utc: str,
) -> dict[str, Any]:
    dates: dict[str, dict[str, Any]] = {}
    files: list[dict[str, Any]] = []

    for day, collection in sorted(daily_collections.items()):
        metadata = collection.get("metadata", {})
        entry = {
            "file": f"{day}.geojson",
            "alert_count": int(metadata.get("alert_count", 0)),
            "feature_count": int(metadata.get("feature_count", 0)),
            "max_color": int(metadata.get("max_color", 0)),
            "color_counts": metadata.get("color_counts", {}),
        }
        dates[day] = entry
        files.append({"date": day, **entry})

    return {
        "generated_at_utc": generated_at_utc,
        "today": run_date,
        "latest_file": "latest.geojson",
        "latest_date": latest_date,
        "dates": dates,
        "files": files,
    }


def build_alert_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        alert_id = feature.get("properties", {}).get("alert_id")
        if alert_id:
            grouped[str(alert_id)].append(feature)

    records: list[dict[str, Any]] = []
    for alert_id, group in sorted(grouped.items()):
        props_list = [feature.get("properties", {}) for feature in group]
        first = props_list[0]
        zone_colors: dict[str, int] = {}
        for props in props_list:
            zone_code = str(props.get("judet_cod") or props.get("cod_judet") or "")
            if not zone_code:
                continue
            color = int(props.get("cod_culoare") or props.get("culoare") or 0)
            zone_colors[zone_code] = max(zone_colors.get(zone_code, 0), color)

        affected = {code: color for code, color in zone_colors.items() if color > 0}
        color_counts = Counter(str(color) for color in affected.values())
        active_days = sorted(set(first.get("active_days") or []))
        max_color = max(zone_colors.values(), default=0)

        records.append(
            {
                "alert_id": alert_id,
                "source": first.get("source") or first.get("tip") or "ANM",
                "data_emitere": first.get("data_emitere") or first.get("data_aparitiei") or "",
                "interval_text": first.get("interval_text") or first.get("intervalul") or "",
                "interval_start": first.get("interval_start") or "",
                "interval_end": first.get("interval_end") or first.get("data_expirarii") or "",
                "active_days": active_days,
                "durata_ore": first.get("durata_ore"),
                "cod_culoare_max": max_color,
                "fenomene_pe_cod": first.get("fenomene_pe_cod") or {},
                "zona_afectata_text": first.get("zona_afectata_text") or first.get("zona_afectata") or "",
                "judete_afectate": sorted(affected),
                "judete_count": len(affected),
                "judete_culori": dict(sorted(zone_colors.items())),
                "text_alerta_plain": first.get("text_alerta_plain") or "",
                "text_alerta_html": first.get("mesaj_html") or first.get("mesaj") or "",
                "content_hash": first.get("content_hash") or "",
                "feature_count": len(group),
                "affected_feature_count": len(affected),
                "color_counts": dict(sorted(color_counts.items())),
            }
        )

    return records


def summarize_alert_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": record["alert_id"],
        "source": record["source"],
        "data_emitere": record["data_emitere"],
        "interval_text": record["interval_text"],
        "interval_start": record["interval_start"],
        "interval_end": record["interval_end"],
        "durata_ore": record["durata_ore"],
        "cod_culoare_max": record["cod_culoare_max"],
        "cod_culoare_max_nume": COLOR_NAMES.get(int(record["cod_culoare_max"]), "Verde"),
        "fenomene_pe_cod": record["fenomene_pe_cod"],
        "zona_afectata_text": record["zona_afectata_text"],
        "judete_afectate": record["judete_afectate"],
        "judete_count": record["judete_count"],
        "judete_culori": record["judete_culori"],
        "text_alerta_plain": record["text_alerta_plain"],
        "text_alerta_html": record["text_alerta_html"],
        "content_hash": record["content_hash"],
        "color_counts": record["color_counts"],
    }


def upsert_archive(records: list[dict[str, Any]], generated_at_utc: str) -> list[str]:
    changed_files: list[str] = []
    records_by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        month = month_key(record.get("interval_start") or generated_at_utc)
        records_by_month[month].append(record)

    for month, month_records in sorted(records_by_month.items()):
        year = month[:4]
        target_dir = HISTORY_DIR / year
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{month}.csv"
        existing_rows = load_csv_rows(path)
        rows_by_id = {row["alert_id"]: row for row in existing_rows if row.get("alert_id")}

        for record in month_records:
            previous = rows_by_id.get(record["alert_id"])
            row = archive_row(record, generated_at_utc, previous)
            rows_by_id[record["alert_id"]] = row

        rows = sorted(rows_by_id.values(), key=lambda row: (row.get("interval_start", ""), row.get("alert_id", "")))
        if write_csv_if_changed(path, rows):
            changed_files.append(public_relative(path))
            print(f"Updated: public/{public_relative(path)}")

    return changed_files


def archive_row(record: dict[str, Any], generated_at_utc: str, previous: dict[str, str] | None) -> dict[str, str]:
    previous_hash = previous.get("content_hash") if previous else None
    changed = previous is not None and previous_hash != record["content_hash"]

    if previous:
        prima_aparitie = previous.get("prima_aparitie_utc") or generated_at_utc
        ultima_actualizare = generated_at_utc if changed else previous.get("ultima_actualizare_utc", generated_at_utc)
        revizuit = "true" if changed or previous.get("revizuit") == "true" else "false"
    else:
        prima_aparitie = generated_at_utc
        ultima_actualizare = generated_at_utc
        revizuit = "false"

    return {
        "alert_id": str(record["alert_id"]),
        "prima_aparitie_utc": prima_aparitie,
        "ultima_actualizare_utc": ultima_actualizare,
        "revizuit": revizuit,
        "content_hash": str(record["content_hash"]),
        "source": str(record["source"]),
        "data_emitere": str(record["data_emitere"]),
        "interval_text": str(record["interval_text"]),
        "interval_start": str(record["interval_start"]),
        "interval_end": str(record["interval_end"]),
        "durata_ore": "" if record["durata_ore"] is None else str(record["durata_ore"]),
        "cod_culoare_max": str(record["cod_culoare_max"]),
        "fenomene_pe_cod_json": compact_json(record["fenomene_pe_cod"]),
        "zona_afectata_text": str(record["zona_afectata_text"]),
        "judete_afectate": ",".join(record["judete_afectate"]),
        "judete_count": str(record["judete_count"]),
        "judete_culori_json": compact_json(record["judete_culori"]),
        "text_alerta_plain": str(record["text_alerta_plain"]),
        "text_alerta_html": str(record["text_alerta_html"]),
    }


def write_history_artifacts(rows: list[dict[str, str]], generated_at_utc: str) -> list[str]:
    changed_files: list[str] = []
    if write_all_alerts_csv(rows):
        changed_files.append("istoric/toate-alertele.csv")

    manifest = build_history_manifest(rows, generated_at_utc)
    if write_json_if_changed(HISTORY_DIR / "index.json", manifest):
        changed_files.append("istoric/index.json")
        print("Updated: public/istoric/index.json")

    readme = build_history_readme(manifest)
    readme_path = HISTORY_DIR / "README.md"
    if not readme_path.exists() or readme_path.read_text(encoding="utf-8") != readme:
        readme_path.write_text(readme, encoding="utf-8")
        changed_files.append("istoric/README.md")
        print("Updated: public/istoric/README.md")

    return changed_files


def build_history_manifest(rows: list[dict[str, str]], generated_at_utc: str) -> dict[str, Any]:
    months: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        months[month_key(row.get("interval_start") or generated_at_utc)].append(row)

    month_entries = []
    for month, month_rows in sorted(months.items()):
        interval_starts = [row.get("interval_start", "") for row in month_rows if row.get("interval_start")]
        interval_ends = [row.get("interval_end", "") for row in month_rows if row.get("interval_end")]
        max_color = max((safe_int(row.get("cod_culoare_max")) for row in month_rows), default=0)
        year = month[:4]
        path = f"istoric/{year}/{month}.csv"
        month_entries.append(
            {
                "month": month,
                "path": path,
                "alert_count": len(month_rows),
                "first_alert": min(interval_starts)[:10] if interval_starts else "",
                "last_alert": max(interval_ends)[:10] if interval_ends else "",
                "max_color": max_color,
                "max_color_name": COLOR_NAMES.get(max_color, "Verde"),
            }
        )

    return {
        "generated_at_utc": generated_at_utc,
        "schema": "meteoalertro-history-v1",
        "total_alert_count": len(rows),
        "rollup_csv": "istoric/toate-alertele.csv",
        "months": month_entries,
    }


def build_history_readme(manifest: dict[str, Any]) -> str:
    lines = [
        "# MeteoAlertRO - Arhiva avertizarilor",
        "",
        "CSV-urile lunare sunt generate automat din fluxurile ANM si sunt servite prin GitHub Pages.",
        "",
        "## Fisiere",
        "",
        "| Luna | Avertizari | Interval | Cod maxim | CSV |",
        "|---|---:|---|---|---|",
    ]
    for month in manifest.get("months", []):
        lines.append(
            f"| {month['month']} | {month['alert_count']} | {month['first_alert']} - {month['last_alert']} | "
            f"{month['max_color_name']} | `{month['path']}` |"
        )
    lines.extend(["", "Encoding CSV: UTF-8-SIG, compatibil cu Excel."])
    return "\n".join(lines) + "\n"


def write_history_stats(rows: list[dict[str, str]], generated_at_utc: str) -> list[str]:
    county_stats: dict[str, dict[str, Any]] = {}

    for row in rows:
        colors = parse_json_object(row.get("judete_culori_json"))
        interval_end = row.get("interval_end", "")
        alert_id = row.get("alert_id", "")
        for county_code, raw_color in colors.items():
            color = safe_int(raw_color)
            if color <= 0:
                continue
            stats = county_stats.setdefault(
                county_code,
                {
                    "judet_cod": county_code,
                    "alert_count": 0,
                    "max_color": 0,
                    "max_color_name": "Verde",
                    "last_alert_end": "",
                    "last_alert_id": "",
                    "color_counts": {},
                },
            )
            stats["alert_count"] += 1
            stats["max_color"] = max(stats["max_color"], color)
            stats["max_color_name"] = COLOR_NAMES.get(stats["max_color"], "Verde")
            stats["color_counts"][str(color)] = stats["color_counts"].get(str(color), 0) + 1
            if interval_end > stats["last_alert_end"]:
                stats["last_alert_end"] = interval_end
                stats["last_alert_id"] = alert_id

    data = {
        "generated_at_utc": generated_at_utc,
        "county_count": len(county_stats),
        "counties": sorted(county_stats.values(), key=lambda item: item["judet_cod"]),
    }
    path = DATA_DIR / "history_stats.json"
    if write_json_if_changed(path, data):
        print("Updated: public/data/history_stats.json")
        return ["data/history_stats.json"]
    return []


def write_base_counties(features: list[dict[str, Any]], generated_at_utc: str) -> list[str]:
    by_code: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = feature.get("properties", {})
        code = str(props.get("judet_cod") or props.get("cod_judet") or "")
        geometry = feature.get("geometry")
        if not code or not geometry:
            continue
        if code in by_code and props.get("element_type") != "judet":
            continue

        by_code[code] = {
            "type": "Feature",
            "id": f"base-{slugify_identifier(code)}",
            "geometry": geometry,
            "properties": {
                "judet_cod": code,
                "judet_nume": props.get("judet_nume") or code,
                "cod_culoare": 0,
                "cod_culoare_nume": "Verde",
            },
        }

    data = {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at_utc": generated_at_utc,
            "feature_count": len(by_code),
            "source": "derived_from_current_anm_geometry",
        },
        "features": [by_code[code] for code in sorted(by_code)],
    }
    path = DATA_DIR / "judete.geojson"
    if write_json_if_changed(path, data):
        print("Updated: public/data/judete.geojson")
        return ["data/judete.geojson"]
    return []


def remove_stale_daily_files(active_days: set[str]) -> list[str]:
    changed: list[str] = []
    for path in sorted(DATA_DIR.glob("????-??-??.geojson")):
        if path.stem in active_days:
            continue
        path.unlink()
        changed.append(f"data/{path.name} (removed)")
        print(f"Removed stale: public/data/{path.name}")
    return changed


def calculate_feature_bbox(features: list[dict[str, Any]]) -> list[float] | None:
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


def distinct_alert_count(features: list[dict[str, Any]]) -> int:
    alert_ids = {
        str(feature.get("properties", {}).get("alert_id"))
        for feature in features
        if feature.get("properties", {}).get("alert_id")
    }
    if alert_ids:
        return len(alert_ids)
    return 1 if features else 0


def load_all_archive_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(HISTORY_DIR.glob("????/????-??.csv")):
        rows.extend(load_csv_rows(path))
    return sorted(rows, key=lambda row: (row.get("interval_start", ""), row.get("alert_id", "")))


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{column: row.get(column, "") for column in CSV_COLUMNS} for row in reader]


def write_csv_if_changed(path: Path, rows: list[dict[str, str]]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
    text = "\ufeff" + buffer.getvalue()
    data = text.encode("utf-8")

    if path.exists() and path.read_bytes() == data:
        return False

    path.write_bytes(data)
    return True


def write_all_alerts_csv(rows: list[dict[str, str]]) -> bool:
    path = HISTORY_DIR / "toate-alertele.csv"
    return write_csv_if_changed(path, rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        current_text = path.read_text(encoding="utf-8")
        if current_text == text:
            return False
        try:
            current_data = json.loads(current_text)
        except json.JSONDecodeError:
            current_data = None
        if current_data is not None and normalize_for_compare(current_data) == normalize_for_compare(data):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def normalize_for_compare(value: Any) -> Any:
    volatile_keys = {"generated_at_utc", "scraped_at_utc"}
    if isinstance(value, dict):
        return {
            key: normalize_for_compare(item)
            for key, item in value.items()
            if key not in volatile_keys
        }
    if isinstance(value, (list, tuple)):
        return [normalize_for_compare(item) for item in value]
    return value


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def month_key(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2})", str(value))
    if match:
        return match.group(1)
    return current_bucharest_date()[:7]


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def public_relative(path: Path) -> str:
    return path.relative_to(PUBLIC_DIR).as_posix()


def slugify_identifier(value: str) -> str:
    folded = str(value).lower()
    folded = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return folded or "zona"


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
