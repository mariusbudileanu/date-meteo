# MeteoAlertRO — Context, evoluție și stare curentă

## 1. Context general

**MeteoAlertRO** este un proiect de colectare, arhivare și vizualizare a avertizărilor meteorologice publicate de Administrația Națională de Meteorologie, cu scopul de a construi în timp o arhivă interactivă a codurilor meteo pentru România.

Pagina publică a proiectului este:

```text
https://mariusbudileanu.github.io/date-meteo/
```

Repository-ul local este:

```text
C:\Users\mariu\Date\_meteoalert
```

Obiectivul proiectului este dublu:

1. afișarea cât mai clară a avertizărilor meteo active;
2. arhivarea în timp a avertizărilor, astfel încât utilizatorul să poată reveni la zile trecute și să vadă situația de atunci.

Proiectul nu este doar o hartă live. Trebuie să devină o aplicație de tip dashboard, cu istoric, filtre, hărți interactive și separare clară între avertizări generale și nowcasting.

---

## 2. Sursele de date utilizate

Au fost identificate și utilizate endpoint-urile ANM corecte:

```text
https://www.meteoromania.ro/avertizari-xml.php
```

pentru avertizările generale ANM și:

```text
https://www.meteoromania.ro/avertizari-nowcasting-xml.php
```

pentru avertizările nowcasting.

Pentru observații meteo curente a fost propus și endpoint-ul:

```text
https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii
```

Acesta poate fi folosit pentru afișarea temperaturii curente în panoul județului selectat, dar nu trebuie confundat cu datele istorice. Temperatura curentă este o informație live și trebuie afișată doar pentru data curentă sau pentru ultimele alerte.

---

## 3. Structura reală a XML-ului ANM

În timpul lucrului a devenit clar că XML-ul ANM nu trebuie tratat simplist.

Structura generală este:

```xml
<avertizari>
  <avertizare ...>
    <judet ... coordGis="MULTIPOLYGON (...)" />
  </avertizare>
</avertizari>
```

Elementul logic important este:

```text
<avertizare>
```

Acesta reprezintă o avertizare ANM / un mesaj ANM.

Geometria nu este stocată într-un tag separat, ci în atributul:

```text
coordGis
```

de pe elemente de tip:

```text
<judet>
<zona>
```

Geometriile sunt în format WKT și sunt în sistemul EPSG:3857. Pentru afișarea în Leaflet trebuie transformate în EPSG:4326.

Diferența conceptuală esențială este:

```text
Avertizare ANM = mesaj logic / alert_id
Zonă afectată = județ, zonă sau poligon / feature
```

Această diferență este importantă pentru că o singură avertizare poate avea multe geometrii, iar un județ poate fi afectat de mai multe avertizări în aceeași zi.

---

## 4. Probleme inițiale rezolvate

### 4.1. Corectarea endpoint-urilor ANM

Inițial au fost discutate endpoint-uri mai vechi sau greșite. Ulterior au fost stabilite endpoint-urile corecte:

```text
https://www.meteoromania.ro/avertizari-xml.php
https://www.meteoromania.ro/avertizari-nowcasting-xml.php
```

### 4.2. Transformarea corectă a geometriei

A fost clarificat faptul că `coordGis` vine în EPSG:3857, nu direct în coordonate geografice. Transformarea corectă este:

```text
EPSG:3857 → EPSG:4326
```

Această corecție a permis afișarea corectă a geometriei pe hartă.

### 4.3. GitHub Pages și deploy

A existat o problemă inițială în care workflow-ul rula scraperul și făcea commit la date, dar nu publica efectiv pagina nouă pe GitHub Pages.

Workflow-ul a fost ulterior modificat astfel încât să includă și etapa de deploy Pages.

### 4.4. Tema vizuală

A fost aleasă direcția vizuală:

```text
Storm Glass Dark
```

Aceasta presupune o interfață dark, modernă, de tip dashboard operațional, cu fundal navy/slate, carduri moderne, accente cyan/blue și culori clare pentru codurile meteo.

---

## 5. Direcția actuală de produs

