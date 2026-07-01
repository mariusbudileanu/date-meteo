# MeteoAlertRO

MeteoAlertRO este un proiect static care descarca avertizarile ANM, combina fluxurile General si Nowcasting, arhiveaza avertizarile in CSV-uri lunare si publica o harta Leaflet cu situatia meteo pe zile pentru Romania.

## Rulare locala

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python src/scraper.py
```

Scraperul citeste:

- `https://www.meteoromania.ro/avertizari-xml.php`
- `https://www.meteoromania.ro/avertizari-nowcasting-xml.php`

Daca un endpoint esueaza, celalalt continua sa fie procesat. Geometriile `POLYGON` si `MULTIPOLYGON` din `coordGis` sunt interpretate ca EPSG:3857 si reproiectate obligatoriu in EPSG:4326, cu coordonate GeoJSON `[longitude, latitude]`.

Scraperul trateaza fiecare element `<avertizare>` ca o fereastra logica de valabilitate. `dataAparitiei` este pastrata ca data de emitere, iar intervalul real este extras din `intervalul` sau din textul mesajului ANM, cu `dataExpirarii` ca sfarsit sigur al ferestrei.

Lipsa codului de culoare, valorile goale, `null`, `0` sau necunoscute sunt tratate ca `Verde`. Fisierele zilnice coloreaza doar zonele cu cod mai mare decat 0, iar `judete.geojson` ofera stratul de baza verde.

## Date generate

La fiecare rulare se scriu fisiere in `public/data/`:

- `latest.geojson`
- `YYYY-MM-DD.geojson`, pentru fiecare zi acoperita de ferestrele ANM curente
- `index.json`, cu `dates` ca obiect pentru calendar
- `judete.geojson`
- `history_stats.json`

Pentru fiecare zi, scraperul rezolva o singura geometrie pe judet/zona prin severitatea maxima din avertizarile active in acea data. Daca nu exista alerte valide, `latest.geojson` ramane un `FeatureCollection` gol, cu metadata despre cauza.

Arhiva descarcabila se scrie in `public/istoric/`:

- `istoric/YYYY/YYYY-MM.csv`
- `istoric/nowcasting/YYYY-MM.csv`
- `istoric/index.json`
- `istoric/toate-alertele.csv`
- `istoric/README.md`

CSV-urile lunare folosesc UTF-8-SIG pentru compatibilitate cu Excel si sunt actualizate idempotent pe `alert_id` stabil.
Nowcasting-ul istoric este pastrat separat in `istoric/nowcasting/`, iar importurile manuale controlate pot fi puse in `manual_nowcasting/nowcasting_manual_import.csv`. Daca XML-ul live nowcasting nu contine `coordGis`, scraperul nu inventeaza zone: foloseste doar importuri manuale documentate sau fallback de judet/UAT cand exista o localizare verificabila.

## Frontend

Pentru testarea hartii statice:

```powershell
cd public
python -m http.server 8000
```

Apoi deschide `http://localhost:8000`.

Frontend-ul foloseste HTML, CSS si JavaScript simplu, Leaflet pentru harta si DOMPurify pentru mesajele HTML venite din XML.

## GitHub Pages

Workflow-ul `.github/workflows/scrape-anm.yml` ruleaza la fiecare 15 minute si poate fi pornit manual din GitHub Actions. El instaleaza Python, instaleaza dependintele, ruleaza `python src/scraper.py`, comite modificarile din `public/data/` si `public/istoric/`, apoi publica folderul `public/` prin GitHub Pages.

Daca Pages nu se activeaza automat, mergi in GitHub la `Settings` -> `Pages` si seteaza `Source` la `GitHub Actions`.
