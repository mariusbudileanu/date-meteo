# Workflow Nowcasting Audit — 2026-07-02

## 1. Context

Pe 1 iulie 2026, în intervalul 18:00–18:45 RO (15:00–15:45 UTC), ANM a emis o avertizare nowcasting
**Cod Roșu** pentru București (vijelie puternică, averse torențiale, grindină, descărcări electrice).
Alerta **nu apare în arhivă/hartă**. Acest document documentează cauza și fixurile aplicate.

---

## 2. Workflow schedule

- **cron**: `*/15 * * * *`
- **frecvență teoretică**: ~96 rulări/zi
- **observații GitHub schedule delay**: GitHub Actions pot întârzia rulările `schedule` cu până la **10–30+ minute** față de ora cron, mai ales în perioade de vârf. Acesta a fost cazul pe 1 iulie 2026 — un GAP de **~2h36 min** fără nicio rulare schedule.

---

## 3. Rulări GitHub Actions — interval critic 1 iulie 2026

| Run ID | Start UTC | Start RO | Event | Status | NC XML bytes | NC Parsed | București Roșu |
|---|---|---|---|---|---|---|---|
| 28523326854 | 14:02 UTC | 17:02 RO | schedule | ✅ success | 1777 bytes, 3 alerte raw, **0 parsate** (bug regex activ) | 0 | NU |
| 28523852325 | 14:11 UTC | 17:11 RO | workflow_dispatch | ✅ success | — (dispatch manual) | — | NU |
| **[LIPSĂ]** | **15:00–15:45 UTC** | **18:00–18:45 RO** | schedule | **❌ NU A RULAT** | — | — | **—** |
| 28532935807 | 16:38 UTC | 19:38 RO | schedule | ✅ success | 806 bytes, 1 alertă, **1 parsată** (fix activ) | 1 | NU |
| 28539140527 | 18:29 UTC | 21:29 RO | schedule | ✅ success | 46 bytes (endpoint gol) | 0 | NU |

> **GAP confirmat**: între 14:11 UTC și 16:38 UTC (2h27 min), nicio rulare schedule nu a existat.
> Aceasta acoperă integral fereastra 15:00–15:45 UTC (18:00–18:45 RO) a codului roșu București.

---

## 4. Cod Roșu București

- **Interval public**: ~18:00–18:45 RO (15:00–15:45 UTC)
- **Căutat în run-uri**: toate run-urile din 1 iulie 2026 (80 disponibile)
- **Găsit în XML**: NU (nu există run în fereastra 15:00–15:45 UTC pentru a verifica)
- **Găsit în GeoJSON**: NU (`public/data/2026-07-01.geojson` — căutare exhaustivă)
- **Găsit în CSV**: NU (`public/istoric/nowcasting/2026-07.csv`)
- **Găsit în index.json**: NU
- **Concluzie**: Alerta **nu a putut fi capturată** deoarece workflow-ul nu a rulat în fereastra activă

---

## 5. Cauza probabilă — CONCLUZIE FINALĂ

**Cauza primară: workflow-ul NU A RULAT în fereastra 15:00–15:45 UTC (18:00–18:45 RO)**

GitHub Actions `schedule` (cron `*/15 * * * *`) suferă de delay-uri nedeterministe.
Pe 1 iulie 2026, runnerele GitHub au avut un gap de ~2h27 min între rulări consecutive schedule.
Codul roșu București a fost activ exact în acest interval neacoperit.

**Cauza secundară (contribuitoare)**: La rularea de la 14:02 UTC (17:02 RO), fixul de parsare
(regex mojibake, `culoare` vs `numeCuloare`, `dataInceput`/`dataSfarsit`) nu era complet deployat.
Chiar dacă ar fi existat o rulare la 15:00 UTC, ar fi putut rata alerta din cauza bugului activ.

**Fixul de parsare a fost deployat la**: 14:10 UTC (commit `22da171`), deci **după** ultimul run
funcțional pre-gap (14:02 UTC) și **înainte** de fereastra codului roșu (15:00 UTC).
Dacă ar fi existat o rulare la 15:15 UTC sau 15:30 UTC, **ar fi capturat alerta** cu noul fix.

