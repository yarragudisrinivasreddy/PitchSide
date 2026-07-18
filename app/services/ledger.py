"""Event ledger: crowd reports and incidents behind a structural Protocol.

Two interchangeable implementations satisfy :class:`EventLedger`:

* :class:`FirestoreLedger` — durable storage in Firestore, mirroring every
  write into an in-memory ledger so reads survive upstream outages.
* :class:`InMemoryLedger` — deterministic storage for tests and for
  credential-free environments.

:func:`build_ledger` selects the best available implementation at startup
without ever raising.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Protocol, runtime_checkable

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import firestore

from app.config import INCIDENTS_COLLECTION, REPORTS_COLLECTION
from app.services.base import GoogleClientService

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)


@runtime_checkable
class EventLedger(Protocol):
    """Structural interface for report and incident persistence."""

    def add_report(self, record: dict) -> str:
        """Persist a crowd report; return its id."""

    def add_incident(self, record: dict) -> str:
        """Persist an incident; return its id."""

    def recent_reports(self, limit: int = 50) -> list[dict]:
        """Most recent crowd reports, newest first."""

    def open_incidents(self, limit: int = 50) -> list[dict]:
        """Most recent incidents, newest first."""


class InMemoryLedger:
    """Deterministic, process-local ledger."""

    def __init__(self) -> None:
        self._reports: list[dict] = []
        self._incidents: list[dict] = []

    @staticmethod
    def _stamp(record: dict) -> dict:
        """Attach id and timestamp to a record copy."""
        stamped = dict(record)
        stamped.setdefault("id", uuid.uuid4().hex)
        stamped.setdefault("created_at", time.time())
        return stamped

    def add_report(self, record: dict) -> str:
        """Persist a crowd report; return its id."""
        stamped = self._stamp(record)
        self._reports.append(stamped)
        return stamped["id"]

    def add_incident(self, record: dict) -> str:
        """Persist an incident; return its id."""
        stamped = self._stamp(record)
        self._incidents.append(stamped)
        return stamped["id"]

    def recent_reports(self, limit: int = 50) -> list[dict]:
        """Most recent crowd reports, newest first."""
        return list(reversed(self._reports[-limit:]))

    def open_incidents(self, limit: int = 50) -> list[dict]:
        """Most recent incidents, newest first."""
        return list(reversed(self._incidents[-limit:]))


class FirestoreLedger(GoogleClientService):
    """Firestore-backed ledger with an in-memory read mirror."""

    def __init__(self) -> None:
        super().__init__()
        self._mirror = InMemoryLedger()

    def _build_client(self) -> firestore.Client:
        """Create the Firestore client."""
        return firestore.Client()

    def _write(self, collection: str, record: dict) -> None:
        """Write a record to Firestore, tolerating upstream failure."""
        try:
            client = self._ensure_client()
            client.collection(collection).document(record["id"]).set(record)
        except UPSTREAM_FAILURES as exc:
            LOGGER.warning("Firestore write degraded to mirror only: %s", exc)

    def add_report(self, record: dict) -> str:
        """Persist a crowd report; return its id."""
        record_id = self._mirror.add_report(record)
        stored = self._mirror.recent_reports(limit=1)[0]
        self._write(REPORTS_COLLECTION, stored)
        return record_id

    def add_incident(self, record: dict) -> str:
        """Persist an incident; return its id."""
        record_id = self._mirror.add_incident(record)
        stored = self._mirror.open_incidents(limit=1)[0]
        self._write(INCIDENTS_COLLECTION, stored)
        return record_id

    def recent_reports(self, limit: int = 50) -> list[dict]:
        """Most recent crowd reports from the mirror (outage-proof reads)."""
        return self._mirror.recent_reports(limit=limit)

    def open_incidents(self, limit: int = 50) -> list[dict]:
        """Most recent incidents from the mirror (outage-proof reads)."""
        return self._mirror.open_incidents(limit=limit)



def build_ledger() -> EventLedger:
    """Choose Firestore when constructible, otherwise stay in memory."""
    try:
        ledger = FirestoreLedger()
        ledger.is_healthy()
        return ledger
    except UPSTREAM_FAILURES as exc:  # pragma: no cover - defensive
        LOGGER.warning("Falling back to in-memory ledger: %s", exc)
        return InMemoryLedger()
