# MeteoAlertRO - implementare nowcasting istoric 2026-07-01

## Implementat

- Persistenta nowcasting in GeoJSON zilnic: feature-urile nowcasting existente sunt pastrate cand endpoint-ul live revine gol.
- Import manual controlat: `manual_nowcasting/nowcasting_manual_import.csv`.
- Fallback geografic pentru nowcasting fara `coordGis`: UAT daca exista `public/geodata/romania_uat.geojson`, altfel judet din `public/geodata/romania_judete.geojson` sau `public/data/judete.geojson`.
- Metadata extinsa in GeoJSON si index:
  - `general_alert_count`
  - `nowcasting_alert_count`
  - `manual_nowcasting_alert_count`
  - `general_feature_count`
  - `nowcasting_feature_count`
  - `has_manual_nowcasting`
  - `sources`
- CSV-uri extinse cu `source`, `alert_type`, `feature_meta_json`, `source_label`, `notes`.
- Arhiva dedicata nowcasting: `public/istoric/nowcasting/YYYY-MM.csv`.
- CSV agregat regenerat: `public/istoric/toate-alertele.csv`.
- Calendar cu badge `NC` / `NC*` pentru zile cu nowcasting.
- Panou lateral cu sursa `Nowcasting - import manual`, zona, geometrie si badge separat.
- Fix UI pentru cardul `Cod maxim`: latime dedicata si text pe o singura linie.
- Workflow schimbat la rulare la fiecare 15 minute.

## Date regenerate

Rularea `python src/scraper.py` a produs:

- general live: `4` avertizari.
- nowcasting live: status `200`, `46` bytes, `0` avertizari brute, `0` `coordGis`.
- import manual nowcasting: `1` avertizare.
- zile generate: `2026-06-29`, `2026-06-30`, `2026-07-01`, `2026-07-02`, `2026-07-03`.
- `latest.geojson`: `2026-07-01`.

## Validare date

`public/data/2026-06-30.geojson`:

- feature-uri totale: `43`
- feature-uri generale pastrate istoric: `42`
- feature-uri nowcasting: `1`
- `has_nowcasting`: `true`
- `has_manual_nowcasting`: `true`
- `general_alert_count`: `1`
- `nowcasting_alert_count`: `1`
- `manual_nowcasting_alert_count`: `1`
- cod maxim zi: `3` / Rosu
- cod nowcasting: `2` / Portocaliu
- surse: `general`, `nowcasting_manual`
- geometrie nowcasting: fallback judet

`public/istoric/nowcasting/2026-06.csv`:

- randuri: `1`
- sursa: `nowcasting_manual`

`public/istoric/toate-alertele.csv`:

- randuri: `18`
- randuri `nowcasting_manual`: `1`

## Limitari documentate

Endpoint-ul live nowcasting nu continea geometrii la momentul verificarii. Pentru cazul Bucuresti 2026-06-30, geometria folosita este fallback de judet, cu `match_confidence=low` si `notes` care marcheaza detaliile incomplete.

## Validare UI asteptata

- In modul toate sursele, 2026-06-30 afiseaza badge `NC*` si zona nowcasting manuala.
- In modul cod maxim, ziua/judetul pastreaza codul general mai sever cand alerta generala si nowcasting-ul se suprapun.
- In filtrul `Nowcasting`, ramane doar alerta nowcasting.
- In filtrul `General`, alerta nowcasting dispare.
- Calendarul si istoricul nu introduc zone false de tip nume UAT; se folosesc judete/coduri reale.
- Cardul `Cod maxim` pastreaza `Portocaliu`, `Rosu` si `Galben` pe o singura linie la 1366px.
