#!/usr/bin/env python3
"""
MeteoAlertRO — scraper ANM (fără dependențe externe, doar stdlib).

Flux: fetch XML (general + nowcasting) -> parse avertizari -> upsert in arhiva CSV lunara
      -> regenereaza: data/<zi>.geojson, data/index.json, data/history_stats.json,
         data/latest.geojson, istoric/index.json, istoric/README.md

Reguli importante:
  * O <avertizare> = o fereastra de valabilitate (intervalul) cu culori fixe pe judet.
  * Evolutia zi-cu-zi = mai multe <avertizare> consecutive -> rezolvare "max culoare/judet" pe zi.
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
PUBLIC = os.environ.get("METEO_OUT", "public")  # seteaza "." daca Pages serveste din radacina
DATA    = os.path.join(PUBLIC, "data")
ISTORIC = os.path.join(PUBLIC, "istoric")

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

def _norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()

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

# ------------------------------------------------------------------ parsing ANM
def parse_interval(intervalul, data_aparitiei, data_expirarii):
    """(start_dt, end_dt). end = dataExpirarii; start din 'intervalul' sau, fallback, dataAparitiei."""
    end_dt = datetime.strptime(data_expirarii, "%Y-%m-%dT%H:%M")
    if intervalul:
        left = re.split(r"[–—-]", intervalul)[0]
        m = re.search(r"(\d{1,2})\s+([a-zăâîșțA-ZĂÂÎȘȚ]+).*?ora\s+(\d{1,2})", left)
        if m and m.group(2).lower() in LUNI:
            day, mon, hour = int(m.group(1)), LUNI[m.group(2).lower()], int(m.group(3))
            year = end_dt.year - (1 if mon > end_dt.month else 0)
            return datetime(year, mon, day, hour), end_dt
    if data_aparitiei:
        try:
            return datetime.strptime(data_aparitiei, "%Y-%m-%dT%H:%M"), end_dt
        except ValueError:
            pass
    return end_dt - timedelta(hours=3), end_dt

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

def make_alert_id(source, s_iso, e_iso, judete_codes):
    base = "|".join([source, s_iso, e_iso, ",".join(sorted(judete_codes))])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

def make_content_hash(mesaj_plain, judete_culori):
    base = (mesaj_plain or "") + "|" + ",".join(f"{c}:{col}" for c, col in sorted(judete_culori.items()))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

def parse_avertizari(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    alerts = []
    for av in root.findall("avertizare"):
        a = av.attrib
        if not a.get("dataExpirarii"):
            continue
        s, e = parse_interval(a.get("intervalul", ""), a.get("dataAparitiei", ""), a["dataExpirarii"])
        judete = av.findall("judet")
        jud_cul, geom = {}, {}
        for j in judete:
            cod = j.attrib["cod"]
            jud_cul[cod] = int(j.attrib.get("culoare", "0"))
            if j.attrib.get("coordGis"):
                try:
                    geom[cod] = wkt_to_geojson_geometry(j.attrib["coordGis"])
                except Exception as ex:
                    print(f"  ! coordGis parse fail {cod}: {ex}", file=sys.stderr)
        if not jud_cul:
            continue
        mesaj_plain = html_to_plain(a.get("mesaj", ""))
        alerts.append({
            "source": source,
            "alert_id": make_alert_id(source, s.isoformat(), e.isoformat(), list(jud_cul)),
            "content_hash": make_content_hash(mesaj_plain, jud_cul),
            "data_emitere": a.get("dataAparitiei", ""),
            "interval_text": a.get("intervalul", ""),
            "interval_start": s.isoformat(),
            "interval_end": e.isoformat(),
            "durata_ore": round((e - s).total_seconds() / 3600, 1),
            "cod_culoare_max": max(jud_cul.values()),
            "zona_afectata_text": a.get("zonaAfectata", ""),
            "zile": zile_acoperite(s, e),
            "jud": jud_cul,
            "geom": geom,
            "fen": extract_phenomena_by_code(a.get("mesaj", "")),
            "mesaj_html": a.get("mesaj", ""),
            "mesaj_plain": mesaj_plain,
        })
    return alerts

def fetch_xml(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MeteoAlertRO/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

# ------------------------------------------------------------------ arhiva CSV
CSV_FIELDS = ["alert_id","prima_aparitie_utc","ultima_actualizare_utc","revizuit","content_hash",
              "source","data_emitere","interval_text","interval_start","interval_end","durata_ore",
              "cod_culoare_max","fenomene_pe_cod_json","zona_afectata_text",
              "judete_afectate","judete_count","judete_culori_json","text_alerta_plain","text_alerta_html"]

def csv_path_for(alert):
    ym = alert["interval_start"][:7]
    d = os.path.join(ISTORIC, ym[:4]); os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{ym}.csv")

def alert_to_row(alert, prima, ultima, revizuit):
    return {
        "alert_id": alert["alert_id"], "prima_aparitie_utc": prima,
        "ultima_actualizare_utc": ultima, "revizuit": str(revizuit).lower(),
        "content_hash": alert["content_hash"], "source": alert["source"],
        "data_emitere": alert["data_emitere"], "interval_text": alert["interval_text"],
        "interval_start": alert["interval_start"], "interval_end": alert["interval_end"],
        "durata_ore": alert["durata_ore"], "cod_culoare_max": alert["cod_culoare_max"],
        "fenomene_pe_cod_json": json.dumps(alert["fen"], ensure_ascii=False),
        "zona_afectata_text": alert["zona_afectata_text"],
        "judete_afectate": ";".join(sorted(alert["jud"].keys())),
        "judete_count": len(alert["jud"]),
        "judete_culori_json": json.dumps(alert["jud"], ensure_ascii=False),
        "text_alerta_plain": alert["mesaj_plain"], "text_alerta_html": alert["mesaj_html"],
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
            cur = rows.get(al["alert_id"])
            if cur is None:
                rows[al["alert_id"]] = alert_to_row(al, now_utc(), now_utc(), False)
            elif cur.get("content_hash") != al["content_hash"]:
                rows[al["alert_id"]] = alert_to_row(al, cur["prima_aparitie_utc"], now_utc(), True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS); w.writeheader()
            for r in sorted(rows.values(), key=lambda x: x["interval_start"]):
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})

# ------------------------------------------------------------------ generare derivate
def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

def _winner_features(alerts_subset, day):
    """Un feature per judet = max culoare intre avertizarile (din subset) active in ziua data."""
    winner = {}
    for al in alerts_subset:
        if day in al["zile"]:
            for jcod, cul in al["jud"].items():
                if jcod not in winner or cul > winner[jcod][0]:
                    winner[jcod] = (cul, al)
    feats = []
    for jcod, (cul, al) in sorted(winner.items()):
        if jcod not in al["geom"]:
            continue
        feats.append({
            "type": "Feature", "geometry": al["geom"][jcod],
            "properties": {
                "alert_id": al["alert_id"], "source": al["source"],
                "judet_cod": jcod, "judet_nume": JUDETE.get(jcod, jcod),
                "cod_culoare": cul, "cod_culoare_nume": COD_TO_NUME[cul],
                "fenomen_principal": al["fen"].get(str(cul), ""),
                "interval_text": al["interval_text"], "interval_start": al["interval_start"],
                "interval_end": al["interval_end"], "data_expirare": al["interval_end"],
                "durata_ore": al["durata_ore"], "zi": day,
            },
        })
    return feats

def _alert_card(al):
    color_counts = {}
    for cul in al["jud"].values():
        if cul > 0:
            color_counts[str(cul)] = color_counts.get(str(cul), 0) + 1
    return {
        "alert_id": al["alert_id"], "source": al["source"],
        "interval_text": al["interval_text"], "interval_start": al["interval_start"],
        "interval_end": al["interval_end"], "durata_ore": al["durata_ore"],
        "cod_culoare_max": al["cod_culoare_max"], "fenomene_pe_cod": al["fen"],
        "judete_afectate": sorted([c for c, v in al["jud"].items() if v > 0]),
        "judete_count": sum(1 for v in al["jud"].values() if v > 0),
        "judete_culori": al["jud"], "color_counts": color_counts,
        "text_alerta_html": al["mesaj_html"],
    }

def build_daily_geojson(alerts, day):
    active = [a for a in alerts if day in a["zile"]]
    general = [a for a in active if a["source"] == "general"]
    nowcast = [a for a in active if a["source"] == "nowcasting"]
    feats = _winner_features(general, day) + _winner_features(nowcast, day)
    cards = [_alert_card(a) for a in general] + [_alert_card(a) for a in nowcast]
    return {
        "type": "FeatureCollection",
        "metadata": {
            "date": day,
            "alert_count": len({a["alert_id"] for a in general}),
            "feature_count": len(_winner_features(general, day)),
            "nowcasting_count": len({a["alert_id"] for a in nowcast}),
            "active_alerts": cards,
        },
        "features": feats,
    }

def generate_all(alerts):
    all_days = sorted(set().union(*[set(a["zile"]) for a in alerts])) if alerts else []
    t = today_iso()
    cand = [d for d in all_days if d <= t]
    latest_day = (max(cand) if cand else (all_days[0] if all_days else None))

    index = {"generated_at_utc": now_utc(), "today": t, "latest_date": latest_day, "dates": {}}
    for day in all_days:
        fc = build_daily_geojson(alerts, day)
        write_json(os.path.join(DATA, f"{day}.geojson"), fc)
        gen_feats = [f for f in fc["features"] if f["properties"]["source"] == "general"]
        index["dates"][day] = {
            "alert_count": fc["metadata"]["alert_count"],
            "feature_count": fc["metadata"]["feature_count"],
            "max_color": max((f["properties"]["cod_culoare"] for f in gen_feats), default=0),
            "nowcasting_count": fc["metadata"]["nowcasting_count"],
            "has_nowcasting": fc["metadata"]["nowcasting_count"] > 0,
        }
    write_json(os.path.join(DATA, "index.json"), index)

    if latest_day:
        latest = build_daily_geojson(alerts, latest_day)
        latest["metadata"]["latest_for_date"] = latest_day
        write_json(os.path.join(DATA, "latest.geojson"), latest)

    rebuild_history_stats()
    rebuild_istoric_manifest()
    return index, latest_day

def glob_csv():
    import glob
    return glob.glob(os.path.join(ISTORIC, "*", "*.csv"))

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

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="cale catre un XML local (test)")
    ap.add_argument("--source", default="general", choices=["general", "nowcasting"])
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True); os.makedirs(ISTORIC, exist_ok=True)
    alerts = []
    if args.local:
        with open(args.local, "rb") as f:
            alerts += parse_avertizari(f.read(), args.source)
        print(f"[local:{args.source}] {args.local}: {len(alerts)} avertizari")
    else:
        for source, url in ENDPOINTS.items():
            try:
                got = parse_avertizari(fetch_xml(url), source)
                alerts += got
                print(f"[{source}] {url}: {len(got)} avertizari")
            except Exception as ex:
                print(f"[{source}] EROARE: {ex}", file=sys.stderr)

    if alerts:
        upsert_archive(alerts)
    index, latest = generate_all(alerts)
    print(f"Zile generate: {list(index['dates'].keys())}")
    print(f"latest.geojson -> {latest}")

if __name__ == "__main__":
    main()
