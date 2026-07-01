# MeteoAlertRO — Specificație UI/UX pentru modernizarea dashboardului

## 1. Context

MeteoAlertRO este un dashboard pentru colectarea, arhivarea și vizualizarea avertizărilor meteorologice ANM. Aplicația are deja o structură funcțională de bază:

* hartă interactivă;
* calendar;
* filtre;
* carduri de avertizări;
* istoric;
* descărcări CSV;
* separare conceptuală între avertizări generale și nowcasting;
* arhivare zilnică a datelor.

Totuși, dashboardul trebuie dus într-o direcție vizuală și funcțională mai matură. Interfața trebuie să devină mai clară, mai compactă, mai modernă și mai orientată spre explorarea geospațială a alertelor.

Obiectivul acestei etape este modernizarea semnificativă a dashboardului, fără a pierde funcționalitatea deja construită.

---

## 2. Principiul central al redesignului

Dashboardul trebuie să arate și să se comporte ca o aplicație modernă de monitorizare geospațială, nu ca o pagină HTML cu hartă și tabele.

Direcția vizuală:

```text
Dark Mode Natural
Geospatial Intelligence Dashboard
Bento UI
Glassmorphism discret
Hartă centrală
Date clare
Interacțiuni rapide
```

Dashboardul trebuie să răspundă imediat la întrebările:

```text
Ce coduri sunt active?
Unde sunt active?
Care este codul maxim?
Ce fenomene sunt vizate?
Există alerte suprapuse?
Există nowcasting?
Ce s-a întâmplat în trecut?
Ce pot descărca?
```

---

## 3. Paleta de culori — estetică 2027 pentru date geospațiale

### 3.1. Direcție generală

Cromatica actuală trebuie să evolueze de la culori web-safe simple la o paletă mai sofisticată, potrivită pentru o aplicație de date geospațiale și meteorologice.

Trebuie evitat contrastul dur alb/negru. În locul acestuia se vor folosi tonuri deep, slate, navy și accente neon-matte.

Tema trebuie să reducă oboseala ochilor și să pună harta în prim-plan.

---

### 3.2. Variabile CSS recomandate

În `public/css/style.css`, definește un sistem coerent de variabile:

```css
:root {
  /* Background */
  --color-bg-main: #0F172A;
  --color-bg-alt: #111827;

  /* Surfaces */
  --color-surface: rgba(30, 41, 59, 0.72);
  --color-surface-solid: #1E293B;
  --color-surface-soft: rgba(15, 23, 42, 0.78);
  --color-surface-hover: rgba(51, 65, 85, 0.82);

  /* Borders */
  --color-border-soft: #334155;
  --color-border-strong: #475569;

  /* Text */
  --color-text-main: #F8FAFC;
  --color-text-secondary: #94A3B8;
  --color-text-muted: #64748B;

  /* Accents */
  --color-accent-cyan: #38BDF8;
  --color-accent-blue: #60A5FA;
  --color-accent-teal: #2DD4BF;
  --color-accent-violet: #A78BFA;

  /* Alert colors */
  --alert-yellow: #FBBF24;
  --alert-orange: #F97316;
  --alert-red: #EF4444;
  --alert-red-strong: #DC2626;
  --alert-neutral: #334155;

  /* Map */
  --map-bg: #020617;
  --map-boundary: #475569;
  --map-boundary-soft: rgba(148, 163, 184, 0.35);

  /* Effects */
  --shadow-soft: 0 18px 60px rgba(0, 0, 0, 0.35);
  --shadow-card: 0 12px 40px rgba(0, 0, 0, 0.28);
  --blur-glass: blur(18px);

  /* Radius */
  --radius-xl: 28px;
  --radius-lg: 22px;
  --radius-md: 16px;
  --radius-sm: 10px;

  /* Spacing */
  --space-xs: 0.35rem;
  --space-sm: 0.65rem;
  --space-md: 1rem;
  --space-lg: 1.5rem;
  --space-xl: 2rem;
}
```

---

