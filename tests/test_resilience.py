"""Resilience tests: every upstream failure path degrades gracefully.

The application must stay fully functional with zero Google credentials.
Each test injects ``GoogleAuthError`` (which is *not* a GoogleAPIError
subclass) or a runtime failure and asserts the feature still answers.
"""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

from google.auth.exceptions import GoogleAuthError

from app.services.archive import ArchiveVault
from app.services.composer import NarrativeComposer
from app.services.interpreter import IntentInterpreter
from app.services.ledger import FirestoreLedger
from app.services.secrets import SecretVault
from app.services.sentiment import SentimentLens
from app.services.translator import ResponseTranslator
from tests.conftest import build_assistant


class AuthFailingGateway:
    """Gateway raising auth errors, the credential-free failure mode."""

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        """Simulate missing Application Default Credentials."""
        raise GoogleAuthError("could not determine credentials")

    def is_healthy(self) -> bool:
        """Report unavailable."""
        return False


def _raise_auth(*_args, **_kwargs):
    """Helper that raises GoogleAuthError for monkeypatching."""
    raise GoogleAuthError("could not determine credentials")


class TestAuthErrorPaths:
    """GoogleAuthError never escapes a service boundary."""

    def test_interpreter_survives_auth_error(self):
        """Interpreter survives auth error."""
        parsed = IntentInterpreter(gateway=AuthFailingGateway()).parse(
            "route to section 114", "fan"
        )
        assert parsed["source"] == "heuristic"

    def test_composer_survives_auth_error(self):
        """Composer survives auth error."""
        text = NarrativeComposer(gateway=AuthFailingGateway()).compose(
            "route_request", {}, "fan"
        )
        assert text

    def test_translator_survives_auth_error(self, monkeypatch):
        """Translator survives auth error."""
        translator = ResponseTranslator()
        monkeypatch.setattr(translator, "_translate_text", _raise_auth)
        payload = {"guidance": "Turn left"}
        assert translator.translate_json_values(payload, "es") == payload

    def test_sentiment_survives_auth_error(self, monkeypatch):
        """Sentiment survives auth error."""
        lens = SentimentLens()
        monkeypatch.setattr(lens, "_ensure_client", _raise_auth)
        assert lens.score("angry words") == 0.0

    def test_secret_vault_survives_auth_error(self, monkeypatch):
        """Secret vault survives auth error."""
        vault = SecretVault()
        monkeypatch.setattr(vault, "_ensure_client", _raise_auth)
        monkeypatch.delenv("ABSENT", raising=False)
        assert vault.get("absent", default="ok") == "ok"

    def test_firestore_write_survives_auth_error(self, monkeypatch):
        """Firestore write survives auth error."""
        ledger = FirestoreLedger()
        monkeypatch.setattr(ledger, "_ensure_client", _raise_auth)
        record_id = ledger.add_report({"zone": "north"})
        assert ledger.recent_reports()[0]["id"] == record_id

    def test_archive_survives_auth_error(self, monkeypatch):
        """Archive survives auth error."""
        vault = ArchiveVault()
        monkeypatch.setattr(vault, "_ensure_client", _raise_auth)
        monkeypatch.setattr("app.services.archive.ARCHIVE_BUCKET", "bucket")
        assert vault.archive_snapshot({"zones": []}) is False

    def test_archive_skips_without_bucket(self):
        """Archive skips without bucket."""
        assert ArchiveVault().archive_snapshot({"zones": []}) is False


class TestFullPipelineWithoutCredentials:
    """End-to-end behaviour with every upstream failing."""

    def test_assist_pipeline_answers_offline(self):
        """Assist pipeline answers offline."""
        assistant = build_assistant(gateway=AuthFailingGateway())
        response = assistant.assist(
            "wheelchair route from gate a to section 201", "fan", "en"
        )
        assert response["source"] == "heuristic"
        assert response["result"]["fully_step_free"] is True
        assert response["guidance"]

    def test_incident_pipeline_answers_offline(self):
        """Incident pipeline answers offline."""
        assistant = build_assistant(gateway=AuthFailingGateway())
        response = assistant.assist(
            "someone is unconscious at gate c", "staff", "en"
        )
        assert response["result"]["severity"] == "P1"

    def test_health_reports_status_without_raising(self):
        """Health reports status without raising."""
        assistant = build_assistant(gateway=AuthFailingGateway())
        health = assistant.health()
        assert health["app"] is True
        assert set(health) >= {
            "vertex_ai",
            "translate",
            "firestore",
            "natural_language",
            "storage",
            "secret_manager",
        }
