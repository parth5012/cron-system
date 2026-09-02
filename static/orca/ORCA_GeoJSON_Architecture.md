# ORCA — Agentic Marine Intelligence (SIH26176) — How It Works (GeoJSON-Centric)

**Live:** `https://cron-system.vercel.app/orca/` (arch) + `https://cron-system.vercel.app/orca/map/` (437 PFZ points 02-Sep-2026)  
**Data:** `https://cron-system.vercel.app/orca/map/data/pfz-today.geojson` (437 features, SEC001-014)  
**Source:** `https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1` → `TextData?secid=SEC005` with `JSESSIONID` (INCOIS TextData, not KML — `pfzmmaps/20260902` is dead `404` as of 02-Sep)

---

## 1. Problem (PS Bullets)
- Fisherman asks in Malayalam/Tamil `PFZ? Safe to go?` — needs *where* not paragraph.
- INCOIS PFZ is satellite `SST + chlorophyll` front, published daily 11am as HTML table (7-col: `place | dir | bearing | depth | distance | lat DMS | lon DMS`), not GeoJSON.
- Need: language ID + multi-turn + spatial/temporal reasoning + explainable map + safety (waves/cyclone) + geofencing (EEZ/MPA) + route.

## 2. Solution — 3 Steps Anyone Gets
1. **You ask** by voice/map in your language → `Talk to ORCA` `+ Language Detect (22 langs)` hears it.
2. **4 helpers check same GeoJSON points in parallel** — `Fish Finder (PFZ)`, `Sea Checker (waves/currents)`, `Weather & Tide (wind/tide)`, `Danger Watch (cyclone/geofence)`.
3. **Smart Combiner picks best *safe* fish spot**, shows it on `Map View` with proof (`INCOIS TextData SEC005 KERALA 02-Sep`) + sends `SMS/Voice` route.

Without shared `pfz-today.geojson`, helpers answer in silos → `fish at A but storm at A` contradiction.

---

## 3. Why TextData → GeoJSON (What We Actually Did)
**INCOIS `PFZViewer.jsp` + `pfzmmaps/*.kml` → 404** (`curl` server-side also `1583 bytes Page Not Found`). Correct live path is `TextDataHome` → `TextData?secid=SECxxx` with session cookie.

**Extraction (today 02-Sep 15:00 IST):**
```bash
curl -c cookies.txt https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1 -o home.html
# JSESSIONID=F352B2C32650... saved
for i in 01..14; do curl -b cookies.txt https://incois.gov.in/MarineFisheries/TextData?secid=SEC00$i -o pfz_SEC00$i.html; done
# each HTML has <table><tr><td>Pallithottam</td><td>SW</td><td>232</td><td>55-60</td><td>645-650</td><td>8 33 18 N</td><td>76 10 2 E</td>
```
Parse: `DMS 8 33 18 N → 8+33/60+18/3600 = 8.555°`, `76 10 2 E → 76.167°` → `Point(lon,lat)` → `FeatureCollection` 437 features `SEC001 GUJARAT … SEC014 LAKSHADWEEP` → `tmp/pfz-today.geojson` (128KB) + `pfz-all.json`.

This is your `Ocean Data Library → Fast Map Memory` pipeline: `STAC/WFS` would be ideal, `TextData HTML` is the working `WFS` today.

---

## 4. Architecture (Atomic, GeoJSON-Centric)

```
[INCOIS TextDataHome] --JSESSIONID--> [TextData SEC001-014 HTML tables] --parse DMS--> [pfz-today.geojson 437 Points]
        |                                                                      |
        |                                                              [PostGIS + Redis tiles]
        |                                                                      |
        |   +---------------+----------------+----------------+               |
        v   v               v                v                v               v
   [Fish Finder]    [Sea Checker]   [Weather/Tide]   [Danger Watch]   [Fast Map Memory /tiles/{z}/{x}/{y}.pbf]
        \               |                |                /               |
         \              |                |               /                |
          `-----> [Smart Combiner (after swarm) — Fusion • Rank • Explain] <----'
                         |                |
                         v                v
                 [Safety Check]    [Map View (Leaflet)]  <--- user taps zone
                         |                |
                         `-----> [Alerts to Phone SMS/Voice] + [Safety route polyline]
```

