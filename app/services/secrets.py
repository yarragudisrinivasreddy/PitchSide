"""Secret resolution: Secret Manager first, environment fallback always.

No secret value is ever hard-coded.  When Secret Manager is unreachable or
the secret is absent, the environment variable of the same name (uppercased)
is used, then the caller-provided default.
"""

from __future__ import annotations

import logging
import os

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import secretmanager

from app.services.base import GoogleClientService
from app.services.gateway import resolve_project_id

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)


class SecretVault(GoogleClientService):
    """Reads secrets with layered fallbacks and no hard failures."""

    def _build_client(self) -> secretmanager.SecretManagerServiceClient:
        """Create the Secret Manager client."""
        return secretmanager.SecretManagerServiceClient()

    def get(self, name: str, default: str = "") -> str:
        """Resolve a secret by name with env-var and default fallbacks."""
        try:
            client = self._ensure_client()
            path = (
                f"projects/{resolve_project_id()}/secrets/{name}/versions/latest"
            )
            response = client.access_secret_version(request={"name": path})
            return response.payload.data.decode("utf-8")
        except UPSTREAM_FAILURES as exc:
            LOGGER.info("Secret '%s' falling back to environment: %s", name, exc)
            return os.environ.get(name.upper(), default)
