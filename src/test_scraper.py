"""
Teste pentru scraper.py — rulează cu:  python test_scraper.py   (sau: pytest test_scraper.py)
Nu necesită rețea: folosește un XML sintetic. Fără dependențe externe.
"""
import json, math, os, tempfile

os.environ["METEO_OUT"] = tempfile.mkdtemp(prefix="meteo_test_")
import scraper as S

R = 6378137.0
def fwd(lon, lat):  # WGS84 -> Web Mercator (forward), pt. a construi fixture-uri
    x = lon * math.pi / 180.0 * R
    y = R * math.log(math.tan(math.pi/4 + (lat*math.pi/180.0)/2))
    return f"{x:.6f} {y:.6f}"

def square(lon, lat, d=0.2):
    pts = [fwd(lon, lat), fwd(lon+d, lat), fwd(lon+d, lat+d), fwd(lon, lat+d), fwd(lon, lat)]
    return "MULTIPOLYGON (((" + ", ".join(pts) + ")))"

def avertizare(interval, ap, exp, judete, mesaj=""):
    js = "".join(f'<judet cod="{c}" culoare="{col}" useCoordGis="true" coordGis="{square(lo,la)}"/>'
                 for c,col,lo,la in judete)
    return (f'<avertizare tipMesaj="0" numeTipMesaj="Avertizare" dataAparitiei="{ap}" '
            f'dataExpirarii="{exp}" culoare="2" intervalul="{interval}" '
            f'zonaAfectata="x" mesaj="{mesaj}">{js}</avertizare>')

MESAJ = ("COD GALBEN Fenomene vizate: val de caldura "
         "COD PORTOCALIU Fenomene vizate: canicula "
         "COD ROSU Fenomene vizate: temperaturi extreme ")

GENERAL_XML = ('<?xml version="1.0"?><avertizari>'
    + avertizare("28 iunie, ora 10 – 29 iunie, ora 10", "2026-06-27T10:00", "2026-06-29T10:00",
                 [("CL",1,26.0,44.2), ("BR",2,27.5,45.0)], MESAJ)
    + avertizare("29 iunie, ora 10 – 1 iulie, ora 10", "2026-06-27T10:00", "2026-07-01T10:00",
                 [("CL",3,26.0,44.2), ("BR",3,27.5,45.0)], MESAJ)
    + '</avertizari>').encode()

NOWCAST_XML = ('<?xml version="1.0"?><avertizari>'
    + avertizare("29 iunie, ora 12 – 29 iunie, ora 14", "2026-06-29T12:00", "2026-06-29T14:00",
                 [("TM",2,21.0,45.7)], "COD PORTOCALIU Fenomene vizate: vijelii ")
    + '</avertizari>').encode()


def test_interval_parsing():
    s, e = S.parse_interval("28 iunie, ora 10 – 29 iunie, ora 10", "2026-06-27T10:00", "2026-06-29T10:00")
    assert s.isoformat() == "2026-06-28T10:00:00" and e.isoformat() == "2026-06-29T10:00:00"
    # fallback la dataAparitiei daca lipseste intervalul
    s2, e2 = S.parse_interval("", "2026-06-29T12:00", "2026-06-29T14:00")
    assert s2.isoformat() == "2026-06-29T12:00:00"
    print("ok interval_parsing")

def test_phenomena_by_code():
    fen = S.extract_phenomena_by_code(MESAJ)
    assert fen["1"].startswith("val de caldura") and fen["2"] == "canicula" and fen["3"] == "temperaturi extreme"
    print("ok phenomena_by_code")

def test_wkt_bbox_in_romania():
    g = S.wkt_to_geojson_geometry(square(26.0, 44.2))
    lons = [c[0] for ring in g["coordinates"][0] for c in ring]
    lats = [c[1] for ring in g["coordinates"][0] for c in ring]
    assert 20 <= min(lons) and max(lons) <= 30 and 43 <= min(lats) and max(lats) <= 49
    print("ok wkt_bbox")

