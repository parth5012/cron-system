# ORCA — Complete Codebase Guide (SIH26176)

**Live Demo:** `https://cron-system.vercel.app/orca/` · Map `https://cron-system.vercel.app/orca/map/` · GeoJSON Arch `https://cron-system.vercel.app/orca/geojson/` · MPP Plan `https://cron-system.vercel.app/orca/mpp/` · Plan Visual `https://cron-system.vercel.app/orca/plan/`

This doc is the **file-section** for your Notion + repo — where every file lives, what it does, and how to run it. Copy-paste to Notion `Import Markdown`.

---

## 1. Repo To Be Created (2-Week MPP) — Proposed Structure

`orca-marine-intelligence/` ← new GitHub repo (6 members push here, not `AI-OS` nor `cron-system` demo hosting)

```
orca-marine-intelligence/
├─ README.md                          # 4-min demo path + live URLs
├─ docs/
│  ├─ ORCA_GeoJSON_Architecture.md    # ← already live https://cron-system.vercel.app/orca/ORCA_GeoJSON_Architecture.md
│  ├─ ORCA_2Week_MPP_Plan.md          # ← https://cron-system.vercel.app/orca/mpp/ORCA_2Week_MPP_Plan.md
│  ├─ ORCA_Codebase_Guide.md          # this file
│  └─ API.md                          # endpoint catalog
├─ frontend/                          # M3 + M4 (Next.js 14)
│  ├─ app/
│  │  ├─ page.tsx                     # Chat + Map split (Talk to ORCA + Map View)
│  │  ├─ map/page.tsx                 # Standalone Map View (Leaflet)
│  │  └─ api/pfz/route.ts             # Next proxy → FastAPI (avoids CORS)
│  ├─ components/
│  │  ├─ ChatPanel.tsx                # Talk to ORCA, Bhashini text 22 langs
│  │  ├─ MapView.tsx                  # Leaflet, pfz-today.geojson 437 circles, popup citation
│  │  ├─ SafetyBadge.tsx              # ✅ Proof Check
│  │  └─ LanguageSwitch.tsx           # request_locale
│  ├─ lib/
│  │  ├─ bhashini.ts                  # ULCA Translate, detect
│  │  └─ geo.ts                       # distance, DMS→decimal
│  └─ package.json
├─ backend/                           # M1 + M2 + M5 + M6 (FastAPI)
│  ├─ main.py                         # FastAPI app, /health, CORS
│  ├─ routers/
│  │  ├─ pfz.py                       # GET /api/pfz/today → GeoJSON, POST /ingest/pfz
│  │  ├─ tiles.py                     # GET /api/tiles/pfz/{z}/{x}/{y}.pbf (PostGIS ST_AsMVT)
│  │  ├─ weather.py                   # GET /api/weather?lat,lon (IMD proxy, mock W1)
│  │  └─ geofence.py                  # POST /api/geofence/check {lat,lon} → {inside EEZ/MPA?}
│  ├─ agents/
│  │  ├─ orchestrator.py              # M1 Brain ReAct, Intent→Planner→Tool Router
│  │  ├─ fish_finder.py               # M2 WHERE sector=KERALA distance<80 on pfz GeoJSON
│  │  ├─ sea_checker.py               # M5 wave mock 0.8m W1 → OSF W2
│  │  ├─ weather_agent.py             # M5 wind/cyclone IMD
│  │  ├─ danger_agent.py              # M5 EEZ/MPA ST_DWithin
│  │  └─ combiner.py                  # M1 Smart Combiner Fusion•Rank•Explain after swarm
│  ├─ ingest/
│  │  ├─ incois_textdata.py           # M2: curl -b cookies.txt TextData?secid=SEC001-014 → DMS→decimal → GeoJSON
│  │  ├─ copernicus_fallback.py       # Backlog W5: PHY 001_024 + BGC 001_028 where chl>0.5
│  │  └─ boundaries.py                # MarineRegions EEZ + WDPA MPA → PostGIS
│  ├─ db/
│  │  ├─ postgis.py                   # connection, ST_GeomFromGeoJSON
│  │  ├─ redis.py                     # cache 6h, multi-turn memory
│  │  └─ schema.sql                   # pfz(geom, sector, place, bearing, depth, distance), eez, mpa, waves
│  ├─ requirements.txt
│  └─ Dockerfile
├─ data/
│  ├─ pfz-today.geojson               # 437 Points 02-Sep (live https://cron-system.vercel.app/orca/map/data/pfz-today.geojson)
│  ├─ pfz-all.json                    # 437 objects with DMS
│  ├─ eez.geojson                     # MarineRegions
│  └─ mpa.geojson                     # WDPA
├─ infra/
│  ├─ docker-compose.yml              # FastAPI + PostGIS + Redis
│  ├─ vercel.json                     # cron-system static hosting already live file_count:9
│  └─ cron_ingest.sh                  # daily 11:30am TextData loop
├─ scripts/
│  ├─ extract_pfz.sh                  # loop SEC001-014 with JSESSIONID
│  └─ dms_to_decimal.py
├─ .env.example
└─ .gitignore
```

