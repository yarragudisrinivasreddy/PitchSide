"""Single gateway to Vertex AI generative models.

This is the only module in the codebase that imports or initialises the
Vertex AI SDK.  Both ``vertexai.init`` and ``aiplatform.init`` are called so
the generative stack and the platform SDK share one explicit project/region
configuration.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import google.auth
from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import aiplatform
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from app.config import MODEL_NAME, REGION

LOGGER = logging.getLogger(__name__)

#: Failure types after which the caller must degrade gracefully.  Auth errors
#: are not GoogleAPIError subclasses, so they are listed explicitly.
UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)


@lru_cache(maxsize=1)
def resolve_project_id() -> str:
    """Resolve the active Google Cloud project id, cached for the process.

    Preference order: explicit environment variable, then Application
    Default Credentials.  During test runs (``PYTEST_CURRENT_TEST`` set) the
    environment variable path is used exclusively so no network lookup
    happens.
    """
    explicit = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if explicit or os.environ.get("PYTEST_CURRENT_TEST"):
        return explicit or "test-project"
    _, project_id = google.auth.default()
    return project_id or ""


class VertexGateway:
    """Lazily-initialised wrapper around a Gemini generative model."""

    def __init__(self) -> None:
        self._model: GenerativeModel | None = None

    def _ensure_model(self) -> GenerativeModel:
        """Initialise the SDKs and model on first use."""
        if self._model is None:
            project_id = resolve_project_id()
            vertexai.init(project=project_id, location=REGION)
            aiplatform.init(project=project_id, location=REGION)
            self._model = GenerativeModel(MODEL_NAME)
        return self._model

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        """Generate text for a prompt.

        Raises members of :data:`UPSTREAM_FAILURES` on upstream problems;
        callers are responsible for deterministic fallbacks.
        """
        model = self._ensure_model()
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(temperature=temperature),
        )
        text = getattr(response, "text", "") or ""
        if not text.strip():
            raise RuntimeError("Empty response from generative model.")
        return text

    def is_healthy(self) -> bool:
        """Best-effort availability probe that never raises."""
        try:
            self._ensure_model()
            return True
        except Exception:  # pragma: no cover  # pylint: disable=broad-exception-caught
            return False