### 3.3. Culori pentru codurile meteo

Culorile trebuie să rămână recognoscibile, dar să fie mai elegante și mai puțin stridente.

| Cod                  |    Culoare |       Hex | Utilizare                          |
| -------------------- | ---------: | --------: | ---------------------------------- |
| Galben               |  Amber 400 | `#FBBF24` | atenționare                        |
| Portocaliu           | Orange 500 | `#F97316` | avertizare severă                  |
| Roșu                 |    Red 500 | `#EF4444` | urgență                            |
| Roșu puternic        |    Red 600 | `#DC2626` | accent punctual, nu suprafețe mari |
| Neutru / fără alertă |  Slate 700 | `#334155` | fundal, contur, zone neafectate    |

Regulă importantă:

```text
Codul verde nu trebuie folosit ca alertă activă pentru zile fără date.
```

Dacă o zi nu are alerte, harta trebuie să rămână neutră, fără geometrii verzi care sugerează existența unei stări meteo active.

---

## 4. Tipografie

### 4.1. Font principal

Folosește un font geometric, modern, foarte lizibil:

```css
font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Opțional, se poate folosi:

```text
Plus Jakarta Sans
```

pentru titluri și zone de dashboard.

### 4.2. Font pentru date tehnice

Pentru valori numerice, ore, intervale, coduri și date tehnice, folosește un font monospace modern:

```css
font-family: "JetBrains Mono", "Fira Code", "Space Mono", monospace;
```

Dacă nu se încarcă un font extern, folosește fallback:

```css
font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
```

### 4.3. Ierarhie tipografică

Definește ierarhia:

```css
.dashboard-title {
  font-size: clamp(1.35rem, 2vw, 2rem);
  font-weight: 750;
  letter-spacing: -0.035em;
}

.section-title {
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.kpi-value {
  font-size: clamp(1.3rem, 2vw, 2.2rem);
  font-weight: 800;
  letter-spacing: -0.045em;
}

.kpi-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-text-secondary);
}

.meta-text {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

.data-text {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.82rem;
}
```

---

## 5. Arhitectura UI/UX

### 5.1. Obiectiv layout

Trebuie redusă oboseala de scroll. Informația esențială trebuie să fie vizibilă above the fold.

Structura actuală liniară trebuie transformată într-un dashboard de tip:

```text
sticky header
bento grid
hartă dominantă
panou de control lateral
panouri plutitoare peste hartă
secțiuni secundare în taburi sau mai jos
```

---

### 5.2. Header compact și sticky

Headerul trebuie să fie mai compact și să rămână vizibil la scroll.

Structură recomandată:

```text
[MeteoAlertRO] [Avertizări meteo ANM pe hartă]        [Ultima actualizare: ...]
```

Elemente:

* titlu scurt;
* subtitlu scurt;
* ultima actualizare;
* link discret către meteoromania.ro;
* fără blocuri mari de text în primul ecran.

CSS recomandat:

```css
.app-header {
  position: sticky;
  top: 0;
  z-index: 1000;
  backdrop-filter: var(--blur-glass);
  background: rgba(15, 23, 42, 0.82);
  border-bottom: 1px solid var(--color-border-soft);
}

.app-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  min-height: 58px;
}
```

---

### 5.3. Structură Bento Grid

Layout recomandat pentru desktop:

```text
┌─────────────────────────────────────────────────────────────┐
│ Sticky Header                                                │
├───────────────┬─────────────────────────────────────────────┤
│ Control Center│ Harta principală                            │
│ Calendar      │                                             │
│ Filtre        │  Floating KPI summary                       │
│ Moduri hartă  │  Floating selected county                   │
│               │                                             │
├───────────────┴─────────────────────────────────────────────┤
│ Avertizări active / Comparare / Nowcasting                  │
├─────────────────────────────────────────────────────────────┤
│ Analiză date / Istoric / Descărcări CSV                     │
└─────────────────────────────────────────────────────────────┘
```

CSS orientativ:

```css
.dashboard-shell {
  display: grid;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  gap: var(--space-lg);
  padding: var(--space-lg);
}

