"""Tests for Google client wiring: init calls, request shapes, fallbacks.

These tests stub the SDK clients at the module boundary so the exact
initialisation and request construction paths run without credentials.
"""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

import json

import pytest

from app.services import gateway as gateway_module
from app.services import ledger as ledger_module
from app.services.archive import ArchiveVault
from app.services.gateway import VertexGateway, resolve_project_id
from app.services.interpreter import IntentInterpreter
from app.services.ledger import build_ledger
from app.services.secrets import SecretVault
from app.services.sentiment import SentimentLens
from app.services.translator import ResponseTranslator
from tests.conftest import ScriptedGateway


class _Recorder:
    """Records keyword arguments passed to an init function."""

    def __init__(self) -> None:
        """Stub behaviour for the wired client path."""
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> None:
        """Stub behaviour for the wired client path."""
        self.calls.append(kwargs)


class TestResolveProjectId:
    """Project resolution honours env vars and test mode."""

    def setup_method(self) -> None:
        """Clear the lru_cache between tests."""
        resolve_project_id.cache_clear()

    def teardown_method(self) -> None:
        """Leave no cached value behind."""
        resolve_project_id.cache_clear()

    def test_explicit_env_var_wins(self, monkeypatch):
        """Explicit env var wins."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "wc26-project")
        assert resolve_project_id() == "wc26-project"

    def test_pytest_mode_never_hits_network(self, monkeypatch):
        """Pymode never hits network."""
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        assert resolve_project_id() == "test-project"

    def test_result_is_cached(self, monkeypatch):
        """Result is cached."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "first")
        assert resolve_project_id() == "first"
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "second")
        assert resolve_project_id() == "first"


