# Free Always-On Cron System (FastAPI + cron-job.org + Render)

A lightweight, stateless FastAPI application designed to execute scheduled scripts triggered externally by [cron-job.org](https://cron-job.org) and deployed for free on [Render](https://render.com).

## 🚀 Architecture

```
┌──────────────────────────────────────────────────────────┐
│ FastAPI app (Render free web service, stateless)         │
│                                                          │
│   GET /health              Warmup / ping endpoint        │
│   GET /cron/{name}         Deep dispatcher (runs script) │
│   GET /cron/{name}/log     Recent run records (JSON)     │
│   POST /cron/{name}/run    Manual trigger for testing    │
│                                                          │
│   scripts/                 One script per job            │
│   cron.yaml                Single source of truth        │
└──────────────────────────────────────────────────────────┘
```

## 📋 Features

- **Deep Dispatcher Pattern:** Zero per-script route code required. Adding a script only requires dropping a `.py` file into `scripts/` and registering an entry in `cron.yaml`.
- **Single Source of Truth (`cron.yaml`):** All job definitions, schedules, secrets, and timeouts live in one declarative configuration file.
- **Authentication & Lock Control:** Every endpoint validates `X-Cron-Secret` header and enforces non-overlapping execution locks.
- **Background Execution for Long Jobs:** Tasks exceeding ~25 seconds return `202 Accepted` immediately and process asynchronously to prevent HTTP timeouts.
- **External Observability:** Emits run records (success, error, duration, logs) to an external Discord webhook / HTTP log sink.

## ⚙️ Cron-Job.org Setup Options

### Option A: Automated API Sync (Recommended)

1. Get your API Key from [cron-job.org Console](https://console.cron-job.org/) -> **Settings** -> **API**.
2. Run the sync script locally or in CI:
   ```bash
   export CRONJOB_ORG_API_KEY="your-api-key"
   export RENDER_URL="https://your-app.onrender.com"
   export CRON_SECRET="your-cron-secret"

   python scripts/cronjob_org_sync.py
   ```
   This automatically creates/updates all jobs listed in `cron.yaml` on cron-job.org with proper schedule, target URLs, and headers.

---

### Option B: Manual Setup via Dashboard

1. Log in to [cron-job.org](https://cron-job.org).
2. Click **Create Cronjob**.
3. Fill in details for each job in `cron.yaml`:
   - **Title:** `warmup` (or job name)
   - **URL:** `https://<your-render-app>.onrender.com/cron/warmup`
   - **Schedule:** Choose matching schedule (e.g. Every 10 minutes for `warmup`)
   - **HTTP Headers:** Add header:
     - Header Name: `X-Cron-Secret`
     - Header Value: `<your-CRON_SECRET>`
4. Save the job.

---

## 🛠️ How to Add a New Job

1. **Add an entry to `cron.yaml`:**
   ```yaml
   - name: my-new-job
     schedule: "0 12 * * *"
     secret: "${CRON_SECRET}"
     timeout_sec: 45
     description: "My daily 12pm task"
   ```

2. **Create the script `scripts/my-new-job.py`:**
   ```python
   #!/usr/bin/env python
   import sys

   def main():
       print("Running my custom task...")
       return 0

   if __name__ == "__main__":
       sys.exit(main())
   ```

3. **Sync to cron-job.org:**
   Run `python scripts/cronjob_org_sync.py` or register manually in the dashboard.

4. **Deploy / Push repository.** Zero FastAPI route code edits needed!

---

## 🔍 How to Check Logs

- **Endpoint:** `GET /cron/{name}/log`
- **Header:** `X-Cron-Secret: <your-CRON_SECRET>`
- **Response:** JSON array of recent `RunRecord` entries including stdout, stderr, exit code, and duration.
- **Log Sink:** If `LOG_SINK_URL` is set, logs will automatically post to your Discord channel/webhook on every run.

## 🧪 Local Testing

Run pytest within the `cron-system` directory:
```bash
cd cron-system
python -m pytest tests/
```

Or run the server locally:
```bash
export CRON_SECRET="my-local-secret"
uvicorn main:app --reload
```
Test endpoints:
```bash
curl -H "X-Cron-Secret: my-local-secret" http://localhost:8000/cron/warmup
curl -H "X-Cron-Secret: my-local-secret" http://localhost:8000/cron/warmup/log
```