.control-sidebar {
  position: sticky;
  top: 82px;
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.map-stage {
  position: relative;
  min-height: calc(100vh - 130px);
  border-radius: var(--radius-xl);
  overflow: hidden;
  background: var(--map-bg);
  border: 1px solid var(--color-border-soft);
  box-shadow: var(--shadow-soft);
}
```

Pe mobil / tabletă:

```css
@media (max-width: 980px) {
  .dashboard-shell {
    grid-template-columns: 1fr;
  }

  .control-sidebar {
    position: relative;
    top: auto;
  }

  .map-stage {
    min-height: 70vh;
  }
}
```

---

## 6. Control Center

### 6.1. Rol

Control Center-ul trebuie să fie locul unde utilizatorul controlează:

* data;
* sursa;
* fenomenul;
* codul;
* modul hărții;
* resetarea filtrelor;
* afișarea nowcasting;
* afișarea doar a județelor cu alerte multiple.

### 6.2. Elemente obligatorii

```text
Calendar / dată selectată
Buton Ultimele alerte
Sursă: General / Nowcasting / General + Nowcasting
Fenomen: Toate / Caniculă / Ploi / Vijelii / Ninsori / Viscol / Ceață / Polei / Altele
Cod: Toate / Galben / Portocaliu / Roșu
Mod hartă: Cod maxim / Pe fenomen / Pe avertizare / Compară
Toggle: Doar județe cu alerte multiple
Reset filtre
```

### 6.3. Stil

Control Center-ul trebuie să fie compact, cu butoane tip segmented control.

```css
.segmented-control {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid var(--color-border-soft);
}

.segmented-control button {
  border: 0;
  border-radius: 999px;
  padding: 0.55rem 0.8rem;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.segmented-control button.is-active {
  background: rgba(56, 189, 248, 0.16);
  color: var(--color-text-main);
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.45);
}
```

---

## 7. Harta — piesa centrală

### 7.1. Harta trebuie să ocupe spațiul principal

Harta trebuie să ocupe minimum 60–70% din spațiul vizibil inițial pe desktop.

Nu trebuie împinsă sub multe carduri, texte sau secțiuni secundare.

---

### 7.2. Basemap dark minimalist

Se recomandă renunțarea la OpenStreetMap Standard ca fundal principal.

Direcții acceptabile:

```text
CartoDB Dark Matter
MapTiler Dark
Mapbox Dark
Stadia Alidade Smooth Dark
Stamen Toner Dark, dacă este disponibil prin endpoint compatibil
```

Dacă se folosește un tile provider extern, trebuie verificat:

* termenii de utilizare;
* stabilitatea endpointului;
* dacă are nevoie de API key;
* dacă poate fi folosit pe GitHub Pages.

Variantă simplă fără chei API:

```javascript
L.tileLayer(
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  {
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    maxZoom: 19
  }
)
```

---

### 7.3. Stilizarea poligoanelor ANM

Poligoanele nu trebuie colorate solid opac. Folosește:

* fill translucid;
* stroke mai intens;
* hover cu stroke mai gros;
* opacitate adaptată codului;
* tranziții fine.

Exemplu:

```javascript
const ALERT_STYLES = {
  1: {
    color: "#FBBF24",
    fillColor: "#FBBF24",
    fillOpacity: 0.24,
    weight: 1.4
  },
  2: {
    color: "#F97316",
    fillColor: "#F97316",
    fillOpacity: 0.28,
    weight: 1.6
  },
  3: {
    color: "#EF4444",
    fillColor: "#EF4444",
    fillOpacity: 0.32,
    weight: 1.8
  }
};
```

Hover:

```javascript
layer.on("mouseover", () => {
  layer.setStyle({
    weight: 3,
    fillOpacity: Math.min(baseFillOpacity + 0.12, 0.48)
  });
});

layer.on("mouseout", () => {
  layer.setStyle(originalStyle);
});
```

---

### 7.4. Suprapuneri

Pentru județe cu mai multe alerte active, nu este suficient să fie afișat codul maxim.

Trebuie să existe indicator vizual:

```text
badge 2+
contur dublu
contur punctat
pattern / hașură
```

Soluția recomandată pentru prima etapă:

```text
fill = cod maxim
stroke = cod maxim
badge numeric = număr alerte active
```

Soluție avansată:

```text
pattern SVG pentru al doilea fenomen
hașuri pentru suprapuneri
```

CSS / SVG pattern orientativ:

```javascript
function createStripePattern(color) {
  const pattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
  pattern.setAttribute("patternUnits", "userSpaceOnUse");
  pattern.setAttribute("width", "8");
  pattern.setAttribute("height", "8");
  pattern.setAttribute("patternTransform", "rotate(45)");

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", "0");
  line.setAttribute("y1", "0");
  line.setAttribute("x2", "0");
  line.setAttribute("y2", "8");
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("opacity", "0.65");

  pattern.appendChild(line);
  return pattern;
}
```

Această etapă poate fi făcută ulterior. Pentru prima modernizare, badge-ul este obligatoriu, hașura este recomandată.

---

### 7.5. Tooltips moderne

Tooltip-ul nu trebuie să fie doar text simplu.

Trebuie să fie un mini-card.

Pentru o alertă:

```text
Cluj
Cod roșu
Caniculă / temperaturi extreme
Valabil până la 1 iulie, ora 10
```

Pentru alerte multiple:

```text
Cluj
2 avertizări active
Cod maxim: Roșu
Fenomene: caniculă, ploi/vijelii
```

Pentru nowcasting:

```text
Alba - zona montană
Nowcasting · Cod galben
Averse / descărcări electrice
Valabil până la ...
```

CSS:

```css
.leaflet-popup-content-wrapper {
  background: rgba(15, 23, 42, 0.92);
  color: var(--color-text-main);
  border: 1px solid var(--color-border-soft);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(14px);
}

.map-tooltip-card {
  min-width: 190px;
}

.map-tooltip-title {
  font-weight: 750;
  font-size: 0.95rem;
}

.map-tooltip-meta {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}

.map-tooltip-code {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.4rem;
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}
```

---

### 7.6. Animații

Adaugă tranziții fine, fără efecte excesive.

```css
.leaflet-interactive {
  transition:
    fill-opacity 180ms ease,
    stroke-width 180ms ease,
    opacity 180ms ease;
}

.dashboard-card,
.kpi-card,
.alert-card {
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    background 180ms ease,
    box-shadow 180ms ease;
}

.dashboard-card:hover,
.alert-card:hover {
  transform: translateY(-1px);
  border-color: rgba(56, 189, 248, 0.35);
}
```

Respectă preferințele de accesibilitate:

```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation: none !important;
    transition: none !important;
  }
}
```

---

## 8. Floating panels peste hartă

### 8.1. Rezumat zi selectată

În loc să ocupe mult spațiu deasupra hărții, rezumatul poate fi afișat ca panel translucid peste hartă.

Poziție recomandată:

```text
colț stânga sus sau stânga jos
```

Conținut:

```text
Data selectată
Avertizări ANM
Nowcasting
Cod maxim
Fenomene active
```

CSS:

```css
.map-floating-summary {
  position: absolute;
  left: 18px;
  top: 18px;
  z-index: 500;
  width: min(360px, calc(100% - 36px));
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-card);
  padding: var(--space-md);
}
```

---

### 8.2. Județ selectat

Panoul pentru județ selectat poate pluti în dreapta hărții.

Poziție recomandată:

```text
colț dreapta sus sau dreapta jos
```

Trebuie să fie scrollabil intern dacă sunt multe alerte.

```css
.map-floating-county {
  position: absolute;
  right: 18px;
  top: 18px;
  z-index: 500;
  width: min(390px, calc(100% - 36px));
  max-height: calc(100% - 36px);
  overflow: auto;
  background: rgba(15, 23, 42, 0.76);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-card);
}
```

Pe ecrane mici, panoul trebuie să devină sub hartă, nu să acopere complet harta.

---

## 9. Carduri KPI

Cardurile KPI trebuie să fie moderne și compacte.

Exemplu conținut:

```text
Data selectată
1 iulie 2026

