# Security Policy

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository or contact
the maintainer directly. Reports are acknowledged within 48 hours.

## Security posture

- **Transport & headers**: CSP, HSTS, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`
  applied to every response in a single `after_request` hook.
- **Input handling**: strict JSON-shape validation, type checks, length caps
  (`MAX_TEXT_LENGTH`), request-body size cap (`MAX_CONTENT_LENGTH` 64 KiB),
  persona and language whitelists. Uniform JSON error envelopes for
  400/404/405/413/422/429 — no stack traces are ever exposed.
- **Rate limiting**: per-client in-memory limiter (240 req/min) with a
  documented Redis/Memorystore path for multi-instance deployments.
- **Secrets**: no secrets in code or repository; Google Secret Manager with
  environment fallback; `.env` is gitignored.
- **Container**: multi-stage build, non-root runtime user, no build tools in
  the final image.
- **Dependencies**: pinned versions in `requirements.txt`; dev tooling split
  into `requirements-dev.txt`.

## Scope notes

The service is a public, unauthenticated demo by challenge design; it stores
no personal data. Crowd and incident reports are free text and are length-
capped and rendered as text only (no HTML interpolation).
