"""Environment-driven configuration for PitchSide.

This module reads environment variables only.  It contains no exception
handling and no credential logic by design: credential resolution lives in
:mod:`app.services.gateway` and secret access in :mod:`app.services.secrets`.
"""

from __future__ import annotations

import os

#: Google Cloud region used for Vertex AI and Cloud Run deployment.
REGION = os.environ.get("PITCHSIDE_REGION", "asia-south1")

#: Gemini model powering interpretation and narrative composition.
MODEL_NAME = os.environ.get("PITCHSIDE_MODEL", "gemini-2.5-flash")

#: Languages offered in the UI, themed for FIFA World Cup 2026 host and
#: visiting audiences.  BCP-47 codes accepted by Cloud Translate v3.
SUPPORTED_LANGUAGES = ("en", "es", "fr", "pt", "ar", "de", "hi")

#: Default language when a request omits one.
DEFAULT_LANGUAGE = "en"

#: Firestore collection names.
REPORTS_COLLECTION = os.environ.get("PITCHSIDE_REPORTS_COLLECTION", "crowd_reports")
INCIDENTS_COLLECTION = os.environ.get("PITCHSIDE_INCIDENTS_COLLECTION", "incidents")

#: Cloud Storage bucket for daily operations-log archives.
ARCHIVE_BUCKET = os.environ.get("PITCHSIDE_ARCHIVE_BUCKET", "")

#: Maximum accepted length for free-text fields, enforced at the API boundary.
MAX_TEXT_LENGTH = 2000

#: Hard cap on request body size (bytes), enforced by Flask before parsing.
MAX_REQUEST_BYTES = 64 * 1024

#: Real-world endpoints for the Routes API city leg.  Defaults model the
#: FIFA World Cup 2026 final venue (MetLife Stadium) to Midtown Manhattan —
#: a live NJ Transit corridor — and can be overridden per deployment.
CITY_LEG_ORIGIN = os.environ.get(
    "PITCHSIDE_CITY_ORIGIN", "MetLife Stadium, East Rutherford, NJ"
)
CITY_LEG_DESTINATION = os.environ.get(
    "PITCHSIDE_CITY_DESTINATION", "Times Square, Manhattan, New York, NY"
)

#: Generous per-client rate limit (requests per minute) for API endpoints.
RATE_LIMIT_PER_MINUTE = int(os.environ.get("PITCHSIDE_RATE_LIMIT", "240"))

#: Seconds a cached operations insight remains valid before recomputation.
INSIGHT_CACHE_TTL_SECONDS = int(os.environ.get("PITCHSIDE_CACHE_TTL", "30"))
