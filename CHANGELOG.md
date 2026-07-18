# Changelog

All notable changes to PitchSide are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.1] - 2026-07-18

### Changed
- City-leg endpoints now default to real FIFA World Cup 2026 addresses
  (MetLife Stadium → Times Square, env-overridable per venue) so the Routes
  API resolves live routes; TRANSIT is attempted first with an automatic
  DRIVE retry, and the response now includes `travel_mode`.
- Test suite grown to 210 tests.

## [1.1.0] - 2026-07-18

### Added
- Google Maps Platform (Routes API) city-leg enrichment on transit plans:
  live stadium-to-city transit routing when a Maps key is present (resolved
  via Secret Manager), deterministic estimate otherwise.
- Static type checking: mypy configuration, full annotations, `py.typed`.
- `SECURITY.md` security policy; request-body size cap
  (`MAX_CONTENT_LENGTH` 64 KiB); uniform JSON 405/413 error envelopes.
- Right-to-left rendering for Arabic responses and a dynamic `lang`
  attribute on the results region.

### Changed
- Test suite grown to 207 tests at 99.4% coverage.

## [1.0.0] - 2026-07-18

### Added
- Deterministic `VenueGraph` with Dijkstra routing and accessibility-aware
  (`step_free`) edges, including a step-free-only routing mode.
- `ZoneLoadRegistry`: time-decayed crowd density scoring and documented
  service-rate wait-time estimation per zone.
- `TransitPlanner`: staggered post-match departure waves and per-mode carbon
  comparison with sourced emission factors.
- Incident triage severity matrix (P1/P2/P3) with keyword escalators,
  sentiment adjustment and dispatch action mapping.
- Gemini 2.5 Flash intent interpretation and narrative composition through a
  single `VertexGateway`, with deterministic heuristic/template fallbacks.
- Full-response translation across en/es/fr/pt/ar/de/hi via Cloud
  Translate v3 (`translate_json_values`).
- Firestore event ledger behind a structural `EventLedger` Protocol with an
  in-memory mirror; operations-insight cache invalidated on every write.
- Cloud Storage snapshot archiving, Secret Manager access with environment
  fallback, Cloud Natural Language sentiment.
- Accessible single-page UI (WCAG 2.1 AA), organizer operations dashboard.
- 193 tests at 99% coverage; pylint 10.00; no C-grade complexity.