Aplicația trebuie să funcționeze ca un dashboard modern pentru avertizări meteo.

Direcția stabilită este:

```text
1. Hartă principală — cod maxim pe județ
2. Hărți / moduri separate pe avertizare
3. Filtru pe fenomen
4. Filtru pe cod
5. Separare General ANM / Nowcasting
6. Calendar istoric persistent
7. Panou lateral pentru județ selectat
8. Carduri de avertizare active
9. Arhivă pe județe
10. Descărcări CSV
```

Principiul important este că **harta principală poate afișa codul maxim**, dar datele brute nu trebuie reduse la cod maxim. Toate alertele trebuie păstrate în GeoJSON și în metadata, pentru ca utilizatorul să poată filtra, compara și izola alerte.

---

## 6. Problema majoră identificată la hărți

Într-o etapă de debug serios s-a constatat că site-ul afișa practic doar codul de temperatură, deși pe pagina ANM existau și alte avertizări, inclusiv instabilitate atmosferică / averse / vijelii.

Problema principală nu era în UI, ci în modelul de date generat de scraper.

Funcția:

```text
_winner_features()
```

păstra doar feature-ul „câștigător” pentru fiecare județ, adică alerta cu codul maxim. Astfel, dacă un județ avea:

```text
Cod roșu — caniculă
Cod galben — ploi / vijelii
```

GeoJSON-ul zilnic păstra doar codul roșu. Codul galben exista eventual în metadata, dar nu mai exista ca feature desenabil pe hartă.

Consecința directă:

```text
Frontend-ul nu avea ce să filtreze.
```

Chiar dacă existau butoane pentru fenomen, cod sau avertizare, acestea nu puteau afișa alerta de ploi dacă alerta fusese eliminată deja din `features`.

Soluția stabilită:

```text
GeoJSON-ul zilnic trebuie să păstreze toate feature-urile active.
Codul maxim trebuie calculat separat, în metadata sau în frontend.
```

---

## 7. Problema intervalelor ANM

A doua problemă majoră a fost legată de câmpul:

```text
intervalul="conform textelor;"
```

Unele avertizări ANM nu au intervalul real în atributul XML, ci în textul HTML din câmpul `mesaj`.

Exemplu de comportament greșit identificat:

```text
Text public: 30 iunie, ora 12 – 30 iunie, ora 23
dataExpirarii XML: 2026-07-30T23:00
```

Scraperul folosea `dataExpirarii` ca fallback și genera zile false până la 30 iulie.

Soluția stabilită:

```text
1. Dacă intervalul este explicit în textul mesajului, acesta are prioritate.
2. dataAparitiei/dataExpirarii sunt fallback, nu sursa principală.
3. Pentru intervalul="conform textelor", scraperul trebuie să parseze textul mesajului.
4. Mesajele cu mai multe secțiuni COD GALBEN / COD PORTOCALIU / COD ROȘU trebuie împărțite logic pe secțiuni.
```

---

## 8. Starea nowcasting-ului

Nowcasting-ul trebuie tratat ca sursă separată de avertizările generale.

În rulările de debug, endpoint-ul nowcasting a returnat:

```xml
<avertizariNowcasting/>
```

adică 0 avertizări nowcasting live la acel moment.

Acest lucru nu este o eroare. Totuși, aplicația trebuie să fie pregătită pentru momentul în care nowcasting-ul apare.

Cerința actuală este:

```text
Nowcasting-ul trebuie arhivat și afișat și pentru date istorice.
```

Asta înseamnă că, atunci când apare o alertă nowcasting și este colectată, ea trebuie:

```text
1. salvată în GeoJSON-ul zilei respective;
2. inclusă în index.json;
3. inclusă în arhivă CSV;
4. vizibilă în calendar;
5. afișabilă ulterior, chiar dacă endpoint-ul live nu o mai returnează.
```

Nowcasting-ul trebuie să aibă proprietăți clare:

```text
source = nowcasting
alert_type = nowcasting
county_name = județ real
zone_name = zona specială
```

