# MeteoAlertRO

MeteoAlertRO este un proiect static care descarca avertizarile ANM, combina fluxurile General si Nowcasting si publica o harta Leaflet cu alertele meteo pentru Romania.

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

Lipsa codului de culoare, valorile goale, `null`, `0` sau necunoscute sunt tratate ca `Verde`.

## Date generate

La fiecare rulare se scriu fisiere in `public/data/`:

- `latest.geojson`
- `YYYY-MM-DD.geojson`, doar cand exista cel putin un feature valid
- `index.json`

Daca nu exista alerte valide, `latest.geojson` ramane un `FeatureCollection` gol, iar data curenta nu este adaugata in `index.json`.

## Frontend

Pentru testarea hartii statice:

```powershell
cd public
python -m http.server 8000
```

Apoi deschide `http://localhost:8000`.

Frontend-ul foloseste HTML, CSS si JavaScript simplu, Leaflet pentru harta si DOMPurify pentru mesajele HTML venite din XML.

## GitHub Pages

Workflow-ul `.github/workflows/scrape_and_deploy.yml` ruleaza de 4 ori pe zi si poate fi pornit manual din GitHub Actions. El instaleaza Python, instaleaza dependintele, ruleaza `python src/scraper.py`, comite doar modificarile din `public/data/` si publica folderul `public/` prin GitHub Pages.

Daca Pages nu se activeaza automat, mergi in GitHub la `Settings` -> `Pages` si seteaza `Source` la `GitHub Actions`.
