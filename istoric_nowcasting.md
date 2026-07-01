Lucrează în repository-ul local:

```text
C:\Users\mariu\Date\_meteoalert
```

Pagina publică:

```text
https://mariusbudileanu.github.io/date-meteo/
```

Nu facem redesign general acum. Nu schimbăm tema. Nu mutăm secțiuni mari. Rezolvăm strict trei probleme funcționale:

1. nowcasting-ul trebuie arhivat și afișat și pentru date istorice;
2. popup-ul / tooltip-ul pe județ trebuie să afișeze informații utile, nu doar numele;
3. adăugăm opțional „starea vremii curente” din API-ul ANM în panoul județului selectat.

---

# 1. Nowcasting istoric — obligatoriu

Problema actuală:

* nowcasting-ul este tratat ca ceva live / temporar;
* dacă dispare din endpoint, nu mai este vizibil;
* calendarul și istoricul nu îl păstrează suficient de clar;
* vrem ca nowcasting-ul să rămână vizibil în trecut, exact ca avertizările generale.

## 1.1. Regula principală

Orice avertizare nowcasting colectată la o rulare trebuie:

```text
1. salvată în GeoJSON-ul zilei corespunzătoare;
2. salvată în arhivă CSV;
3. inclusă în index.json;
4. vizibilă în calendar pentru ziua respectivă;
5. încărcabilă ulterior din calendar, chiar dacă endpoint-ul live nu o mai returnează.
```

Nu este acceptabil ca nowcasting-ul să fie doar live.

## 1.2. Structură în GeoJSON

În fiecare feature nowcasting, proprietățile trebuie să includă clar:

```json
{
  "source": "nowcasting",
  "alert_type": "nowcasting",
  "alert_id": "...",
  "feature_id": "...",
  "county_code": "AB",
  "county_name": "Alba",
  "zone_name": "Alba - zona montană",
  "display_name": "Alba - zona montană",
  "culoare": "1",
  "cod": "Galben",
  "fenomen_principal": "...",
  "fenomen_group": "...",
  "valid_from": "...",
  "valid_to": "...",
  "interval_valabilitate_text": "...",
  "mesaj_plain": "..."
}
```

Important:

* `zone_name` poate fi „Alba Munte 2” sau similar;
* dar `county_name` trebuie să fie „Alba”;
* pentru istoricul județean se folosește `county_name`, nu `zone_name`.

## 1.3. Istoric nowcasting separat sau integrat controlat

Creează arhivă lunară pentru nowcasting, de exemplu:

```text
public/istoric/nowcasting/2026-06.csv
public/istoric/nowcasting/2026-07.csv
```

sau include în arhiva generală, dar obligatoriu cu:

```text
source = nowcasting
alert_type = nowcasting
county_name = județ real
zone_name = zona specială
```

În dropdown-ul principal de istoric pe județ trebuie să apară doar județe reale:

```text
Alba
Arad
Argeș
...
```

Nu trebuie să apară:

```text
Alba Munte 2
Alba zona joasă 1
```

Acestea pot apărea doar în detaliile unei alerte nowcasting, nu în selectorul județean.

## 1.4. index.json trebuie să includă nowcasting istoric

`public/data/index.json` trebuie reconstruit din toate fișierele zilnice existente.

Pentru fiecare zi, indexul trebuie să conțină separat:

```json
{
  "date": "2026-07-01",
  "file": "2026-07-01.geojson",
  "general_alert_count": 3,
  "nowcasting_alert_count": 2,
  "alert_count": 5,
  "feature_count": 80,
  "max_code": 3,
  "sources": ["general", "nowcasting"],
  "has_nowcasting": true,
  "phenomena": ["temperaturi extreme", "ploi/vijelii"]
}
```

Calendarul trebuie să coloreze ziua dacă există:

* avertizare generală;
* nowcasting;
* sau ambele.

Dacă ziua are doar nowcasting, trebuie să fie tot vizibilă în calendar.

## 1.5. UI pentru calendar

În calendar:

* zi cu avertizare generală: culoare după cod maxim;
* zi cu nowcasting: adaugă punct / badge mic `NC`;
* zi cu general + nowcasting: culoare după cod maxim + badge `NC`;
* tooltip calendar:

  ```text
  3 avertizări ANM · 2 nowcasting · cod maxim Roșu
  ```

## 1.6. UI pentru hartă

Nowcasting-ul trebuie să apară când sursa selectată permite asta:

```text
Sursă: General
Sursă: Nowcasting
Sursă: General + Nowcasting
```

Stil nowcasting:

* contur punctat;
* badge `NC`;
* opacitate diferită;
* să fie vizual diferit de general.

## 1.7. Test obligatoriu cu fixture nowcasting

Dacă endpoint-ul live nowcasting returnează 0, nu este o eroare. Dar trebuie test controlat.

Creează fixture sau demo:

