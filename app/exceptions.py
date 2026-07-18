"""Typed exception hierarchy for PitchSide.

Every domain and service failure maps to a subclass of :class:`PitchSideError`
so the application factory can register a single JSON error handler.  HTTP
status codes live on the exception class, keeping route handlers thin.
"""

from __future__ import annotations


class PitchSideError(Exception):
    """Base class for all application-level errors."""

    status_code = 500
    message = "An internal error occurred."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message

    def to_payload(self) -> dict:
        """Serialise the error for JSON responses."""
        return {"error": type(self).__name__, "message": self.message}


class ValidationError(PitchSideError):
    """Raised when client input fails validation at the API boundary."""

    status_code = 400
    message = "Invalid request payload."


class RoutingError(PitchSideError):
    """Raised when the venue graph cannot satisfy a routing request."""

    status_code = 422
    message = "No viable route could be computed."


class InterpretationError(PitchSideError):
    """Raised when free-text input cannot be interpreted at all."""

    status_code = 422
    message = "The request could not be interpreted."


class TranslationError(PitchSideError):
    """Raised when response translation fails irrecoverably."""

    status_code = 502
    message = "Translation service is unavailable."


class LedgerError(PitchSideError):
    """Raised when the event ledger cannot persist or read records."""

    status_code = 503
    message = "Event ledger is unavailable."


class SentimentError(PitchSideError):
    """Raised when sentiment analysis fails irrecoverably."""

    status_code = 502
    message = "Sentiment analysis is unavailable."


class ArchiveError(PitchSideError):
    """Raised when the operations archive cannot store a snapshot."""

    status_code = 502
    message = "Archive storage is unavailable."


class SecretAccessError(PitchSideError):
    """Raised when a required secret cannot be resolved."""

    status_code = 500
    message = "A required secret could not be resolved."