### Where Current Live Files Move
| Now (demo hosting) | Moves to (MPP repo) |
|---|---|
| `cron-system/static/orca/index.html` (`tmp/sih26176.html`) | `docs/arch.html` + `frontend/app/page.tsx` |
| `cron-system/static/orca/map/data/pfz-today.geojson` | `data/pfz-today.geojson` + `backend/db` seed |
| `cron-system/static/orca/map/index.html` | `frontend/app/map/page.tsx` |
| `tmp/pfz_SEC*.html` | `backend/ingest` cache, not committed |
| `docs/ORCA_*.md` | `docs/` |

---

## 2. Key Files — What Each Does (For 6 Members)

| File | Owner | PS FR | What It Does |
|------|-------|-------|--------------|
| `backend/agents/orchestrator.py` | **M1** | FR1, FR5 | `ReAct` splits `fish where? + safe?` → calls 4 agents in parallel, handles multi-turn `location/boat` |
| `backend/agents/combiner.py` | **M1** | FR5,6,8 | After swarm `x612,y430` — `closest*0.4 + safe sea*0.3 + wind*0.2 + not banned*0.1` → `explain + citation` |
| `backend/ingest/incois_textdata.py` | **M2** | FR4 | `curl -c cookies.txt TextDataHome → TextData?secid=SEC001-014` → parse 7-col → `DMS 8 33 18 N→8.555` → `GeoJSON` 437 |
| `backend/routers/tiles.py` | **M2/M6** | FR4, NFR | `GET /tiles/pfz/{z}/{x}/{y}.pbf` `ST_AsMVT` — Map View fetches tiles, not raw GeoJSON in prod |
| `frontend/components/MapView.tsx` | **M3** | FR3,6,7 | `Leaflet` `Bhuvan WMS` + `437 cyan circles` `rank1<60km`, popup `bearing/distance/citation INCOIS` + route `pgRouting` |
| `frontend/lib/bhashini.ts` | **M4** | FR2 | `Bhashini ULCA Translate` `detect → respond same language` `22 langs` `request_locale=ta/ml/hi` — text MVP only |
| `backend/agents/danger_agent.py` | **M5** | FR7 | `ST_DWithin(boat, eez, 2km)` `MarineRegions` + `WDPA MPA` → `IMBL` warning |
| `backend/main.py` + `routers/pfz.py` | **M6** | NFR | `FastAPI /api/pfz/today` server proxy `requests.get(https://incois...)` bypasses browser `CORS` → `fetch('/api/pfz/today')` same-origin |
| `infra/docker-compose.yml` | **M6** | NFR | `FastAPI:8000 + PostGIS:5432 + Redis:6379` one `docker compose up` |

---

## 3. Tech Stack (MVP, No Voice/Copernicus)

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | `Next.js 14` + `react-leaflet` + `Tailwind` | `Vercel` deploy `cron-system` already live, `Bhuvan` WMS easy |
| Language | `Bhashini ULCA` `Translate` + `fasttext` detect | 22 langs text MVP, no `STT/TTS` mic |
| Backend | `FastAPI` `Python 3.11` | Same as ingest `xarray/rioxarray`, `CORS` proxy simple |
| Geo | `PostGIS` `ST_AsMVT` + `GDAL` `ogr2ogr` + `GeoPandas` | `437 Points` → `tiles` for 2G at sea |
| Cache | `Redis` `6h` for `pfz` + `multi-turn` | Offline `GeoJSON` `mbtiles` via `expo-file-system` pattern |
| Raster (W2) | `xarray`, `Dask`, `Zarr/COG` | `OSF` `06Z` `wave/current` when mock replaced |
| LLM | `tool-calling LLM` + `RAG` over `INCOIS` docs | `M1` `ReAct` tool routing |
| Infra | `Docker Compose` + `Vercel` `cron-system` | `file_count:9` `335959 bytes` live, `GitHub` auto-deploy |

---

## 4. API Catalog (MPP)

| Method | Endpoint | Owner | Returns |
|--------|----------|-------|---------|
| `GET` | `/api/pfz/today` | M6 | `FeatureCollection` 437 Points `pfz-today.geojson` (proxied `INCOIS` HTML) |
| `POST` | `/api/ingest/pfz` | M2 | Triggers `SEC001-014` loop with `JSESSIONID`, returns `437 count` |
| `GET` | `/api/tiles/pfz/{z}/{x}/{y}.pbf` | M2/M6 | `MVT` vector tile for `Map View` |
| `GET` | `/api/weather?lat,lon` | M5 | `{wind, wave:0.8 mock W1, cyclone}` |
| `POST` | `/api/geofence/check` | M5 | `{insideEEZ: bool, distanceToIMBL: m}` |
| `POST` | `/api/chat` | M1 | `{answer, map_ref, evidence:[citation], lang}` |

`CORS`: `app.add_middleware(CORSMiddleware, allow_origins=["https://cron-system.vercel.app"], ...)` — but `frontend` `fetch('/api/pfz/today')` same-origin → no CORS.

---

## 5. Data — What We Extract & How

