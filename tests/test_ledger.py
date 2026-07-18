"""Ledger Protocol conformance and cache invalidation tests."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

from app.services.archive import ArchiveVault
from app.services.cache import InsightCache
from app.services.ledger import EventLedger, FirestoreLedger, InMemoryLedger
from tests.conftest import build_assistant


class TestInMemoryLedger:
    """Behaviour of the deterministic ledger."""

    def setup_method(self) -> None:
        """Fresh ledger for each test."""
        self.ledger = InMemoryLedger()

    def test_add_report_returns_id(self):
        """Add report returns id."""
        record_id = self.ledger.add_report({"zone": "north", "level": "high"})
        assert isinstance(record_id, str) and record_id

    def test_recent_reports_newest_first(self):
        """Recent reports newest first."""
        self.ledger.add_report({"zone": "a"})
        self.ledger.add_report({"zone": "b"})
        reports = self.ledger.recent_reports()
        assert reports[0]["zone"] == "b"

    def test_recent_reports_respects_limit(self):
        """Recent reports respects limit."""
        for index in range(10):
            self.ledger.add_report({"zone": str(index)})
        assert len(self.ledger.recent_reports(limit=3)) == 3

    def test_incidents_are_separate_from_reports(self):
        """Incidents are separate from reports."""
        self.ledger.add_report({"zone": "north"})
        self.ledger.add_incident({"severity": "P1"})
        assert len(self.ledger.recent_reports()) == 1
        assert len(self.ledger.open_incidents()) == 1

    def test_records_are_stamped(self):
        """Records are stamped."""
        self.ledger.add_incident({"severity": "P2"})
        stored = self.ledger.open_incidents()[0]
        assert "id" in stored and "created_at" in stored

    def test_caller_id_preserved(self):
        """Caller id preserved."""
        self.ledger.add_report({"id": "fixed", "zone": "north"})
        assert self.ledger.recent_reports()[0]["id"] == "fixed"


class TestProtocolConformance:
    """Both implementations satisfy the structural EventLedger Protocol."""

    def test_in_memory_satisfies_protocol(self):
        """In memory satisfies protocol."""
        assert isinstance(InMemoryLedger(), EventLedger)

    def test_firestore_satisfies_protocol(self):
        """Firestore satisfies protocol."""
        assert isinstance(FirestoreLedger(), EventLedger)

    def test_firestore_reads_serve_from_mirror(self):
        """Firestore reads serve from mirror."""
        ledger = FirestoreLedger()
        ledger.add_report({"zone": "north", "level": "low"})
        assert ledger.recent_reports()[0]["zone"] == "north"

    def test_firestore_write_survives_outage(self):
        """Firestore write survives outage."""
        ledger = FirestoreLedger()
        record_id = ledger.add_incident({"severity": "P3"})
        assert record_id
        assert ledger.open_incidents()[0]["id"] == record_id


class TestInsightCache:
    """TTL semantics and prefix invalidation."""

    def test_set_then_get(self):
        """Set then get."""
        cache = InsightCache()
        cache.set("ops:summary", {"value": 1})
        assert cache.get("ops:summary") == {"value": 1}

    def test_missing_key_is_none(self):
        """Missing key is none."""
        assert InsightCache().get("nothing") is None

    def test_expired_entry_is_none(self):
        """Expired entry is none."""
        cache = InsightCache(ttl_seconds=0.0)
        cache.set("ops:summary", 1)
        assert cache.get("ops:summary") is None

    def test_invalidate_prefix_counts(self):
        """Invalidate prefix counts."""
        cache = InsightCache()
        cache.set("ops:a", 1)
        cache.set("ops:b", 2)
        cache.set("other", 3)
        assert cache.invalidate_prefix("ops:") == 2
        assert cache.get("other") == 3

    def test_crowd_report_invalidates_ops_cache(self):
        """Crowd report invalidates ops cache."""
        assistant = build_assistant()
        first = assistant.ops_summary()
        assert assistant.cache.get("ops:summary") is not None
        assistant.record_crowd_report("south", "critical")
        assert assistant.cache.get("ops:summary") is None
        refreshed = assistant.ops_summary()
        assert refreshed != first

    def test_incident_invalidates_ops_cache(self):
        """Incident invalidates ops cache."""
        assistant = build_assistant()
        assistant.ops_summary()
        assistant.record_incident("medical", "fan is unconscious")
        assert assistant.cache.get("ops:summary") is None

    def test_ops_summary_served_from_cache_between_writes(self):
        """Ops summary served from cache between writes."""
        assistant = build_assistant()
        first = assistant.ops_summary()
        second = assistant.ops_summary()
        assert first is second


class TestArchiveHealthProbe:
    """Archive client construction path executes safely."""

    def test_archive_health_probe_is_boolean(self):
        """Archive health probe is boolean."""
        assert isinstance(ArchiveVault().is_healthy(), bool)
