# LOG

## 2026-10-02 — Pull Requests module + mobile PWA overhaul

**Status:** Done (verified: 55 passed / 0 failed, Playwright mobile smoke, live
GitHub data)

### What changed

- `pull_requests.py` (new) — GitHub PR aggregation service modeled on
  `wayfinder.py`: `GITHUB_OWNER`/`GITHUB_REPOS` config, `GITHUB_TOKEN`/`GH_TOKEN`
  auth read live from env, 120s in-memory cache keyed per `involved` flag,
  Search API primary path + per-repo pulls union, TTL-bounded diff-stat
  enrichment. Endpoints: `GET /api/pull-requests` (`{prs, total_count, cached,
  rate_limit_remaining, …}`) and `GET /pull-requests` (standalone HTML).
- `main.py` — mount the new router; exclude `static/pull-requests/` from the
  blanket static mounts (same treatment `wayfinder` already had) so the router
  owns the route.
- `static/pull-requests/index.html` (new) — standalone dashboard in the
  Wayfinder aesthetic: theme toggle, PC metrics + table + drawer, mobile
  segmented filters + repo chips + expandable cards, skeleton loaders,
  pull-to-refresh, floating refresh, bottom nav with safe-area inset.
- `static/pwa/index.html` — new **PRs** tab (search, repo select, All/Ready/
  Draft/Review-me chips, Open/Draft/Review badges, branch + diff lines, "View on
  GitHub"); fixed bottom nav (Wayfinder/PRs/Content/Jobs) replacing the
  horizontal scroller under 768px; 48px touch targets, 16px inputs, single-row
  header, skeleton loaders, pull-to-refresh + FAB, upload reachable from a
  header button on mobile.
- `static/wayfinder/index.html` — bottom nav, skeleton loaders, 48px targets,
  16px controls, `viewport-fit=cover`.
- `static/pwa/manifest.webmanifest` + PWA meta description now mention PRs.
- Tests: `tests/test_pull_requests.py` (new, 25 tests) and 2 UI regressions in
  `tests/test_pwa_api.py`.

### Bug found and fixed during verification

Unioning Search API results with per-repo pulls listings listed **every PR
twice**: the two endpoints report different ids for the same PR (issue id vs
pull id). Fixed by de-duplicating on `(owner/repo, number)` and merging field
values instead of keeping the first hit. Regression tests:
`test_search_and_repo_listing_are_deduplicated`,
`test_repo_listing_does_not_mask_reviewer_role`.

### Verification

- `python -m pytest tests -q` → 55 passed. The 2 `tests/test_e2e_wayfinder.py`
  latency assertions (`< 25ms` cached) failed on a loaded machine earlier in
  the session and pass on an idle one — load-sensitive, see TECH_DEBT.md.
- `uvx ruff check --select F,E9,B,SIM,RET` on new/changed Python → clean. The
  `UP006/UP045` typing-modernization findings the new module shares with
  `wayfinder.py` were left alone to match the existing house style.
- Live API against real GitHub: 6 unique PRs with diff stats and branches;
  graceful degradation confirmed when the unauthenticated search budget is
  exhausted (search 403 → repo sweep still returns everything).
- Playwright at 360/390/430×844: bottom nav 48–52px targets, 48px FAB,
  16px inputs, no horizontal overflow, filters and search narrowing correctly,
  empty state rendered, zero JS errors, desktop layout unregressed.

### Not done (deliberate)

- Service-worker scope left at `/pwa/`, so `/pull-requests` and `/wayfinder`
  are not offline-capable. Widening it needs `Service-Worker-Allowed` plus a
  re-audit of the cache-first navigation handler.
- No commit made — changes left in the working tree for review.