**Positions in diagram:** `Smart Combiner x612,y430` after `swarm x620` (not left of it), `Map View x250,y395` as output after combiner, `Safety Check x410,y470` under it — flow reads left→right without back-track.

**File:** `tmp/sih26176.html:654` (main ORCA), atomic GeoJSON diagram: `tmp/orca-geojson-arch.html` → `https://cron-system.vercel.app/orca/geojson` (this doc's diagram).

---

## 5. Multi-Agent + GeoJSON — How It Works Together
- **Shared key:** `lat/lon` from GeoJSON is join key. `PFZ Agent` filters `WHERE sector=KERALA AND distance<60`; `Sea Checker` joins `wave at that point`; `Weather` joins `wind`; `Danger` checks `ST_DWithin(point, EEZ)`.
- **Example — Kochi fisherman (Malayalam voice):**
  1. `Talk to ORCA` detects Malayalam → `Brain` splits `fish where? + safe?`
  2. `Fish Finder` → `Pallithottam 8.555,76.167 55km SW` (rank1)
  3. `Sea` → `wave 0.8m ok`, `Weather` → `wind 8kt ok`, `Danger` → `no cyclone`
  4. `Combiner` → `Pallithottam rank1 SAFE`, `Mampally rank1 but 2.1m rough → rank2`
  5. `Map View` flies to `8.55,76.16`, cyan circle, popup `Bearing 232 Depth 55-60 Citation INCOIS TextData SEC005 02-Sep`, green route from GPS → `SMS` in Malayalam.

Without shared points, you'd get 4 conflicting answers. With it, one safe answer with proof.

---

## 6. User Value
- **Saves:** 4h search + 40L diesel per trip (go to advisory point, not blind).
- **Trust:** every zone shows `why: bearing/distance + citation` not `go here`.
- **Language:** 22 langs auto, voice at sea, offline `GeoJSON` cached.
- **Safety:** `Danger Watch` + `geofence ST_DWithin(EEZ)` blocks `IMBL` crossing.

---

## 7. Tech Stack (MVP)
- **Ingest:** `curl + python html.parser → DMS→decimal → GeoJSON` (today), `copernicusmarine` fallback when INCOIS down (`PHY 001_024` SST + `BGC 001_028` Chl where `chl>0.5 & SST front`)
- **Store:** `PostGIS (geom Point 4326) + Redis` → `ST_AsMVT` tiles `/api/tiles/pfz/{z}/{x}/{y}.pbf`
- **API:** `FastAPI /api/pfz/today` proxies `TextData` (server `requests` bypasses `CORS`; browser `fetch('/api/pfz/today')` same-origin → no CORS)
- **Frontend:** `Next.js + react-leaflet + Bhashini STT/TTS`, `offline mbtiles` via `expo-file-system` (same as `VelaVoice/velavoice app/` pattern)
- **Deploy:** `cron-system` `static/orca` + `static/orca/map` → Vercel auto-deploy

---

## 8. PS Coverage
- `Language + multi-turn` → Bhashini + Redis history
- `Autonomous data discovery` → `TextData` loop SEC001-014 daily 11am
- `Spatial/temporal reasoning` → `PostGIS ST_Intersects + 7-day history`
- `Explainable maps` → `Map View` + `Safety Check` citation
- `Safety alerts` → `OSF/GOFS waves + IMD cyclone` joined on same points
- `Geofencing` → `MarineRegions EEZ + WDPA MPA` `ST_DWithin`
- `Route` → `pgRouting` cost `wave*0.5 + wind*0.3`

---

## 9. What You Have Now
- `tmp/pfz-all.json` (125KB) + `tmp/pfz-today.geojson` (128KB) 437 zones live 02-Sep
- `https://cron-system.vercel.app/orca/map/data/pfz-today.geojson` + `pfz-all.json` served
- `https://cron-system.vercel.app/orca/map/` renders live points (replaced mock `A/B/C`)
- `https://cron-system.vercel.app/orca/` arch with `Smart Combiner after swarm`, `Map View x250,y395`, halos, abbreviations

**Next:** wire `FastAPI /ingest/pfz → PostGIS → tiles` so `Map View` fetches `tiles` not `GeoJSON` file, and add `Copernicus` fallback ingest when `TextData` 404.

---

*Generated 02-Sep-2026 15:30 IST — ORCA GeoJSON pipeline live.*
