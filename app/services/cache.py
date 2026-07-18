"""Small TTL cache for operations insights with prefix invalidation.

Every write endpoint (crowd reports, incidents) invalidates the ``ops:``
prefix so the organizer dashboard always reflects the latest ledger state
while repeated reads within the TTL stay cheap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import INSIGHT_CACHE_TTL_SECONDS


@dataclass
class InsightCache:
    """Process-local key/value cache with TTL and prefix invalidation."""

    ttl_seconds: float = INSIGHT_CACHE_TTL_SECONDS
    _store: dict[str, tuple[float, object]] = field(default_factory=dict)

    def get(self, key: str) -> object | None:
        """Return a cached value or ``None`` when absent or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.time() - stored_at > self.ttl_seconds:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: object) -> None:
        """Store a value with the current timestamp."""
        self._store[key] = (time.time(), value)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key starting with ``prefix``; return the count."""
        doomed = [key for key in self._store if key.startswith(prefix)]
        for key in doomed:
            del self._store[key]
        return len(doomed)
