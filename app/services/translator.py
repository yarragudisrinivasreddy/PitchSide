"""Full-response translation via Cloud Translate v3.

The critical contract: :func:`translate_json_values` recursively translates
*every* human-readable string value in the response payload — not merely an
echo of the input.  Structural values are excluded so the API remains
machine-usable in any language:

* keys listed in :data:`EXCLUDED_KEYS` (identifiers, codes, modes);
* hashtags (``#BuildWithAI`` stays platform-native);
* URLs;
* unit-like short tokens (e.g. ``P1``, ``m``, ``gCO2e``).
"""

from __future__ import annotations

import logging
import re

from google.api_core import exceptions as gapi_exceptions
from google.auth import exceptions as gauth_exceptions
from google.cloud import translate_v3

from app.config import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from app.services.base import GoogleClientService
from app.services.gateway import resolve_project_id

LOGGER = logging.getLogger(__name__)

UPSTREAM_FAILURES = (
    gapi_exceptions.GoogleAPIError,
    gauth_exceptions.GoogleAuthError,
    ValueError,
    RuntimeError,
)

#: Keys whose values are structural and must never be translated.
EXCLUDED_KEYS = frozenset(
    {
        "zone", "mode", "modes", "intent", "language", "source", "severity",
        "category", "node_id", "from", "to", "id", "width_class",
        "greenest_mode", "lowest_carbon_transit_mode", "error",
    }
)

_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
_UNIT_PATTERN = re.compile(r"^[A-Za-z]{1,2}\d*$|^[a-z]*CO2e?$")


def _is_translatable(key: str | None, value: str) -> bool:
    """Decide whether a string value should be sent for translation."""
    if key in EXCLUDED_KEYS:
        return False
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if _URL_PATTERN.match(stripped) or _UNIT_PATTERN.match(stripped):
        return False
    return True


class ResponseTranslator(GoogleClientService):
    """Translates whole response payloads with graceful degradation."""

    def _build_client(self) -> translate_v3.TranslationServiceClient:
        """Create the Translate v3 client."""
        return translate_v3.TranslationServiceClient()

    @staticmethod
    def validate_language(language: str | None) -> str:
        """Return a supported language code, defaulting to English."""
        code = (language or DEFAULT_LANGUAGE).strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language '{language}'.")
        return code

    def translate_json_values(
        self, payload: object, target_language: str, _key: str | None = None
    ) -> object:
        """Recursively translate every translatable string in ``payload``.

        Lists and dicts are walked; excluded keys, hashtags, URLs and unit
        tokens pass through untouched.  On upstream failure the original
        payload is returned unchanged so responses always succeed.
        """
        if target_language == DEFAULT_LANGUAGE:
            return payload
        try:
            return self._walk(payload, target_language, _key)
        except UPSTREAM_FAILURES as exc:
            LOGGER.warning("Translation fallback engaged: %s", exc)
            return payload

    def _walk(self, payload: object, target_language: str, key: str | None) -> object:
        """Depth-first traversal performing per-string translation."""
        if isinstance(payload, dict):
            return {
                child_key: self._walk(value, target_language, child_key)
                for child_key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._walk(item, target_language, key) for item in payload]
        if isinstance(payload, str) and _is_translatable(key, payload):
            return self._translate_text(payload, target_language)
        return payload

    def _translate_text(self, text: str, target_language: str) -> str:
        """Translate one string via Cloud Translate v3."""
        client = self._ensure_client()
        parent = f"projects/{resolve_project_id()}/locations/global"
        response = client.translate_text(
            request={
                "parent": parent,
                "contents": [text],
                "mime_type": "text/plain",
                "source_language_code": DEFAULT_LANGUAGE,
                "target_language_code": target_language,
            }
        )
        translations = list(response.translations)
        if not translations:
            raise RuntimeError("Translate v3 returned no translations.")
        return translations[0].translated_text