```text
?demo=nowcasting
```

sau include în:

```text
?demo=overlap
```

Scenariu minim:

```text
Județ: Alba
Zonă: Alba - zona montană
Cod: Galben
Fenomen: averse / descărcări electrice
Sursa: Nowcasting
Valabilitate: 1 oră
```

Teste:

```text
1. nowcasting apare în hartă când sursa = Nowcasting sau General + Nowcasting;
2. nowcasting dispare când sursa = General;
3. nowcasting are stil diferit;
4. nowcasting apare în calendarul zilei demo;
5. nowcasting este arhivat;
6. selectorul de istoric pe județ afișează Alba, nu Alba Munte 2;
7. la click pe zona nowcasting, panoul afișează județul asociat și zona specială.
```

---

# 2. Popup / tooltip județ — fix obligatoriu

Problema actuală:

* la click pe județ apare doar numele;
* nu apar coduri;
* nu apar fenomene;
* nu apare intervalul;
* nu apare numărul de alerte;
* pare că interacțiunea este incompletă.

## 2.1. Regula pentru popup

Popup-ul de pe hartă trebuie să fie scurt, dar informativ.

Pentru județ cu o alertă:

```text
Cluj
1 avertizare activă
Cod: Roșu
Fenomen: caniculă / temperaturi extreme
Valabil până la: 1 iulie, ora 10
```

Pentru județ cu alerte multiple:

```text
Cluj
2 avertizări active
Cod maxim: Roșu
Fenomene: caniculă, ploi/vijelii
Click pentru detalii în panoul lateral
```

Pentru zonă nowcasting:

```text
Alba - zona montană
Nowcasting
Cod: Galben
Fenomen: averse / descărcări electrice
Valabil până la: ...
```

Nu afișa text complet ANM în popup.

## 2.2. Panoul lateral

Când se selectează un județ, panoul lateral trebuie să afișeze toate alertele active pentru acel județ.

Exemplu:

```text
Județ: Cluj
Avertizări active: 2
Cod maxim: Roșu

1. Cod roșu — caniculă / temperaturi extreme
   Interval: 30 iunie, ora 10 – 1 iulie, ora 10
   Sursa: General ANM

2. Cod galben — ploi / vijelii
   Interval: 1 iulie, ora 12 – 1 iulie, ora 23
   Sursa: General ANM
```

Dacă există nowcasting:

```text
Nowcasting activ:
1. Cod galben — averse / descărcări electrice
   Zonă: Alba - zona montană
   Interval: ...
```

## 2.3. Implementare tehnică

În `public/js/app.js`, nu lega popup-ul doar la `feature.properties.name`.

Trebuie să folosești gruparea deja existentă sau să creezi:

```javascript
function getFeatureCountyKey(feature) { ... }
function getVisibleFeaturesForCounty(countyKey) { ... }
function getVisibleFeaturesForNowcastingZone(feature) { ... }
function summarizeFeatureGroup(features) { ... }
function buildMapPopupHtml(title, features) { ... }
function renderSelectedAreaPanel(title, features) { ... }
```

În modul `Cod maxim`, chiar dacă pe hartă desenezi un singur poligon reprezentativ, popup-ul trebuie să caute toate alertele active pentru acel județ în `featuresByCounty[countyKey]`.

Nu folosi doar feature-ul desenat.

## 2.4. Fallback-uri curate

Nu afișa niciodată:

```text
undefined
null
[object Object]
NaN
```

Folosește:

```text
Fenomen: conform textului ANM
Interval: indisponibil
Sursa: ANM
```

## 2.5. Test obligatoriu popup

Testează local:

```text
1. click pe județ cu o alertă -> popup are cod, fenomen, interval;
2. click pe județ cu alerte multiple -> popup are număr alerte și cod maxim;
3. click pe zonă nowcasting -> popup menționează nowcasting;
4. panoul lateral listează toate alertele;
5. nu apare undefined/null;
6. textul complet ANM nu apare în popup.
```

---

# 3. Temperatura curentă din API ANM

Ideea este bună, dar trebuie implementată ca informație separată și clar etichetată.

Endpoint:

```text
https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii
```

Acest endpoint trebuie verificat live și salvat ca sample de debug, pentru că trebuie să vedem schema exactă a JSON-ului.

## 3.1. Nu folosi temperatura curentă ca istoric

Temperatura curentă este informație live. Nu trebuie afișată ca și cum ar aparține datei istorice selectate.

Regulă:

```text
Dacă data selectată este azi / latest_date:
  afișează „Starea vremii curente în județ”.

Dacă data selectată este istorică:
  ascunde secțiunea sau afișează discret:
  „Observațiile meteo curente nu se aplică datei istorice selectate.”
```

## 3.2. Fetch și cache în scraper

Nu face frontend-ul dependent direct de API-ul ANM, pentru că pot apărea probleme CORS / disponibilitate / schimbare schemă.