def test_per_day_resolution_and_advance():
    alerts = S.parse_avertizari(GENERAL_XML, "general")
    # ziua 28: doar primul interval -> CL=1, BR=2
    d28 = {f["properties"]["judet_cod"]: f["properties"]["cod_culoare"]
           for f in S.build_daily_geojson(alerts, "2026-06-28")["features"]}
    assert d28 == {"CL": 1, "BR": 2}, d28
    # ziua 29 (tranzitie): max intre intervale -> CL=3, BR=3
    d29 = {f["properties"]["judet_cod"]: f["properties"]["cod_culoare"]
           for f in S.build_daily_geojson(alerts, "2026-06-29")["features"]}
    assert d29 == {"CL": 3, "BR": 3}, d29
    # ziua 30 (viitor, cunoscut in avans) exista
    assert any(f for f in S.build_daily_geojson(alerts, "2026-06-30")["features"])
    print("ok per_day_resolution + advance")

def test_alert_id_stable_and_content_hash():
    a1 = S.parse_avertizari(GENERAL_XML, "general")[0]
    # acelasi interval+judete, alt dataAparitiei -> acelasi alert_id
    xml2 = GENERAL_XML.replace(b"2026-06-27T10:00", b"2026-06-28T10:00")
    a2 = S.parse_avertizari(xml2, "general")[0]
    assert a1["alert_id"] == a2["alert_id"], "alert_id trebuie stabil la re-emitere"
    # mesaj editat -> content_hash diferit
    xml3 = GENERAL_XML.replace(b"temperaturi extreme", b"temperaturi extreme MODIFICAT")
    a3 = S.parse_avertizari(xml3, "general")[0]
    assert a1["content_hash"] != a3["content_hash"]
    print("ok alert_id_stable + content_hash")

def test_nowcasting_separation():
    alerts = S.parse_avertizari(GENERAL_XML, "general") + S.parse_avertizari(NOWCAST_XML, "nowcasting")
    fc = S.build_daily_geojson(alerts, "2026-06-29")
    srcs = {f["properties"]["source"] for f in fc["features"]}
    assert "general" in srcs and "nowcasting" in srcs
    # alert_count din metadata numara DOAR general
    assert fc["metadata"]["alert_count"] == 2 and fc["metadata"]["nowcasting_count"] == 1
    print("ok nowcasting_separation")

def test_full_run_idempotent():
    S.generate_all  # exists
    import shutil
    base = os.environ["METEO_OUT"]
    for p in ("data","istoric"):
        shutil.rmtree(os.path.join(base,p), ignore_errors=True)
    alerts = S.parse_avertizari(GENERAL_XML, "general") + S.parse_avertizari(NOWCAST_XML, "nowcasting")
    S.upsert_archive(alerts); idx1,_ = S.generate_all(alerts)
    csvp = [os.path.join(r,f) for r,_,fs in os.walk(os.path.join(base,"istoric")) for f in fs if f.endswith(".csv")]
    import csv as _csv
    rows1 = sum(len(list(_csv.DictReader(open(p, encoding="utf-8-sig")))) for p in csvp)
    # re-run
    S.upsert_archive(alerts); S.generate_all(alerts)
    rows2 = sum(len(list(_csv.DictReader(open(p, encoding="utf-8-sig")))) for p in csvp)
    assert rows1 == rows2, f"upsert nu e idempotent: {rows1} vs {rows2}"
    # index.json are latest_date + dates
    idx = json.load(open(os.path.join(base,"data","index.json")))
    assert idx["latest_date"] and idx["dates"]
    # history_stats e listă
    hs = json.load(open(os.path.join(base,"data","history_stats.json")))
    assert isinstance(hs["counties"], list)
    print(f"ok full_run_idempotent (rânduri={rows1})")

if __name__ == "__main__":
    fns = [v for k,v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns: fn()
    print(f"\nTOATE TESTELE AU TRECUT ({len(fns)} teste)")
