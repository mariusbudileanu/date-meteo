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

def month_number(name):
    return {_norm(k): v for k, v in LUNI.items()}.get(_norm(name or ""))

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
        exp_dt = parse_xml_datetime(a.get("dataExpirarii"))
        ap_dt = parse_xml_datetime(a.get("dataAparitiei"))
        base_year = (exp_dt or ap_dt or datetime.now()).year
        sections = extract_sections_from_message(a.get("mesaj", ""), base_year)
        sections_by_code = {}
        for sec in sections:
            if sec["code"] in sections_by_code:
                print(f"  ! multiple sections for code {sec['code']} in one ANM message; keeping first", file=sys.stderr)
                continue
            sections_by_code[sec["code"]] = sec
        s, e = parse_interval(a.get("intervalul", ""), a.get("dataAparitiei", ""), a["dataExpirarii"], a.get("mesaj", ""))
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
        fen = {code: sec["phenomena"] for code, sec in sections_by_code.items() if sec.get("phenomena")}
        if not fen:
            fen = extract_phenomena_by_code(a.get("mesaj", ""))
        section_days = [
            set(zile_acoperite(sec["valid_from"], sec["valid_to"]))
            for sec in sections
            if sec.get("valid_from") and sec.get("valid_to")
        ]
        zile = sorted(set().union(*section_days)) if section_days else zile_acoperite(s, e)
        interval_text = a.get("intervalul", "")
        section_intervals = []
        for sec in sections:
            if sec.get("interval_text") and sec["interval_text"] not in section_intervals:
                section_intervals.append(sec["interval_text"])
        if section_intervals and ("CONFORM TEXTELOR" in _norm(interval_text) or not interval_text):
            interval_text = "; ".join(section_intervals)
        alerts.append({
            "source": source,
            "alert_id": make_alert_id(source, s.isoformat(), e.isoformat(), jud_cul),
            "content_hash": make_content_hash(mesaj_plain, jud_cul),
            "data_emitere": a.get("dataAparitiei", ""),
            "interval_text": interval_text,
            "interval_start": s.isoformat(),
            "interval_end": e.isoformat(),
            "durata_ore": round((e - s).total_seconds() / 3600, 1),
            "cod_culoare_max": max(jud_cul.values()),
            "zona_afectata_text": a.get("zonaAfectata", ""),
            "zile": zile,
            "jud": jud_cul,
            "geom": geom,
            "fen": fen,
            "sections": sections,
            "sections_by_code": sections_by_code,
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
            feats.append({
                "type": "Feature", "geometry": al["geom"][jcod],
                "properties": {
                    "alert_id": al["alert_id"], "source": al["source"],
                    "judet_cod": jcod, "judet_nume": JUDETE.get(jcod, jcod),
                    "cod_culoare": cul, "cod_culoare_nume": COD_TO_NUME[cul],
                    "fenomen_principal": fenomen,
                    "fenomen_group": phenomenon_group(fenomen),
                    "zona_text": sec.get("zones_text") or al["zona_afectata_text"],
                    "interval_text": interval_text, "interval_start": fs.isoformat(),
                    "interval_end": fe.isoformat(), "data_expirare": fe.isoformat(),
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
    general_feats = _all_features(general, day)
    nowcast_feats = _all_features(nowcast, day)
    feats = general_feats + nowcast_feats
    cards = [_alert_card(a) for a in general] + [_alert_card(a) for a in nowcast]
    alerts_by_county, max_by_county = _county_metadata(feats)
    return {
        "type": "FeatureCollection",
        "metadata": {
            "date": day,
            "alert_count": len({a["alert_id"] for a in general}),
            "feature_count": len(general_feats),
            "max_color": max((f["properties"]["cod_culoare"] for f in general_feats), default=0),
            "nowcasting_count": len({a["alert_id"] for a in nowcast}),
            "active_alerts": cards,
            "alerts_by_county": alerts_by_county,
            "max_by_county": max_by_county,
        },
        "features": feats,
    }

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
    general_feats = [f for f in feats if f.get("properties", {}).get("source") == "general"]
    codes = sorted({
        int(f.get("properties", {}).get("cod_culoare") or 0)
        for f in general_feats
        if int(f.get("properties", {}).get("cod_culoare") or 0) > 0
    })
    phenomena = sorted({
        f.get("properties", {}).get("fenomen_group")
        or phenomenon_group(f.get("properties", {}).get("fenomen_principal", ""))
        for f in general_feats
        if f.get("properties")
    })
    max_color = meta.get("max_color")
    if max_color is None:
        max_color = max(codes, default=0)
    return {
        "date": day,
        "alert_count": meta.get("alert_count", len({f.get("properties", {}).get("alert_id") for f in general_feats if f.get("properties", {}).get("alert_id")})),
        "feature_count": meta.get("feature_count", len(general_feats)),
        "max_color": max_color,
        "max_code": max_color,
        "nowcasting_count": meta.get("nowcasting_count", 0),
        "has_nowcasting": bool(meta.get("nowcasting_count", 0)),
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
        "nowcasting_ids": set(),
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
                is_nc = (str(r.get("source")).lower() == "nowcasting")
                alert_id = r.get("alert_id") or r.get("content_hash") or ""
                for day in zile_acoperite(start, end):
                    entry = by_day[day]
                    entry["alert_ids"].add(alert_id or day)
                    if is_nc and alert_id:
                        entry["nowcasting_ids"].add(alert_id)
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
            continue
        dates[day] = {
            "date": day,
            "file": None,
            "has_geojson": False,
            "has_archive": True,
            "alert_count": len(archived["alert_ids"]),
            "feature_count": 0,
            "max_color": None,
            "max_code": None,
            "nowcasting_count": len(archived["nowcasting_ids"]),
            "has_nowcasting": len(archived["nowcasting_ids"]) > 0,
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

def generate_all(alerts):
    all_days = sorted(set().union(*[set(a["zile"]) for a in alerts])) if alerts else []
    for day in all_days:
        fc = build_daily_geojson(alerts, day)
        write_json(os.path.join(DATA, f"{day}.geojson"), fc)

    index, latest_day = rebuild_data_index()
    if latest_day:
        latest_path = os.path.join(DATA, f"{latest_day}.geojson")
        if latest_day in all_days:
            latest = build_daily_geojson(alerts, latest_day)
        else:
            with open(latest_path, encoding="utf-8") as f:
                latest = json.load(f)
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

    fetch_and_save_current_weather()

    if alerts:
        upsert_archive(alerts)
    index, latest = generate_all(alerts)
    print(f"Zile generate: {list(index['dates'].keys())}")
    print(f"latest.geojson -> {latest}")

if __name__ == "__main__":
    main()
