# ORCA — SIH26176 Agentic Marine Intelligence — 2-Week MPP Plan (02 Sep – 16 Sep 2026)

**Live Artifacts:** Arch `https://cron-system.vercel.app/orca/` · Atomic GeoJSON Arch `https://cron-system.vercel.app/orca/geojson/` · Map 437 PFZ `https://cron-system.vercel.app/orca/map/` · Data `https://cron-system.vercel.app/orca/map/data/pfz-today.geojson` · Plan Visual `https://cron-system.vercel.app/orca/plan/`  
**MPP Scope:** `INCOIS TextData → GeoJSON` live, `Map View` with 437 points, `Smart Combiner` after swarm, `Multilingual text (22 langs)` MVP, `Voice STT/TTS = backlog`, `Copernicus fallback = backlog`, `M5 wave = mock 0.8m W1 → real OSF W2`, `INCOIS TextData SEC001-014` via `JSESSIONID` (`pfzmmaps/*.kml` dead 404)

---

## 1. Goal (What Judges Click in 4 Minutes)
> Kochi fisherman types in Malayalam `എവിടെ മത്സ്യം?` → ORCA detects Malayalam → finds 3 closest PFZ dots within 80km from `437-point pfz-today.geojson` → 4 helpers check wave/wind/banned → `Smart Combiner` picks best **SAFE** spot → `Map View` flies to `8.55,76.16` `Pallithottam SW 232 55km` with `citation INCOIS TextData SEC005 02-Sep` + green route → `SMS` in Malayalam.

This loop ticks **FR1 Chat + FR2 Multilingual text + FR3 Location + FR4 Data discovery + FR5 Spatio-temporal + FR6 Map/Explain + FR7 Geofencing + FR8 Evidence**.

---

## 2. Timeline — 2 Weeks, 2 Global Tests

| Week | Dates | Focus | Exit Criteria (Demo-able) |
|------|-------|-------|---------------------------|
| **W1 Build** | 02–09 Sep | `TextData → GeoJSON → Map + Brain + Combiner + EEZ/MPA + Bhashini text` | **Fri 05 Sep 16:00 IST Global Test #1 (all 6):** `Malayalam text near Kochi → Map pin 8.55,76.16 → Safety Check → SMS mock` passes. |
| **W2 Harden** | 09–16 Sep | `IMD wind/cyclone real, multi-turn memory, route, offline cache, evidence schema, polish` | **Fri 12 Sep 16:00 IST Global Test #2 (SIH Dress):** 5 scenarios `PFZ today → Safety Veraval tomorrow → Lightning alert → Route avoids EEZ → Malayalam refinement` with `P50 latency + geofence distance` logged. Freeze `static/orca` `file_count:7` for SIH submit. |

**Global Tests = All 6 on `cron-system` live, not local** — catches `CORS`, `JSESSIONID` expiry, `Vercel` deploy drift. Daily standup `10:00 IST` 15min, `Fri 16:00` 60min cross-test.

---

## 3. Architecture (Where Each Member Lives)

```
INCOIS TextDataHome (JSESSIONID) → TextData SEC001-014 HTML (7-col) → Parse DMS→decimal → pfz-today.geojson 437 Points → PostGIS + Redis tiles
                                                                                      ↓
Fish Finder (M2) — Sea Checker (M5 mock 0.8m) — Weather (M5 mock wind) — Danger (M5 EEZ/MPA) — all read same lat/lon
                                                                                      ↓
Smart Combiner (M1) x612,y430 after swarm — Fusion•Rank•Explain — closest*0.4 + safe sea*0.3 + wind*0.2 + not banned*0.1
                                                                                      ↓
Map View (M3) x250,y395 + Safety Check (M1/M5) citation + Alerts to Phone (M6) SMS — Talk to ORCA (M4) multilingual text
```

Diagram: `tmp/sih26176.html:654` (main ORCA) + `tmp/orca-geojson-arch.html` (atomic GeoJSON) → `https://cron-system.vercel.app/orca/geojson/`

---

## 4. 6-Member Split — What, By When (MVP, 2 Weeks)

> `Voice STT/TTS` and `Copernicus PHY+BGC` are **backlog W5**, not MVP. `M5 wave = mock 0.8m W1 → real OSF 06Z W2`.

