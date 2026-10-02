# TECH_DEBT

## Flaky wall-clock latency assertions in `tests/test_e2e_wayfinder.py`

`test_e2e_wayfinder_api_caching_and_refresh_lifecycle` and
`test_e2e_wayfinder_full_user_journey` assert a cached `/api/wayfinder` response
arrives in under **25ms** (lines ~172 and ~308). On a loaded machine both fail
(observed 38–63ms); on an idle machine both pass. The measurement includes
`TestClient` request overhead, not just the cache lookup, so it is a machine
speed assertion dressed as a test.

- Impact: unrelated CI/dev runs report spurious failures.
- Not a bug in `wayfinder.py`; the cache does return immediately.
- Fix options: raise the bound to a realistic 250ms, or assert on cache
  behaviour (e.g. mock call counts, as `tests/test_pull_requests.py` does)
  instead of elapsed time.

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