Avertizări ANM
4

Nowcasting
2

Cod maxim
Roșu

Fenomene
Caniculă · Ploi/vijelii
```

Stil:

```css
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-md);
}

.kpi-card {
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.82), rgba(15, 23, 42, 0.72));
  border: 1px solid var(--color-border-soft);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-card);
}
```

Pe mobil:

```css
@media (max-width: 980px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
```

---

## 10. Carduri de avertizare

### 10.1. Rol

Cardurile de avertizare trebuie să fie și informaționale, și interactive.

Fiecare card trebuie să poată controla harta.

Conținut:

```text
Cod maxim
Fenomen principal
Interval
Zone afectate
Sursa
Afișează / Izolează / Ascunde
Text complet ANM în details
```

### 10.2. Stil

```css
.alert-card {
  background: rgba(30, 41, 59, 0.72);
  border: 1px solid var(--color-border-soft);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-card);
}

.alert-card[data-severity="yellow"] {
  border-left: 4px solid var(--alert-yellow);
}

.alert-card[data-severity="orange"] {
  border-left: 4px solid var(--alert-orange);
}

.alert-card[data-severity="red"] {
  border-left: 4px solid var(--alert-red);
}
```

### 10.3. Butoane

```css
.action-button {
  border: 1px solid var(--color-border-soft);
  background: rgba(15, 23, 42, 0.58);
  color: var(--color-text-secondary);
  border-radius: 999px;
  padding: 0.45rem 0.75rem;
  font-size: 0.78rem;
  cursor: pointer;
}