| Member | Role (FR) | W1 Due: 09 Sep | W2 Due: 16 Sep | Handover / URL | W1 Load |
|--------|-----------|----------------|----------------|----------------|---------|
| **M1 — Orchestrator + Reasoning** | `FR1, FR5, FR6, FR8` `Planner/ReAct → Risk/Decision` | `Brain` stub `Intent→Planner→Tool Router` + `Smart Combiner` after swarm `Fusion•Rank•Explain` on `closest+0.8m mock` → returns `citation` | `Multi-turn memory` `Redis: location/boat/risk` + `explain` panel `Why + datasets_used` | `tmp/sih26176.html` `Smart Combiner x612,y430` |
| **M2 — Marine Data + Ocean Analytics** | `FR4 PFZ` | **`INCOIS TextData SEC001-014 → pfz-today.geojson 437`** `curl -b cookies.txt` `DMS 8 33 18 N→8.555` → `https://cron-system.vercel.app/orca/map/data/pfz-today.geojson` `PostGIS Point` | Tile cache `ST_AsMVT /tiles/{z}/{x}/{y}.pbf` + daily `11:30am` cron | `tmp/pfz-today.geojson` `128KB` `file_count:7` | **High** |
| **M3 — Geospatial + Visualization** | `FR3, FR6, FR7` | `Map View` `Leaflet/Bhuvan` `437 cyan rank1 <60km` `https://cron-system.vercel.app/orca/map/` `tap→popup bearing/distance` | Route `pgRouting` `cost = wave*0.5 + wind*0.3 + forbidden` + `FR3 pin/GPS/WGS84` | `static/orca/map/index.html` | **High** |
| **M4 — Language (Text MVP)** | `FR2` | `Bhashini ULCA Translate` `22 langs` `request_locale=ta/ml/hi/bn` `Talk to ORCA` text `detect → answer same lang` | Polish `hi/ta/te/ml` glossary + mixed transliteration | `Talk to ORCA x210` `Bhashini` — Voice `STT/TTS` → W5 | **Medium** |
| **M5 — Safety + Geofencing** | `FR7, FR8` | `MarineRegions EEZ` + `WDPA MPA` → `PostGIS` `ST_DWithin(boat,eez,2km)` `Danger Watch` `IMBL` + **mock `wave 0.8m` + mock wind** for all 437 | Add real `IMD` `wind/cyclone/lightning` `https://mausam.imd.gov.in` text; `OSF` real `06Z` wave stays **W2** (not W1) | `Geofence` polygons | **Medium (mock) → High if OSF W1** |
| **M6 — Platform + Reporting** | `NFR` `FR4, FR6` | `FastAPI /api/pfz/today` server proxy `requests.get` bypasses `INCOIS CORS` → `fetch('/api/pfz/today')` same-origin + `Vercel` `static/orca` deploy | `SMS` `Alerts to Phone`, offline `GeoJSON` cache `mbtiles`, `Reporting Agent` `PDF advisory`, `Redis 6h` | `D:\work\projects\cron-system` | **Medium** |

**Single global dependency:** All read same `lat/lon` GeoJSON key — `M2` `W1 Tue` delivery unblocks `M1/M3/M5`.

---

## 5. W1 Daily Slice (What Each Member Does Tue-Fri)

| Day | M1 | M2 | M3 | M4 | M5 | M6 |
|-----|----|----|----|----|----|----|
| **Tue 02 Sep** | `Brain` stub | `pfz-today.geojson 437` done | `Map` renders `GeoJSON` circles | `Bhashini` `en↔ml` test | `EEZ` download | `FastAPI` proxy |
| **Wed 03 Sep** | `Tool Router` | `PostGIS` ingest | `Bhuvan` WMS base | `Talk to ORCA` UI | `MPA` ingest | `Vercel` deploy |
| **Thu 04 Sep** | `Smart Combiner` ranking | `11:30am` cron | `popup citation` | `22 langs` switch | `ST_DWithin` logic | `Redis` cache |
| **Fri 05 Sep 16:00** | **Global Test #1** | **Global Test #1** | **Global Test #1** | **Global Test #1** | **Global Test #1** | **Global Test #1** |

**W2:** Mon `M5` adds `IMD wind`, `M1` adds `memory`, Tue `M3` adds `route`, Wed `M6` adds `SMS/offline`, Thu freeze, **Fri 12 Sep 16:00 Global Test #2** 5 scenarios.

---

## 6. How GeoJSON Helps User + Multi-Agent (Simple)
1. **Get location** `GPS 9.93,76.26` or `near Kochi` text
2. **Closest dots** from 437 `GeoJSON` within 80km → top 5
3. **4 helpers filter** `Sea (wave) + Weather (wind) + Danger (EEZ)` on same `lat/lon`
4. **Smart Combiner** picks best **SAFE** (not just closest) → `Map` blue dot + route + `SMS` in Malayalam with `citation INCOIS TextData SEC005 02-Sep` → saves 4h + 40L diesel.

Without shared `lat/lon` GeoJSON, agents answer in silos → `fish at A but storm at A`.

---

## 7. Risks & Mitigations (MPP)
- `INCOIS TextData 404` (pfzViewer dead) → fallback `yesterday’s pfz-today.geojson` cached `W1`, `Copernicus` `W5`
- `JSESSIONID` expiry → refresh `curl -c cookies.txt TextDataHome` daily
- `CORS` `INCOIS` → `FastAPI` server proxy `requests.get` (browser `fetch('/api/pfz/today')` same-origin)
- `Vercel` `file_count` drift → `Fri` global test on live `https://cron-system.vercel.app/orca/*`

---

## 8. Deliverables for Notion (Copy-Paste)
- **Prototype:** `https://cron-system.vercel.app/orca/map/` + `https://cron-system.vercel.app/orca/` + `https://cron-system.vercel.app/orca/geojson/` + `https://cron-system.vercel.app/orca/plan/`
- **Data:** `https://cron-system.vercel.app/orca/map/data/pfz-today.geojson` (437) + `pfz-all.json`
- **Docs:** This `ORCA_2Week_MPP_Plan.md` + `ORCA_GeoJSON_Architecture.md` `https://cron-system.vercel.app/orca/ORCA_GeoJSON_Architecture.md`
- **Issues:** 6 issues `M1-M6` × 2 milestones `W1 09 Sep` + `W2 16 Sep`

---

*Generated 02 Sep 2026 15:45 IST — ORCA MPP 2-week plan, mock wave W1 → real OSF W2, multilingual text MVP.*
