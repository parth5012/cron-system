# TECH_DEBT

## Flaky wall-clock latency assertions in `tests/test_e2e_wayfinder.py`

Three assertions measure elapsed time instead of behaviour, and all three fail
depending on how GitHub is answering this IP at that moment:

| Test | Bound | Observed |
|---|---|---|
| `test_e2e_wayfinder_api_caching_and_refresh_lifecycle` (line ~172) | cached `/api/wayfinder` < **25ms** | 38–63ms on a loaded machine |
| `test_e2e_wayfinder_full_user_journey` (line ~308) | cached `/api/wayfinder` < **25ms** | 38–63ms on a loaded machine |
| `test_e2e_wayfinder_api_live_data_and_schema` (line ~106) | live `/api/wayfinder` < **15s** | 46s while GitHub search was slow |

The 25ms ones include `TestClient` request overhead, so they assert machine
speed, not cache behaviour. The 15s one is worse: it depends entirely on
upstream GitHub. Measured during the PR merge on 2026-10-02, a raw
`GET https://api.github.com/search/issues` from this machine took **28.8s**
while `GET /repos/{owner}/{repo}/pulls` took **0.76s** in the same second —
GitHub was throttling the *search* resource for this IP after sustained
unauthenticated use, even though `/rate_limit` still reported 46/60 core
remaining (secondary/concurrency limits do not surface there).

- Impact: unrelated CI/dev runs report spurious failures. Full suite went
  57/57 green, then 55/57, then 54/57 across three consecutive runs minutes
  apart with no code change in between.
- Not a bug in `wayfinder.py`; the cache does return immediately.
- Fix options: raise the bounds to realistic values, skip them when
  `GITHUB_TOKEN` is absent or when a `/rate_limit` probe shows budget pressure,
  or assert on cache behaviour (e.g. mock call counts, as
  `tests/test_pull_requests.py` does) instead of elapsed time.

## Service worker scope is `/pwa/` only

`static/pwa/sw.js` is registered with `{ scope: '/pwa/' }`, so
`/pull-requests` and `/wayfinder` get no offline shell and no cached API
fallback. Offline PR data works inside the installed PWA only. Widening the
scope requires a `Service-Worker-Allowed: /` response header and a re-audit of
the cache-first navigation branch, which would otherwise serve stale HTML for
the whole site.

## No ruff/pytest configuration in the repo

There is no `pyproject.toml`, `pytest.ini` or `ruff.toml`, so lint rules and
pytest-asyncio's `asyncio_mode` are implicit (strict mode by default; the
existing tests use explicit `@pytest.mark.asyncio`). A config file would make
CI behaviour reproducible.