Zonele speciale de tip „Alba Munte 2” nu trebuie să apară în selectorul principal de istoric pe județ. Selectorul principal trebuie să conțină doar județe reale.

---

## 9. Calendarul istoric

A existat o problemă în care calendarul părea să afișeze doar datele din rularea curentă, nu și datele istorice deja arhivate.

Cerința stabilită:

```text
Atâta timp cât există GeoJSON zilnic sau arhivă pentru o dată, data trebuie să rămână vizibilă în calendar.
```

Soluția corectă:

```text
index.json trebuie reconstruit din toate fișierele public/data/YYYY-MM-DD.geojson existente, nu doar din rularea curentă.
```

Această problemă a fost raportată ca rezolvată pentru calendarul istoric general.

Rămâne însă de extins aceeași logică și pentru nowcasting istoric.

---

## 10. Tooltip / popup pe hartă

O problemă rămasă este că, la click pe un județ, popup-ul afișează doar numele județului.

Acest lucru nu este suficient.

Popup-ul trebuie să afișeze, într-o formă scurtă:

```text
Județ
Număr avertizări active
Cod maxim
Fenomene
Interval / valabilitate
```

Pentru un județ cu o singură alertă:

```text
Cluj
1 avertizare activă
Cod: Roșu
Fenomen: caniculă / temperaturi extreme
Valabil până la: 1 iulie, ora 10
```

Pentru un județ cu alerte multiple:

```text
Cluj
2 avertizări active
Cod maxim: Roșu
Fenomene: caniculă, ploi/vijelii
Click pentru detalii în panoul lateral
```

Pentru nowcasting:

```text
Alba - zona montană
Nowcasting
Cod: Galben
Fenomen: averse / descărcări electrice
Valabil până la: ...
```

Popup-ul trebuie să rămână scurt. Textul complet ANM trebuie afișat doar în cardurile de avertizare, în `<details>`.

---

## 11. Panoul lateral pentru județ selectat

Panoul lateral trebuie să fie locul principal pentru detalii.

Când se selectează un județ, panoul trebuie să listeze toate alertele active pentru acel județ, nu doar prima alertă.

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

Dacă există nowcasting, acesta trebuie afișat separat:

```text
Nowcasting activ:
1. Cod galben — averse / descărcări electrice
   Zonă: Alba - zona montană
   Interval: ...
```

---

## 12. Starea vremii curente

A fost propusă integrarea temperaturii curente din endpoint-ul ANM:

```text
https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii
```

Ideea este utilă, dar trebuie implementată separat de avertizări.

Regulă:

```text
Temperatura curentă se afișează doar pentru data curentă sau pentru latest.
Pentru date istorice, nu trebuie afișată ca și cum ar aparține acelei date.
```

Locul recomandat pentru afișare este panoul lateral al județului selectat, sub alerte:

```text
Starea vremii acum în județ
Actualizat: ...

Stații ANM:
- Cluj-Napoca: 31°C
- Dej: 30°C
- Vlădeasa: 22°C
```

Dacă API-ul nu răspunde, scraperul nu trebuie să eșueze. Trebuie doar să logheze un warning și să continue actualizarea avertizărilor.

---

## 13. Elemente deja realizate

Până acum au fost realizate sau începute următoarele:

```text
1. Stabilirea endpoint-urilor ANM corecte.
2. Parsarea XML-ului general ANM.
3. Transformarea coordGis din EPSG:3857 în EPSG:4326.
4. Generarea de GeoJSON-uri zilnice.
5. Generarea latest.geojson.
6. Generarea index.json.
7. Publicarea site-ului prin GitHub Pages.
8. Corectarea workflow-ului GitHub Actions pentru deploy.
9. Introducerea unei interfețe de tip dashboard.
10. Alegerea direcției vizuale Storm Glass Dark.
11. Adăugarea filtrelor pe sursă, fenomen, cod și mod hartă.
12. Adăugarea conceptului de calendar istoric.
13. Diagnosticarea problemei cu alertele suprapuse.
14. Identificarea problemei `_winner_features()`.
15. Identificarea problemei cu intervalele `conform textelor`.
16. Corectarea, cel puțin parțială, a calendarului istoric general.
```