În `src/scraper.py`, adaugă un fetch pentru:

```text
https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii
```

Salvează rezultatul normalizat în:

```text
public/data/current_weather.json
```

Structură dorită:

```json
{
  "fetched_at_utc": "...",
  "source": "meteoromania.ro",
  "stations": [
    {
      "station_name": "Cluj-Napoca",
      "county_name": "Cluj",
      "temperature_c": 31.2,
      "weather": "...",
      "humidity": 40,
      "wind": "...",
      "raw": {}
    }
  ],
  "by_county": {
    "Cluj": [
      {
        "station_name": "Cluj-Napoca",
        "temperature_c": 31.2,
        "weather": "..."
      }
    ]
  }
}
```

Dacă schema API-ului este diferită, fă mai întâi un inspector robust care loghează câmpurile disponibile.

## 3.3. Nu bloca scraperul dacă API-ul meteo pică

Dacă fetch-ul pentru `starea-vremii` eșuează:

* scraperul trebuie să continue;
* păstrează ultimul `current_weather.json`, dacă există;
* loghează warning;
* nu opri actualizarea alertelor.

## 3.4. UI în panoul județului

În panoul lateral, sub alertele active, adaugă:

```text
Starea vremii acum în județ
Actualizat: ...

Stații ANM:
- Cluj-Napoca: 31°C, senin
- Dej: 30°C
- Vlădeasa: 22°C
```

Dacă nu există stații pentru județ:

```text
Nu există observații curente disponibile pentru acest județ.
```

Dacă data selectată este istorică:

```text
Observațiile meteo curente sunt disponibile doar pentru ziua curentă.
```

## 3.5. Test temperatură curentă

Testează:

```text
1. current_weather.json este generat;
2. are fetched_at_utc;
3. conține stații;
4. stațiile sunt grupate pe județ;
5. panoul județului afișează temperaturile pentru ziua curentă;
6. pentru o zi istorică nu le afișează ca date istorice;
7. dacă API-ul pică, scraperul nu se oprește.
```

---

# 4. Test local complet

Rulează:

```powershell
cd C:\Users\mariu\Date\_meteoalert
python src\test_scraper.py
python src\scraper.py
cd public
python -m http.server 8000
```

Testează:

```text
1. calendar istoric include zile cu nowcasting arhivat;
2. nowcasting apare pe hartă pentru zile istorice cu nowcasting;
3. selectorul de istoric are doar județe reale;
4. popup județ este informativ;
5. panoul lateral listează toate alertele;
6. current_weather.json există;
7. panoul județului afișează temperatura curentă doar pentru latest/today;
8. nu apar undefined/null.
```

---

# 5. Commit și deploy

Dacă toate testele trec:

```powershell
cd C:\Users\mariu\Date\_meteoalert
git status
git add .
git commit -m "Archive nowcasting and improve county detail popups"
git push
gh workflow run scrape-anm.yml
gh run watch
```

După deploy, verifică public:

```text
https://mariusbudileanu.github.io/date-meteo/?v=nowcasting-popup-weather-1
```

---

# 6. Raport final obligatoriu

Răspunde cu:

```text
REZUMAT NOWCASTING ISTORIC + POPUP + STAREA VREMII

1. Fișiere modificate:
   - ...

2. Nowcasting istoric:
   - nowcasting salvat în GeoJSON zilnic: DA/NU
   - nowcasting inclus în index.json: DA/NU
   - nowcasting vizibil în calendar istoric: DA/NU
   - nowcasting arhivat CSV: DA/NU
   - nowcasting afișabil pe hartă pentru date trecute: DA/NU
   - selector istoric fără zone nowcasting ciudate: DA/NU

3. Popup / panou:
   - popup afișează cod: DA/NU
   - popup afișează fenomen: DA/NU
   - popup afișează interval: DA/NU
   - popup afișează număr alerte: DA/NU
   - panoul lateral listează toate alertele: DA/NU
   - panoul lateral separă General / Nowcasting: DA/NU
   - fără undefined/null: DA/NU

4. Starea vremii:
   - endpoint ANM verificat: DA/NU
   - current_weather.json generat: DA/NU
   - stații grupate pe județ: DA/NU
   - temperaturi afișate în panoul județului: DA/NU
   - temperaturile nu sunt afișate greșit pentru date istorice: DA/NU
   - scraperul nu pică dacă endpointul meteo e indisponibil: DA/NU

5. Teste:
   - test_scraper.py: trecut/picat
   - scraper.py: trecut/picat
   - test local browser: trecut/picat
   - workflow GitHub: success/fail

6. Public:
   - URL verificat:
   - nowcasting istoric public: DA/NU
   - popup informativ public: DA/NU
   - starea vremii public: DA/NU

7. Probleme rămase:
   - ...
```
