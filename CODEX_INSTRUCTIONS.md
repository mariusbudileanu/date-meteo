# Instrucțiuni pentru Codex — MeteoAlertRO

**Rol: EXECUTOR, nu autor.** Fișierele de mai jos sunt finite și testate. NU le rescrie, NU le
„optimiza", NU schimba logica. Le pui exact la căile indicate, înlocuind ce există, rulezi testele
și verifici. Dacă ceva nu merge, raportează — nu reproiecta.

## 1. Plasarea fișierelor (înlocuiește fișierele existente)

| Fișier livrat | Cale în repo |
|---|---|
| `scraper.py` | `src/scraper.py` (înlocuiește complet scraperul vechi) |
| `test_scraper.py` | `src/test_scraper.py` (lângă scraper) |
| `index.html` | `public/index.html` |
| `app.js` | `public/js/app.js` |
| `style.css` | `public/css/style.css` |
| `scrape-anm.yml` | `.github/workflows/scrape-anm.yml` |

**Curățenie obligatorie:**
- Șterge sau dezactivează ORICE workflow vechi de cron (ca să nu ruleze două joburi care comit în paralel).
- Dacă în `public/index.html` vechi exista un al doilea calendar sau un `<input type="date" id="alert-date-picker">`, dispare — noul `index.html` are UN SINGUR calendar și niciun date-picker nativ.

## 2. Rulează testele (OBLIGATORIU înainte de commit)

```bash
cd src
python test_scraper.py
```
Așteptat: `TOATE TESTELE AU TRECUT (7 teste)`. Testele nu folosesc rețeaua (fixture sintetic).
Dacă pică vreun test, OPREȘTE-TE și raportează ieșirea exactă.

## 3. Test funcțional al scraperului pe date reale (fără rețea)

Pune un XML ANM real la `samples/avertizari.xml`, apoi:
```bash
python src/scraper.py --local samples/avertizari.xml
```
Verifică să se genereze: `public/data/index.json`, `public/data/<zi>.geojson` pentru fiecare zi
acoperită, `public/data/latest.geojson`, `public/data/history_stats.json`,
`public/istoric/<an>/<an>-<lună>.csv`, `public/istoric/index.json`, `public/istoric/README.md`.

Rulează DE DOUĂ ORI aceeași comandă și confirmă că CSV-ul lunar NU se dublează (upsert idempotent).

## 4. Test în browser (local)

```bash
cd public
python -m http.server 8000
# deschide http://localhost:8000
```
De verificat:
1. Calendarul apare O SINGURĂ DATĂ și este compact (max ~360px lățime).
2. Zilele cu cod sunt colorate (galben/portocaliu/roșu); zilele viitoare acoperite au contur punctat.
3. Clic pe o zi schimbă harta + cardurile; o zi fără date arată „Nu există avertizări înregistrate...".
4. Checkbox-ul „Afișează nowcasting" din header ascunde/afișează stratul nowcasting (implicit ascuns).
5. Harta arată poligoanele generale colorate; popup compact la clic pe județ; panoul de detalii se completează.
6. Secțiunile „Istoric pe județ" și „Descărcări" se populează.

## 5. Configurare GitHub Pages (verifică ÎNAINTE de a te baza pe cron)

Workflow-ul comite în `public/data` și `public/istoric`. Asta funcționează DOAR dacă Pages servește
site-ul din folderul `public/`:
- Dacă Pages e prin GitHub Actions (artifact din `public/`) → ok ca atare.
- Dacă Pages e „from branch" cu folder `/ (root)` → atunci `public/` NU e servit. În acest caz:
  - rulează scraperul cu variabila `METEO_OUT="."` (decomentează blocul `env:` din workflow),
  - și schimbă în workflow `git add public/data public/istoric` în `git add data istoric`,
  - sau mută conținutul lui `public/` în rădăcina repo-ului.

## 6. Pornește o rulare manuală a workflow-ului

GitHub → tab **Actions** → **Scrape ANM** → **Run workflow**. Confirmă că jobul e verde și că a făcut
commit cu fișierele actualizate (sau „Nimic de comis" dacă nu erau modificări).

## Note de implementare (context, nu de modificat)
- Scraperul nu are dependențe externe (doar stdlib) → fără `pip install` în CI.
- O `<avertizare>` ANM = o fereastră cu culori fixe pe județ; evoluția zi-cu-zi = mai multe ferestre,
  rezolvate „max culoare/județ" pe fiecare zi. Buletinul curent conține și zilele viitoare → calendar în avans.
- `general` și `nowcasting` sunt separate: nowcasting NU colorează calendarul și e strat propriu, cu toggle.
- `alert_id` e stabil (re-emiterea nu dublează); `content_hash` marchează editările (`revizuit=true`).
- `data/judete.geojson` (strat de bază cu toate județele) este OPȚIONAL și nu e generat de scraper;
  dacă lipsește, harta merge fără el. Poate fi adăugat separat (contur județe în EPSG:4326).
