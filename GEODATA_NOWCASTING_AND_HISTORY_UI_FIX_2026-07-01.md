# Geodata Nowcasting and History UI Fix - 2026-07-01

## Context

Schimbarea finalizeaza fallback-ul geospatial pentru nowcasting si reparatia vizuala pentru panoul "Istoric judet". Fisierele geodata locale raman in `src/geodata/`, iar frontend-ul consuma doar GeoJSON-urile generate in `public/data/`.

## Fisiere geodata

- Judete: `src/geodata/romania_judete.geojson`
- UAT: `src/geodata/romania_uat.geojson`
- Schema judete detectata: nume=`name`, cod=`mnemonic`, total=42
- Schema UAT detectata: nume=`name`, judet=`countyMn`, SIRUTA/natcode=`natcode`, total=3186
- CRS detectat pentru ambele fisiere: `EPSG:3857`
- Transformare aplicata in scraper: `EPSG:3857` -> `EPSG:4326`

## Workflow

Workflow-ul `.github/workflows/scrape-anm.yml` ramane la frecventa de 15 minute:

```yaml
- cron: "*/15 * * * *"
```

`workflow_dispatch` este pastrat pentru rulare manuala.

## Nowcasting

Scraperul foloseste ordinea de geometrie:

1. `coordGis`, daca exista in XML.
2. Fallback UAT prin `romania_uat.geojson`, daca exista localitati.
3. Fallback judet prin `romania_judete.geojson`, daca UAT nu se potriveste.
4. Arhivare fara geometrie, daca nu exista geometrie determinabila.

Logurile runtime includ frecventa workflow-ului, nowcasting live, importul manual, arhiva pastrata si distributia surselor de geometrie.

## Bucuresti 2026-06-30

Importul manual pentru Bucuresti din 2026-06-30 este inclus in:

- `public/data/2026-06-30.geojson`
- `public/istoric/nowcasting/2026-06.csv`
- `public/data/index.json`

Feature-ul nowcasting rezultat are:

- `source=nowcasting_manual`
- `alert_type=nowcasting`
- `geometry_source=uat_match`
- `match_confidence=high`
- coordonate normale `EPSG:4326` in jurul Bucurestiului, fara valori de milioane.

## Fix UI Istoric judet

Panoul "Istoric judet" are acum un header separat sub dropdown:

- eyebrow "Judet selectat"
- titlu judet separat
- badge de severitate aliniat in header
- grid de statistici sub header

Pe mobil, headerul trece pe coloana, badge-ul ramane sub titlu, iar cardurile se afiseaza pe o singura coloana fara scroll orizontal.

## Teste

| Test | Rezultat |
| --- | --- |
| `python -m py_compile src/scraper.py src/test_scraper.py` | PASS |
| `python src/test_scraper.py` | PASS, 16 teste |
| `python src/scraper.py` | PASS |
| Log CRS judete `EPSG:3857 -> EPSG:4326` | PASS |
| Log CRS UAT `EPSG:3857 -> EPSG:4326` | PASS |
| Bucuresti nowcasting manual in `2026-06-30.geojson` | PASS |
| `geometry_source=uat_match` si `match_confidence=high` | PASS |
| Coordonate Bucuresti in lon/lat, fara valori de milioane | PASS |
| `index.json` cu `has_nowcasting`, `manual_nowcasting_alert_count`, `calendar_badge=NC*` | PASS |
| Browser local: 30 iunie cu badge `NC*` | PASS |
| Browser local: sursa General ascunde nowcasting | PASS |
| Browser local: sursa Nowcasting afiseaza importul Bucuresti | PASS |
| Browser local: sursa All afiseaza general + nowcasting | PASS |
| Browser local: panou istoric desktop fara suprapuneri | PASS |
| Browser local: panou istoric mobil fara scroll orizontal | PASS |

## Probleme ramase

- Endpoint-ul live de nowcasting a returnat XML cu `raw_alerts=1`, dar fara `coordGis` si fara avertizare parsabila ca feature live in rularea testata; rezultatul live este `live=0`.
- Nowcasting-ul istoric/manual este pastrat si nu este sters cand endpoint-ul live intoarce 0 feature-uri.
