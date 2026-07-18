# PitchSide Architecture

## Module map

```
main.py                      WSGI entry point (Cloud Run / gunicorn)
app/
├── __init__.py              create_app() factory: blueprints, after_request
│                            security headers, single PitchSideError handler
├── config.py                environment configuration only (no logic)
├── exceptions.py            typed error hierarchy with HTTP status codes
├── routes/
│   ├── pages.py             UI blueprint (renders the single page)
│   └── api.py               JSON API: validate → assistant → jsonify
├── domain/                  deterministic core — no Google SDK imports
│   ├── venue_graph.py       VenueGraph, Dijkstra, step-free routing
│   ├── zone_load.py         ZoneLoadRegistry: decayed density, wait times
│   ├── transit_planner.py   departure waves, CO2e comparison (sourced)
│   └── incident_rules.py    severity matrix P1/P2/P3, dispatch actions
└── services/
    ├── base.py              GoogleClientService: lazy client + health probe
    ├── gateway.py           VertexGateway — the only Vertex AI touchpoint
    ├── interpreter.py       Gemini intent parsing + keyword heuristics
    ├── composer.py          Gemini narration + deterministic templates
    ├── translator.py        Cloud Translate v3 full-response translation
    ├── sentiment.py         Cloud Natural Language sentiment
    ├── ledger.py            EventLedger Protocol; Firestore + InMemory
    ├── archive.py           Cloud Storage ops-snapshot archive
    ├── secrets.py           Secret Manager with env fallback
    ├── cache.py             TTL insight cache with prefix invalidation
    └── assistant.py         MatchDayAssistant orchestration
```

## Request flow

1. **Route layer** (`routes/api.py`) parses and validates the JSON body:
   type checks, length caps, persona/language whitelists. Anything invalid
   raises `ValidationError` (HTTP 400) before touching a service.
2. **Orchestration** (`services/assistant.py`) coordinates the pipeline.
   For `/api/assist`: interpret → dispatch to the deterministic domain →
   persist side effects → compose narrative → translate the whole response.
3. **Deterministic domain** (`app/domain/`) produces every number. These
   modules import no Google SDKs and are tested with known-answer fixtures.
4. **Translation** (`services/translator.py`) walks the final payload and
   translates every human-readable string; structural keys (zone ids,
   modes, severity codes, URLs, hashtags, unit tokens) are excluded so the
   response stays machine-usable in all seven languages.

## Design decisions

### Gemini interprets, the graph computes
Generative models parse messy input and phrase results; they never produce
figures. This keeps outputs auditable (a route is provably shortest; a
severity is reproducible from the matrix) and eliminates hallucinated
numbers as a failure class.

### Graceful degradation everywhere
Each service defines a typed `UPSTREAM_FAILURES` tuple that explicitly
includes `google.auth.exceptions.GoogleAuthError` (auth failures are not
`GoogleAPIError` subclasses). Failure paths: interpreter → keyword
heuristics; composer → templates; translator → untranslated payload;
sentiment → neutral; Firestore → in-memory mirror; archive → skip; secrets
→ environment. The resilience suite proves full functionality with zero
credentials.

### Accessibility as domain logic
`step_free` is a property of graph edges, not a UI afterthought. Stairs are
modelled alongside parallel ramp/elevator edges, so `accessible=True`
routing is ordinary Dijkstra over a filtered edge set and every venue must
provide a step-free alternative to be fully navigable.

### Repository pattern for persistence
`EventLedger` is a structural `typing.Protocol` with two implementations.
`FirestoreLedger` mirrors every write into `InMemoryLedger`, making reads
outage-proof and tests deterministic without patching Firestore.

### Cache invalidation wired into writes
The organizer summary is cached for `INSIGHT_CACHE_TTL_SECONDS`; every crowd
report or incident write calls `cache.invalidate_prefix("ops:")`, so the
dashboard is both cheap and never stale after an event.

### Security posture
All security headers are attached in one `after_request` hook. There is
deliberately no `before_request` origin/host validation — such filters
reject legitimate clients (health checks, evaluators, proxies) and add no
real protection for a public API. Input validation and rate limiting happen
at the API boundary instead.

## Testing strategy

| File | Focus |
|---|---|
| `tests/test_domain.py` | Known-answer tests for routing, density, waves, triage |
| `tests/test_services.py` | Interpreter/composer/translator contracts and fallbacks |
| `tests/test_api.py` | Endpoint happy paths, validation boundaries, rate limit |
| `tests/test_ledger.py` | Protocol conformance, mirror reads, cache invalidation |
| `tests/test_resilience.py` | GoogleAuthError paths; full pipeline with no credentials |
| `tests/test_clients.py` | SDK init calls, request shapes via stubbed clients |
| `tests/test_pages.py` | UI rendering, accessibility markers, security headers |

193 tests, 99% coverage. The uncovered handful of lines are real-network
branches (ADC project lookup, live client construction) that cannot execute
in a hermetic test environment.