.action-button:hover,
.action-button.is-active {
  color: var(--color-text-main);
  border-color: rgba(56, 189, 248, 0.55);
  background: rgba(56, 189, 248, 0.13);
}
```

---

## 11. Calendar modern

### 11.1. Calendarul trebuie să fie compact

Calendarul nu trebuie să domine dashboardul. Este un instrument de navigare, nu elementul principal.

### 11.2. Zile colorate

Reguli:

```text
Zi cu alertă generală: culoare după cod maxim
Zi cu nowcasting: badge NC
Zi cu general + nowcasting: culoare după cod maxim + badge NC
Zi cu arhivă fără GeoJSON: marcare discretă
Zi fără date: neutru
```

### 11.3. Tooltip calendar

La hover pe o zi:

```text
1 iulie 2026
4 avertizări ANM
2 nowcasting
Cod maxim: Roșu
Fenomene: caniculă, ploi/vijelii
```

---

## 12. Nowcasting

### 12.1. Nowcasting trebuie separat vizual

Nowcasting-ul nu trebuie să se confunde cu avertizările generale.

Stil recomandat:

```text
contur punctat
badge NC
opacitate ușor mai mică
etichetă clară în carduri
secțiune separată în panoul județului
```

### 12.2. Nowcasting istoric

Nowcasting-ul trebuie să fie vizibil și pentru date trecute, dacă a fost arhivat.

Regulă:

```text
Dacă o alertă nowcasting a fost colectată, ea trebuie să rămână vizibilă în calendar și în harta acelei zile.
```

### 12.3. Selector istoric

Selectorul principal pe județ trebuie să conțină doar județe reale.

Zonele nowcasting speciale apar doar în detalii, nu în dropdown.

---

## 13. Secțiunea „Analiză Date”

### 13.1. Istoric și descărcări CSV

Istoricul și descărcările CSV nu trebuie să domine primul ecran.

Soluție recomandată:

```text
tab 1: Harta Live / Zi selectată
tab 2: Analiză Date
tab 3: Descărcări
```

sau, mai simplu:

```text
secțiune amplasată sub dashboardul principal
```

### 13.2. Data Cards în loc de tabel simplu

În loc de tabel HTML simplu, fiecare lună poate deveni card.

Exemplu:

```text
Iunie 2026
42 avertizări arhivate
Cod maxim: Roșu
General: 38
Nowcasting: 4
[Descarcă CSV]
```

Stil:

```css
.data-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-md);
}

