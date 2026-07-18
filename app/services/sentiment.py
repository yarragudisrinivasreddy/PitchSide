"""Sentiment analysis for incident reports via Cloud Natural Language.

The sentiment score feeds the deterministic severity matrix in
:mod:`app.domain.incident_rules`.  On any upstream failure the analyser
returns a neutral score so triage still completes using categories and
keywords alone.
"""

from __future__ import annotations

import logging

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import language_v1

from app.services.base import GoogleClientService

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)

NEUTRAL_SCORE = 0.0


class SentimentLens(GoogleClientService):
    """Thin wrapper around Cloud Natural Language sentiment analysis."""

    def _build_client(self) -> language_v1.LanguageServiceClient:
        """Create the Natural Language client."""
        return language_v1.LanguageServiceClient()

    def score(self, text: str) -> float:
        """Sentiment score in [-1, 1]; neutral on any upstream failure."""
        try:
            client = self._ensure_client()
            document = language_v1.Document(
                content=text, type_=language_v1.Document.Type.PLAIN_TEXT
            )
            response = client.analyze_sentiment(request={"document": document})
            return float(response.document_sentiment.score)
        except UPSTREAM_FAILURES as exc:
            LOGGER.warning("Sentiment fallback engaged: %s", exc)
            return NEUTRAL_SCORE
