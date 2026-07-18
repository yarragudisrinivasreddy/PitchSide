"""Daily operations-log archiving to Cloud Storage.

Archiving is best-effort by design: a missing bucket or missing credentials
must never degrade the live match-day experience, so failures log a warning
and return ``False``.
"""

from __future__ import annotations

import json
import logging
import time

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import storage  # type: ignore[attr-defined]

from app.config import ARCHIVE_BUCKET
from app.services.base import GoogleClientService

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)


class ArchiveVault(GoogleClientService):
    """Best-effort snapshot writer for operations summaries."""

    def _build_client(self) -> storage.Client:
        """Create the Cloud Storage client."""
        return storage.Client()

    def archive_snapshot(self, snapshot: dict) -> bool:
        """Store a JSON snapshot; returns ``True`` only on success."""
        if not ARCHIVE_BUCKET:
            LOGGER.info("Archive skipped: no bucket configured.")
            return False
        try:
            client = self._ensure_client()
            bucket = client.bucket(ARCHIVE_BUCKET)
            name = f"ops-snapshots/{time.strftime('%Y-%m-%d')}/{int(time.time())}.json"
            bucket.blob(name).upload_from_string(
                json.dumps(snapshot, default=str),
                content_type="application/json",
            )
            return True
        except UPSTREAM_FAILURES as exc:
            LOGGER.warning("Archive skipped: %s", exc)
            return False