.data-card {
  background: rgba(30, 41, 59, 0.72);
  border: 1px solid var(--color-border-soft);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
}

.download-button {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border-radius: 999px;
  padding: 0.55rem 0.9rem;
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: var(--color-text-main);
}
```

---

## 14. Icoane și microinteracțiuni

Se pot folosi iconițe simple, de preferat SVG inline sau o librărie foarte mică.

Icoane recomandate:

```text
temperatură / caniculă: thermometer
ploi: cloud-rain
vijelii: cloud-lightning
vânt: wind
ninsoare: snowflake
ceață: haze
descărcare CSV: download
calendar: calendar
hartă: map
nowcasting: radio / activity
```

Nu introduce biblioteci grele doar pentru iconițe.

---

## 15. Responsive design

Dashboardul trebuie să funcționeze bine pe:

```text
desktop mare
laptop
tabletă
telefon
```

Reguli:

```text
Pe desktop: sidebar + hartă mare
Pe tabletă: control center deasupra hărții
Pe mobil: secțiuni stacked, hartă 70vh, panouri sub hartă
```

Pe mobil, floating panels nu trebuie să acopere harta complet. Ele trebuie să devină cards sub hartă sau bottom sheets.

---

## 16. Accesibilitate

### 16.1. Contrast

Toate textele trebuie să aibă contrast bun pe fundal dark.

### 16.2. Focus states

Butoanele și selectoarele trebuie să aibă focus vizibil.

```css
button:focus-visible,
a:focus-visible,
select:focus-visible {
  outline: 2px solid var(--color-accent-cyan);
  outline-offset: 3px;
}
```

### 16.3. Reduced motion

Respectă `prefers-reduced-motion`.

### 16.4. Nu transmite informație doar prin culoare

Codurile meteo trebuie să fie indicate și prin text / badge, nu doar prin culoare.

---

## 17. Performanță

### 17.1. Evită randări excesive

La schimbarea filtrelor:

```text
nu recrea toată aplicația
nu reîncărca inutil index.json
nu reîncărca latest.geojson dacă data selectată are GeoJSON propriu
```

### 17.2. Lazy rendering pentru secțiuni secundare

Secțiunile de istoric și descărcări pot fi randate doar când utilizatorul le deschide.

### 17.3. Mini-hărți

Dacă se implementează modul „Compară avertizările” cu mini-hărți multiple, limitează numărul inițial la 4.

Pentru mai multe:

```text
afișează carduri cu buton „Vezi pe hartă”
```

---

## 18. Ordinea recomandată de implementare

### Etapa 1 — CSS foundation

```text
1. introducere variabile CSS;
2. paletă nouă;
3. fonturi;
4. carduri glassmorphism;
5. header sticky;
6. butoane / controls moderne.
```

### Etapa 2 — Layout Bento

```text
1. refacere structură grid;
2. control center în sidebar;
3. hartă dominantă;
4. panouri floating;
5. secțiuni secundare mai jos.
```

### Etapa 3 — Hartă

```text
1. basemap dark;
2. stil poligoane translucid;
3. hover state;
4. popup mini-card;
5. badge alerte multiple;
6. animații fine.
```

### Etapa 4 — Carduri și interacțiuni

```text
1. carduri avertizări;
2. chips alerte afișate;
3. legendă interactivă;
4. data cards pentru CSV;
5. tabs pentru analiză / descărcări.
```

### Etapa 5 — Responsive și accesibilitate

```text
1. mobile layout;
2. focus states;
3. reduced motion;
4. contrast check;
5. test cu ecran îngust.
```

---

## 19. Teste obligatorii după modernizare

### 19.1. Test vizual

```text
1. Tema dark modernă este aplicată coerent.
2. Headerul este compact și sticky.
3. Harta ocupă spațiul principal.
4. Control center-ul este compact și clar.
5. Cardurile KPI sunt lizibile.
6. Panourile floating nu blochează harta.
7. Secțiunile de istoric/CSV nu domină primul ecran.
```

### 19.2. Test hartă

```text
1. Basemap dark se încarcă.
2. Poligoanele au fill translucid și stroke clar.
3. Hover-ul evidențiază județul.
4. Popup-ul este mini-card, nu text simplu.
5. Badge-ul pentru alerte multiple apare.
6. Zi fără alerte nu afișează geometrii verzi.
7. Nowcasting are stil diferit.
```

### 19.3. Test funcțional

```text
1. Calendarul istoric funcționează.
2. Selectarea unei date istorice încarcă GeoJSON-ul corect.
3. Filtrul pe fenomen funcționează.
4. Filtrul pe cod funcționează.
5. Modul Cod maxim funcționează.
6. Modul Pe avertizare funcționează.
7. Reset filtre funcționează.
8. Datele nowcasting istorice rămân vizibile.
```

### 19.4. Test responsive

```text
1. Desktop mare.
2. Laptop.
3. Tabletă.
4. Mobil.
5. Harta rămâne utilizabilă.
6. Floating panels nu acoperă complet harta.
```

---

## 20. Raport final cerut de la Codex

La finalul implementării, Codex trebuie să răspundă cu:

```text
REZUMAT MODERNIZARE DASHBOARD METEOALERTRO