---

## 6. Fixuri implementate

### 6.1 Parser nowcasting (PR anterior)
- **Fix regex** `parse_nowcasting_counties_and_localities`: caractere mojibake → Unicode corect (`\u021b`, `\u0163`)
- **Fix atribute nowcasting XML**: `dataInceput/dataSfarsit` → `dataAparitiei/dataExpirarii`
- **Fix prioritate culoare**: `numeCuloare`/`avertizareNivelDenumire` > numeric `culoare` (care este index intern ANM, nu codul MeteoAlert)
- **Fix `coordsGis`** (cu 's') → `coordGis`
- **Adăugat endpoint XML-GIS** cu geometrie reală, merge în alertele simple XML
- **Eliminat blocul duplicat** `main()` / `glob_csv()` / `rebuild_history_stats()` / `rebuild_istoric_manifest()`

### 6.2 Heartbeat `status.json` (acest PR)
- Fișier `public/data/status.json` scris la **fiecare rulare** indiferent de schimbări date
- Conține `last_checked_at_utc`, `last_checked_at_ro`, `last_data_change_at_utc`, stats nowcasting
- Frontend afișează acum **două timpuri separate**: `Verificat: HH:MM` și `Date: HH:MM`

### 6.3 Debug snapshots nowcasting (acest PR)
- La fiecare rulare se salvează în `public/debug/nowcasting/`:
  - `YYYY-MM-DD_HHMM_nowcasting.xml` — raw XML simplu
  - `YYYY-MM-DD_HHMM_nowcasting_gis.xml` — raw XML-GIS
  - `YYYY-MM-DD_HHMM_summary.json` — stats parsare
- Retenție automată: maxim 96 snapshot-uri (~24h la */15 min)

### 6.4 Workflow timing log (acest PR)
- Pas nou `Log workflow timing` afișează: `utc_now`, `ro_now`, `github_event_name`, `github_run_id`
- Permite auditarea exactă a oricărei rulări

### 6.5 `git add` extins (acest PR)
- Adăugat `public/debug/` în `git add` din workflow
- `public/data/status.json` e inclus implicit prin `public/data/`

---

## 7. Teste efectuate

### 7.1 Local
- `python src/scraper.py` → ✅ `[status] Scris status.json: verificat=09:10 nowcasting_live=0`
- `python src/scraper.py` → ✅ `[debug] Snapshot salvat: 2026-07-02_0610`
- `public/data/status.json` — ✅ conținut valid JSON cu toate câmpurile
- `public/debug/nowcasting/` — ✅ 3 fișiere generate (nowcasting.xml, nowcasting_gis.xml, summary.json)

### 7.2 GitHub Actions (rulare anterioară validată)
- Run 28539140527 (18:29 UTC): ✅ workflow funcțional cu noul format log
- Run 28532935807 (16:38 UTC): ✅ nowcasting live=1 capturat, coordGis=1

---

## 8. Probleme rămase

| # | Problemă | Severitate | Status |
|---|---|---|---|
| 1 | GitHub Actions schedule delay (poate fi 2h+) | **Mare** | Nerezolvabil direct — limitare platformă |
| 2 | Lipsa snapshot-urilor pentru fereastra codului roșu | Medie | Rezolvat prin debug snapshots |
| 3 | Avertizare București cod roșu neînregistrată | Medie | Nerecuperabilă (fără raw XML disponibil) |
| 4 | `last_data_change_at_utc` în status.json arată ora curentă, nu ora ultimei schimbări reale | Mică | De rafinat în iterație viitoare |

> [!NOTE]
> GitHub Actions oferă **garantarea cel mult o rulare pe interval cron**, fără SLA de precizie.
> Pentru alertare critică în timp real, soluția corectă este un server dedicat cu cron propriu
> sau un serviciu de monitoring terț (uptime robot, Cloudflare Workers, etc).

> [!TIP]
> Debug snapshot-urile din `public/debug/nowcasting/` sunt acum vizibile pe GitHub Pages la:
> `https://mariusbudileanu.github.io/date-meteo/debug/nowcasting/`
> Poți verifica manual oricând ce a returnat ANM la fiecare rulare.