class TestVertexGateway:
    """SDK initialisation and generation via a stubbed model."""

    def _wire(self, monkeypatch, response_text: str):
        """Stub vertexai/aiplatform init and the generative model class."""
        vertex_init = _Recorder()
        platform_init = _Recorder()
        monkeypatch.setattr(gateway_module.vertexai, "init", vertex_init)
        monkeypatch.setattr(gateway_module.aiplatform, "init", platform_init)

        class _StubResponse:
            text = response_text

        class _StubModel:
            def __init__(self, name: str) -> None:
                """Stub behaviour for the wired client path."""
                self.name = name

            def generate_content(self, prompt, generation_config=None):
                """Stub behaviour for the wired client path."""
                del prompt, generation_config
                return _StubResponse()

        monkeypatch.setattr(gateway_module, "GenerativeModel", _StubModel)
        return vertex_init, platform_init

    def test_both_sdk_inits_called_with_project_and_region(self, monkeypatch):
        """Both sdk inits called with project and region."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "wc26")
        resolve_project_id.cache_clear()
        vertex_init, platform_init = self._wire(monkeypatch, "hello")
        VertexGateway().generate("prompt")
        assert vertex_init.calls[0]["project"] == "wc26"
        assert platform_init.calls[0]["project"] == "wc26"
        assert vertex_init.calls[0]["location"] == platform_init.calls[0]["location"]
        resolve_project_id.cache_clear()

    def test_generate_returns_model_text(self, monkeypatch):
        """Generate returns model text."""
        self._wire(monkeypatch, "guidance text")
        assert VertexGateway().generate("prompt") == "guidance text"

    def test_model_initialised_once(self, monkeypatch):
        """Model initialised once."""
        vertex_init, _ = self._wire(monkeypatch, "hello")
        gateway = VertexGateway()
        gateway.generate("one")
        gateway.generate("two")
        assert len(vertex_init.calls) == 1

    def test_empty_model_response_raises(self, monkeypatch):
        """Empty model response raises."""
        self._wire(monkeypatch, "   ")
        with pytest.raises(RuntimeError):
            VertexGateway().generate("prompt")

    def test_is_healthy_true_when_model_builds(self, monkeypatch):
        """Is healthy true when model builds."""
        self._wire(monkeypatch, "hello")
        assert VertexGateway().is_healthy() is True

    def test_gateway_feeds_interpreter_end_to_end(self, monkeypatch):
        """Gateway feeds interpreter end to end."""
        self._wire(monkeypatch, json.dumps({"intent": "transit_query"}))
        parsed = IntentInterpreter(gateway=VertexGateway()).parse("metro?", "fan")
        assert parsed["intent"] == "transit_query"
        assert parsed["source"] == "gemini"


class TestTranslatorClientPath:
    """Translate v3 request construction with a stubbed client."""

    class _StubTranslation:
        def __init__(self, text: str) -> None:
            """Stub behaviour for the wired client path."""
            self.translated_text = text

    def _translator_with_stub(self, monkeypatch, translations):
        """Stub behaviour for the wired client path."""
        translator = ResponseTranslator()
        requests: list[dict] = []

        class _StubClient:
            def translate_text(self, request):
                """Stub behaviour for the wired client path."""
                requests.append(request)

                class _Response:
                    pass

                response = _Response()
                response.translations = [
                    TestTranslatorClientPath._StubTranslation(text)
                    for text in translations
                ]
                return response

        monkeypatch.setattr(translator, "_ensure_client", lambda: _StubClient())
        return translator, requests

    def test_request_shape_and_translated_value(self, monkeypatch):
        """Request shape and translated value."""
        translator, requests = self._translator_with_stub(monkeypatch, ["Hola"])
        result = translator.translate_json_values({"guidance": "Hello"}, "es")
        assert result["guidance"] == "Hola"
        request = requests[0]
        assert request["target_language_code"] == "es"
        assert request["contents"] == ["Hello"]
        assert request["mime_type"] == "text/plain"

    def test_empty_translation_list_falls_back(self, monkeypatch):
        """Empty translation list falls back."""
        translator, _ = self._translator_with_stub(monkeypatch, [])
        payload = {"guidance": "Hello"}
        assert translator.translate_json_values(payload, "es") == payload

    def test_is_healthy_with_stub_client(self, monkeypatch):
        """Is healthy with stub client."""
        translator, _ = self._translator_with_stub(monkeypatch, ["x"])
        assert translator.is_healthy() is True


class TestSentimentClientPath:
    """Natural Language request path with a stubbed client."""

    def test_score_returned_from_client(self, monkeypatch):
        """Score returned from client."""
        lens = SentimentLens()

        class _StubSentiment:
            score = -0.6

        class _StubResponse:
            document_sentiment = _StubSentiment()

        class _StubClient:
            def analyze_sentiment(self, request):
                """Stub behaviour for the wired client path."""
                del request
                return _StubResponse()

        monkeypatch.setattr(lens, "_ensure_client", lambda: _StubClient())
        assert lens.score("terrible crush at the gate") == pytest.approx(-0.6)

    def test_is_healthy_with_stub_client(self, monkeypatch):
        """Is healthy with stub client."""
        lens = SentimentLens()
        monkeypatch.setattr(lens, "_ensure_client", lambda: object())
        assert lens.is_healthy() is True


class TestSecretClientPath:
    """Secret Manager access path with a stubbed client."""

    def test_secret_value_decoded(self, monkeypatch):
        """Secret value decoded."""
        vault = SecretVault()

        class _StubPayload:
            data = b"s3cret"

        class _StubResponse:
            payload = _StubPayload()

        class _StubClient:
            def access_secret_version(self, request):
                """Stub behaviour for the wired client path."""
                assert "versions/latest" in request["name"]
                return _StubResponse()

        monkeypatch.setattr(vault, "_ensure_client", lambda: _StubClient())
        assert vault.get("api_key") == "s3cret"

    def test_is_healthy_with_stub_client(self, monkeypatch):
        """Is healthy with stub client."""
        vault = SecretVault()
        monkeypatch.setattr(vault, "_ensure_client", lambda: object())
        assert vault.is_healthy() is True


class TestArchiveClientPath:
    """Cloud Storage snapshot path with a stubbed client."""

    def test_snapshot_uploaded(self, monkeypatch):
        """Snapshot uploaded."""
        vault = ArchiveVault()
        uploads: list[tuple[str, str]] = []

        class _StubBlob:
            def __init__(self, name: str) -> None:
                """Stub behaviour for the wired client path."""
                self.name = name

            def upload_from_string(self, payload, content_type):
                """Stub behaviour for the wired client path."""
                uploads.append((self.name, content_type))
                del payload

        class _StubBucket:
            def blob(self, name):
                """Stub behaviour for the wired client path."""
                return _StubBlob(name)

        class _StubClient:
            def bucket(self, name):
                """Stub behaviour for the wired client path."""
                del name
                return _StubBucket()

        monkeypatch.setattr("app.services.archive.ARCHIVE_BUCKET", "ops-bucket")
        monkeypatch.setattr(vault, "_ensure_client", lambda: _StubClient())
        assert vault.archive_snapshot({"zones": []}) is True
        assert uploads[0][0].startswith("ops-snapshots/")
        assert uploads[0][1] == "application/json"

    def test_is_healthy_with_stub_client(self, monkeypatch):
        """Is healthy with stub client."""
        vault = ArchiveVault()
        monkeypatch.setattr(vault, "_ensure_client", lambda: object())
        assert vault.is_healthy() is True


class TestLedgerClientPath:
    """Firestore write path with a stubbed client."""

    def test_write_reaches_collection(self, monkeypatch):
        """Write reaches collection."""
        writes: list[tuple[str, str]] = []

        class _StubDocument:
            def __init__(self, collection: str, doc_id: str) -> None:
                """Stub behaviour for the wired client path."""
                self.collection = collection
                self.doc_id = doc_id

            def set(self, record):
                """Stub behaviour for the wired client path."""
                del record
                writes.append((self.collection, self.doc_id))

        class _StubCollection:
            def __init__(self, name: str) -> None:
                """Stub behaviour for the wired client path."""
                self.name = name

            def document(self, doc_id):
                """Stub behaviour for the wired client path."""
                return _StubDocument(self.name, doc_id)

        class _StubClient:
            def collection(self, name):
                """Stub behaviour for the wired client path."""
                return _StubCollection(name)

        ledger = ledger_module.FirestoreLedger()
        monkeypatch.setattr(ledger, "_ensure_client", lambda: _StubClient())
        record_id = ledger.add_report({"zone": "north"})
        assert writes[0][0] == "crowd_reports"
        assert writes[0][1] == record_id

    def test_build_ledger_returns_event_ledger(self):
        """Build ledger returns event ledger."""
        ledger = build_ledger()
        assert hasattr(ledger, "add_report")
        assert hasattr(ledger, "open_incidents")


class TestInterpreterPromptContract:
    """The interpreter prompt carries persona and message."""

    def test_prompt_includes_message_and_persona(self):
        """Prompt includes message and persona."""
        gateway = ScriptedGateway(json.dumps({"intent": "route_request"}))
        IntentInterpreter(gateway=gateway).parse("find section 114", "volunteer")
        prompt = gateway.prompts[0]
        assert "find section 114" in prompt
        assert "volunteer" in prompt