1. Fișiere modificate:
   - ...

2. Paletă și tipografie:
   - variabile CSS noi: DA/NU
   - paletă dark deep: DA/NU
   - culori coduri modernizate: DA/NU
   - font principal modern: DA/NU
   - font monospace pentru date: DA/NU

3. Layout:
   - header sticky compact: DA/NU
   - bento grid: DA/NU
   - control center sidebar: DA/NU
   - hartă dominantă: DA/NU
   - panouri floating: DA/NU
   - secțiuni istoric/CSV mutate jos sau în tab: DA/NU

4. Hartă:
   - basemap dark: DA/NU
   - poligoane translucide: DA/NU
   - stroke modern: DA/NU
   - hover state: DA/NU
   - popup mini-card: DA/NU
   - badge alerte multiple: DA/NU
   - nowcasting stil diferit: DA/NU

5. Carduri:
   - KPI cards modernizate: DA/NU
   - alert cards modernizate: DA/NU
   - data cards pentru CSV: DA/NU
   - butoane interactive modernizate: DA/NU

6. Responsive:
   - desktop testat: DA/NU
   - tabletă testată: DA/NU
   - mobil testat: DA/NU

7. Accesibilitate:
   - focus states: DA/NU
   - contrast verificat: DA/NU
   - reduced motion: DA/NU

8. Teste funcționale:
   - calendar istoric: trecut/picat
   - hartă zi curentă: trecut/picat
   - hartă zi istorică: trecut/picat
   - zi fără date clean: trecut/picat
   - filtre: trecut/picat
   - nowcasting: trecut/picat
   - popup: trecut/picat

9. Deploy:
   - commit:
   - workflow status:
   - URL public:

10. Probleme rămase:
   - ...
```

---

## 21. Concluzie

Modernizarea dashboardului trebuie să transforme MeteoAlertRO într-o aplicație geospațială modernă, nu doar într-o pagină cu hartă.

Prioritățile vizuale sunt:

```text
dark natural
hartă dominantă
carduri glassmorphism
tipografie modernă
culori meteo neon-matte
interacțiuni clare
istoric discret
downloaduri moderne
```

Prioritățile funcționale care nu trebuie pierdute sunt:

```text
calendar istoric
toate alertele păstrate
nowcasting istoric
tooltip informativ
panou lateral complet
filtre reale
fără fallback greșit la latest
```

Redesignul nu trebuie să ascundă problemele de date. El trebuie să le facă mai ușor de înțeles.