---

## 14. Probleme importante întâlnite

### 14.1. Endpoint nowcasting gol

În unele rulări live, endpoint-ul nowcasting a returnat 0 avertizări. Nu este eroare, dar trebuie test fixture / demo pentru a valida afișarea nowcasting.

### 14.2. GeoJSON redus la cod maxim

Cea mai mare problemă tehnică a fost eliminarea alertelor suprapuse din `features`.

### 14.3. Intervale greșite

Unele mesaje ANM au intervale reale doar în textul mesajului. Folosirea directă a `dataExpirarii` poate genera zile false.

### 14.4. Calendar incomplet

Calendarul a pierdut inițial date istorice, pentru că indexul nu era reconstruit din toate fișierele zilnice existente.

### 14.5. Tooltip insuficient

Tooltip-ul / popup-ul hărții încă afișează prea puține informații.

### 14.6. Nowcasting istoric incomplet

Nowcasting-ul trebuie arhivat și vizibil în trecut, nu doar tratat ca strat live.

---

## 15. Pașii următori prioritari

În acest moment, nu trebuie continuat redesign-ul până când nu sunt rezolvate complet problemele funcționale.

Prioritatea este:

### Pasul 1 — Nowcasting istoric

Nowcasting-ul trebuie:

```text
- salvat în GeoJSON zilnic;
- inclus în index.json;
- vizibil în calendar;
- afișabil pe hartă pentru date trecute;
- separat clar de avertizările generale;
- arhivat fără să polueze selectorul de județe cu zone speciale.
```

### Pasul 2 — Tooltip / popup real

Popup-ul trebuie să afișeze:

```text
- cod;
- fenomen;
- interval;
- număr alerte;
- cod maxim;
- sursă;
- indicator nowcasting, dacă este cazul.
```

### Pasul 3 — Panou lateral complet

Panoul lateral trebuie să listeze toate alertele active pentru județul selectat, inclusiv suprapunerile.

### Pasul 4 — Starea vremii curente

Integrarea temperaturii curente este utilă, dar trebuie să fie clar separată de istoricul avertizărilor.

### Pasul 5 — Dashboard polish

Abia după ce datele, harta, popup-ul, nowcasting-ul și calendarul funcționează corect, se poate continua cu îmbunătățirea vizuală a dashboardului.

---

## 16. Principiul de bază pentru dezvoltare

Nu trebuie să mai rezolvăm probleme de date prin UI.

Regula principală:

```text
Toate alertele trebuie păstrate în date.
Frontend-ul decide cum le agregă, filtrează sau afișează.
```

Asta înseamnă:

```text
GeoJSON = toate alertele
metadata = sumar / index / cod maxim
frontend = moduri de vizualizare
```

Nu invers.

Dacă o alertă este eliminată din GeoJSON, ea nu mai poate fi afișată, filtrată sau comparată.

---

## 17. Concluzie

MeteoAlertRO a evoluat de la o simplă hartă de avertizări la un dashboard meteo interactiv, cu arhivare în timp. Problemele majore descoperite au fost legate de modelul de date, nu doar de interfață.

Cele mai importante lecții sunt:

```text
1. Avertizarea ANM și zona afectată sunt concepte diferite.
2. Codul maxim este un mod de afișare, nu un criteriu de eliminare a datelor.
3. Mesajele ANM pot conține mai multe coduri și intervale interne.
4. Nowcasting-ul trebuie arhivat, nu tratat doar ca live.
5. Calendarul trebuie să fie persistent și să reflecte arhiva.
6. Tooltip-ul și panoul lateral trebuie să explice harta.
7. Temperatura curentă poate completa dashboardul, dar nu trebuie confundată cu istoricul.
```

Următoarea etapă trebuie să se concentreze pe:

```text
1. nowcasting istoric;
2. popup / tooltip informativ;
3. panou lateral complet;
4. starea vremii curente;
5. apoi polish vizual și UX.
```
