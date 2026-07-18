"""Shared base for lazily-constructed Google Cloud client services.

Each service builds its client on first use and exposes a uniform,
never-raising :meth:`is_healthy` probe used by the ``/api/health`` endpoint.
"""

from __future__ import annotations

from typing import Any


class GoogleClientService:
    """Lazy client holder with a uniform health probe."""

    def __init__(self) -> None:
        self._client: Any = None

    def _build_client(self) -> Any:
        """Construct the concrete client.  Subclasses must override."""
        raise NotImplementedError

    def _ensure_client(self) -> Any:
        """Create the client on first use and cache it."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def is_healthy(self) -> bool:
        """Best-effort availability probe that never raises.

        This is the one sanctioned broad-except boundary in the codebase:
        a health probe must swallow every failure mode, including missing
        credentials, and report ``False`` instead of propagating.
        """
        try:
            self._ensure_client()
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False
