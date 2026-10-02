# LEARNINGS

## GitHub ids: a pull request has TWO ids

`GET /search/issues` returns a PR with the **issue** `id` (e.g. `5668278848`),
while `GET /repos/{owner}/{repo}/pulls` returns the **pull request** `id`
(e.g. `4708858338`) for the exact same PR. Unioning the two data sources and
de-duplicating on `id` silently lists every PR twice.

**Rule:** de-duplicate PRs on `(owner/repo, number)`, never on `id`.
Applies to any code that unions GitHub search results with per-repo listings.

## `x-ratelimit-remaining` means different things per resource

The same header name is reused for the `core` (60/hr unauth, 5000/hr auth) and
`search` (10/min unauth, 30/min auth) budgets. A `GET /repos/.../pulls` call
can report `59` seconds after a `GET /search/issues` call reported `0`.

**Rule:** when reporting a single "budget left" number, surface the *most
constrained* reading (min) rather than the most recent one, and attach the
full limit/remaining/reset triple separately.

## Unauthenticated GitHub budget shapes the architecture

Without a token, one full sweep of 8 repos costs 8 core requests (60/hr) and 3
search queries cost 3 of 10/min. Consequences baked into `pull_requests.py`:

- results cached in memory for 120s (a cold sweep measured 3.2–7.8s)
- diff stats (`additions`/`deletions`) only exist on the single-PR endpoint, so
  enrichment is capped at 8 PRs unauthenticated / 20 authenticated
- when search 403s, the per-repo sweep still returns every open PR, and the
  response keeps `error` populated so the UI can say *why* the list is degraded
  instead of silently showing partial data

## Mobile PWA: layout facts worth keeping

- `font-size: 16px` on inputs is mandatory — anything smaller makes iOS Safari
  and Android Chrome zoom the viewport on focus
- the old stacked PWA header burned ~240px of an 844px viewport; collapsing it
  to one 48px row (badge + "Online" word hidden) is what made the list usable
- `env(safe-area-inset-bottom)` only matters if `viewport-fit=cover` is on the
  `<meta name="viewport">` tag, otherwise the inset resolves to 0
- the service worker is registered with `scope: '/pwa/'`, so it only controls
  `/pwa/*`. Offline PR data works inside the PWA shell, but `/pull-requests`
  and `/wayfinder` are not covered (widening the scope needs a
  `Service-Worker-Allowed` header and re-audits the cache-first navigation
  handler — deliberately not done)