**INCOIS TextData (Live 02-Sep):** `https://incois.gov.in/MarineFisheries/TextData?secid=SEC005` with `JSESSIONID` `F352B2C32650...` → HTML `<table><tr><td>Pallithottam</td><td>SW</td><td>232</td><td>55-60</td><td>645-650</td><td>8 33 18 N</td><td>76 10 2 E</td>` → parse → `DMS→decimal` → `Point(lon,lat)` → `pfz-today.geojson`.

**Loop:** `for SEC001 GUJARAT … SEC014 LAKSHADWEEP` daily `11:30am` (INCOIS publishes 11am).

**Fallback (Backlog W5):** `Copernicus Marine` `cmems_mod_glo_phy_my` `thetao SST` + `cmems_mod_glo_bgc_my` `chl` where `chl>0.5 & SST front (sobel)` → polygonize.

**Boundaries (Static, W1):** `MarineRegions EEZ` `https://geo.vliz.be/.../eez.geojson` + `WDPA MPA` `https://www.protectedplanet.net/downloads` → `PostGIS`.

---

## 6. How to Run (For 6, After Clone)

```bash
# 1. Env
cp .env.example .env  # INCOIS_JSESSIONID, BHASHINI_API_KEY, DATABASE_URL, REDIS_URL

# 2. Infra
docker compose up -d  # PostGIS + Redis
psql -f backend/db/schema.sql

# 3. Ingest (M2) — live 437 points
curl -c cookies.txt https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1 -o /tmp/home.html
for s in SEC001 SEC002 ... SEC014; do curl -b cookies.txt https://incois.gov.in/MarineFisheries/TextData?secid=$s -o data/pfz_$s.html; done
python backend/ingest/incois_textdata.py  # → data/pfz-today.geojson

# 4. Backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
# test: curl http://localhost:8000/api/pfz/today | jq '.features | length' # 437

# 5. Frontend
cd frontend && npm i && npm run dev  # http://localhost:3000 → Chat + Map
# Map standalone: http://localhost:3000/map → fetches /api/pfz/today → 437 cyan dots
```

**Vercel (M6):** Push to `main` → `cron-system` auto-deploy `https://cron-system.vercel.app/orca/` + `/map/` + `/geojson/` + `/mpp/` + `/plan/`.

---

## 7. Other Details (NFR, Testing, Risks)

- **NFR:** `Reliability` cache `Redis 6h` + fallback `yesterday’s GeoJSON` when `TextData 404`; `Latency` `P50` map <2s via `MVT` tiles; `Offline` `mbtiles` `expo-file-system`; `Audit` logs `datasets_used` per answer.
- **Weekly Global Tests (All 6, Live):** `Fri W1 05 Sep 16:00` `Malayalam text → Map pin` + `Fri W2 12 Sep 16:00` 5 SIH scenarios `PFZ→Safety Veraval→Lightning→Route EEZ→Refinement` — `P50 + geofence distance` logged.
- **Deliverables SIH:** `frontend` + `backend` `FastAPI` + `PostGIS` `Zarr` + `explainability` `citation` + `video` + `docs` `ORCA_2Week_MPP_Plan.md` `ORCA_GeoJSON_Architecture.md` + `eval` 5 scenarios.
- **Repo Rules:** `main` protected, `6 feature branches` `M1-orchestrator` etc., `PR` needs `1 review` + `Vercel` preview.

---

## 8. File Section for Notion — Copy This Table

| Section | Files | Who |
|---------|-------|-----|
| **Docs** | `README.md`, `docs/ORCA_GeoJSON_Architecture.md`, `docs/ORCA_2Week_MPP_Plan.md`, `docs/ORCA_Codebase_Guide.md` (this), `docs/API.md` | M1+M6 |
| **Data (Live 02-Sep)** | `data/pfz-today.geojson` (128KB 437), `data/pfz-all.json` (125KB), `data/eez.geojson`, `data/mpa.geojson` | M2+M5 |
| **Frontend** | `frontend/app/page.tsx`, `frontend/app/map/page.tsx`, `frontend/components/MapView.tsx`, `frontend/components/ChatPanel.tsx`, `frontend/lib/bhashini.ts` | M3+M4 |
| **Backend Agents** | `backend/agents/orchestrator.py`, `combiner.py`, `fish_finder.py`, `sea_checker.py`, `weather_agent.py`, `danger_agent.py` | M1+M2+M5 |
| **Ingest** | `backend/ingest/incois_textdata.py`, `copernicus_fallback.py` (W5), `boundaries.py` | M2 |
| **Infra** | `infra/docker-compose.yml`, `infra/vercel.json`, `infra/cron_ingest.sh`, `backend/db/schema.sql` | M6 |
| **Live Demo** | `https://cron-system.vercel.app/orca/` `https://cron-system.vercel.app/orca/map/` `https://cron-system.vercel.app/orca/geojson/` `https://cron-system.vercel.app/orca/mpp/` `https://cron-system.vercel.app/orca/plan/` | All |

---

*Generated 02 Sep 2026 16:00 IST — 2-week MPP, 437 PFZ live, mock wave W1 → real OSF W2, text multilingual MVP. This file → Notion import Markdown.*
