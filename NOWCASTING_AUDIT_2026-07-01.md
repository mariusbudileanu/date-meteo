# MeteoAlertRO - audit nowcasting 2026-07-01

## Rezumat

Auditul local si live arata ca endpoint-ul ANM nowcasting este valid, dar la momentul verificarii nu publica avertizari active:

- URL verificat: `https://www.meteoromania.ro/avertizari-nowcasting-xml.php`
- Status HTTP: `200`
- Dimensiune XML live: `46` bytes
- Continut live: `<avertizariNowcasting/>`
- Avertizari brute live: `0`
- Elemente `coordGis` live: `0`

Prin urmare, lipsa nowcasting-ului live nu este tratata ca eroare. Pentru validare istorica si UI exista un import manual controlat pentru Bucuresti, 2026-06-30.

## Date locale inainte de reparatie

Verificarile initiale pe datele locale au aratat:

- `public/data/*.geojson`: `0` feature-uri nowcasting in fisierele zilnice existente.
- `public/istoric/2026/2026-06.csv`: `8` randuri, `0` nowcasting.
- `public/istoric/2026/2026-07.csv`: `9` randuri, `0` nowcasting.
- `public/istoric/toate-alertele.csv`: `4` randuri, `0` nowcasting.
- `public/istoric/nowcasting/`: inexistent.
- `public/geodata/`: inexistent.
- fallback disponibil: `public/data/judete.geojson`.

## Workflow

Workflow-ul activ este `.github/workflows/scrape-anm.yml`.

Inainte de schimbare cronul era la aproximativ 6 ore:

```yaml
- cron: "0 0,6,12,18 * * *"
```

Pentru nowcasting, intervalul era prea rar. A fost schimbat la:

```yaml
- cron: "*/15 * * * *"
```

Ultimele rulari verificate cu `gh run list --workflow scrape-anm.yml --limit 10` erau `completed/success`. Logurile recente care au putut fi citite au raportat `0 avertizari` nowcasting.

## Concluzie

Nu exista dovezi ca scraperul a capturat automat nowcasting real in perioada verificata. Endpoint-ul live era gol la momentul auditului, iar datele locale nu contineau randuri nowcasting. Pentru Bucuresti 2026-06-30 a fost necesar import manual documentat.
