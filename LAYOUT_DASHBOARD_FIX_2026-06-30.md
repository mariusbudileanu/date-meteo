# LAYOUT DASHBOARD FIX - 2026-06-30

## Obiectiv

Calibrarea ferestrelor dashboardului MeteoAlertRO fără modificarea scraperului, parserului sau datelor generate.

## Fișiere modificate

- `public/index.html`
- `public/css/style.css`
- `public/js/app.js`

## Modificări aplicate

- Harta Leaflet a fost separată de panourile de dashboard.
- Panourile `Rezumat zi`, `Județ selectat` și `Alerte afișate` au fost mutate într-un rail lateral dedicat.
- Layoutul principal folosește grid stabil pe desktop: controale / hartă / detalii.
- Breakpointurile tabletă și mobil au fost calibrate pentru stivuire fără suprapuneri.
- Containerul Leaflet primește dimensiuni explicite și recalculare la resize/orientare.
- Secțiunea `Descărcări CSV` folosește din nou tabel valid, compatibil cu randarea existentă din JavaScript.

## Verificare layout

Viewporturi testate local în Chrome headless:

- 1920x1080: PASS
- 1600x900: PASS
- 1366x768: PASS
- 1280x720: PASS
- 1024x768: PASS
- 768x1024: PASS
- 390x844: PASS

Rezultate comune:

- fără overflow orizontal la nivel de document;
- headerul nu acoperă dashboardul;
- panourile principale nu se suprapun;
- `#feature-details` este în `.detail-panel`, nu în containerul hărții;
- `.visible-alerts-strip` este în `.detail-panel`, nu în containerul hărții;
- `#alerts-map` are dimensiuni nenule și controlate;
- tabelul de descărcări rămâne conținut în panoul său.

## Verificare funcțională

- Ultimele alerte: `2026-06-30`, 65 feature-uri vizibile.
- Calendar istoric: `2026-07-01`, 90 feature-uri vizibile.
- Dată fără alerte: `2026-07-04`, 0 feature-uri și mesaj de lipsă date.
- Filtru sursă `General + Nowcasting`: funcțional.
- Filtru fenomen `Ploi`: 23 feature-uri.
- Filtru fenomen `Temperaturi extreme / caniculă`: 42 feature-uri.
- Filtru cod `Roșu`: 40 feature-uri.
- Mod hartă `Compară avertizările`: secțiunea de comparare devine vizibilă.
- Click pe județ pe hartă: popup Leaflet vizibil și panoul `Județ selectat` se actualizează.
- Istoric județ: 42 opțiuni de județ disponibile.
- Descărcări CSV: 2 linkuri CSV disponibile.

## Confirmări

- Scraperul nu a fost modificat.
- Parserul nu a fost modificat.
- Fișierele din `public/data/` nu au fost modificate manual.
- Modificarea este strict de structură HTML, CSS de layout și recalibrare Leaflet la resize.
