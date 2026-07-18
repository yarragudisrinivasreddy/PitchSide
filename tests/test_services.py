"""Unit tests for the service layer: parsing, narration, translation."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

import json

from app.services.composer import NarrativeComposer
from app.services.interpreter import IntentInterpreter
from app.services.secrets import SecretVault
from app.services.sentiment import SentimentLens
from app.services.translator import ResponseTranslator
from tests.conftest import EchoTranslator, FailingGateway, ScriptedGateway


class TestInterpreter:
    """Intent parsing with Gemini and the heuristic safety net."""

    def test_valid_model_json_is_used(self):
        """Valid model json is used."""
        payload = {
            "intent": "route_request",
            "origin": "Gate A",
            "destination": "Section 114",
            "accessible": True,
        }
        gateway = ScriptedGateway(json.dumps(payload))
        parsed = IntentInterpreter(gateway=gateway).parse("any", "fan")
        assert parsed["intent"] == "route_request"
        assert parsed["source"] == "gemini"
        assert parsed["accessible"] is True

    def test_model_json_with_fences_is_cleaned(self):
        """Model json with fences is cleaned."""
        gateway = ScriptedGateway(
            "```json\n{\"intent\": \"transit_query\"}\n```"
        )
        parsed = IntentInterpreter(gateway=gateway).parse("any", "fan")
        assert parsed["intent"] == "transit_query"
        assert parsed["source"] == "gemini"

    def test_garbage_model_output_falls_back_without_exception(self):
        """Garbage model output falls back without exception."""
        gateway = ScriptedGateway("the model rambles with no JSON at all")
        parsed = IntentInterpreter(gateway=gateway).parse(
            "how do I reach section 114", "fan"
        )
        assert parsed["source"] == "heuristic"
        assert parsed["intent"] == "route_request"

    def test_model_json_missing_intent_falls_back(self):
        """Model json missing intent falls back."""
        gateway = ScriptedGateway(json.dumps({"origin": "Gate A"}))
        parsed = IntentInterpreter(gateway=gateway).parse("route please", "fan")
        assert parsed["source"] == "heuristic"

    def test_model_json_array_falls_back(self):
        """Model json array falls back."""
        gateway = ScriptedGateway(json.dumps(["not", "an", "object"]))
        parsed = IntentInterpreter(gateway=gateway).parse("route please", "fan")
        assert parsed["source"] == "heuristic"

    def test_upstream_outage_falls_back(self):
        """Upstream outage falls back."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "huge queue at gate c", "volunteer"
        )
        assert parsed["source"] == "heuristic"
        assert parsed["intent"] == "crowd_report"

    def test_heuristic_incident_detection(self):
        """Heuristic incident detection."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "someone is injured near the west restrooms", "staff"
        )
        assert parsed["intent"] == "incident_report"
        assert parsed["category"] == "medical"
        assert parsed["description"]

    def test_heuristic_transit_detection(self):
        """Heuristic transit detection."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "when does the metro leave", "fan"
        )
        assert parsed["intent"] == "transit_query"
        assert parsed["mode"] == "metro"

    def test_heuristic_accessibility_flag(self):
        """Heuristic accessibility flag."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "wheelchair route to section 114 please", "fan"
        )
        assert parsed["accessible"] is True

    def test_heuristic_zone_extraction(self):
        """Heuristic zone extraction."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "long line at gate b", "fan"
        )
        assert parsed["zone"] == "gate b"

    def test_heuristic_level_words(self):
        """Heuristic level words."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "the south concourse is packed", "fan"
        )
        assert parsed["intent"] == "crowd_report"
        assert parsed["level"] == "critical"

    def test_heuristic_default_is_route(self):
        """Heuristic default is route."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "hello there", "fan"
        )
        assert parsed["intent"] == "route_request"


class TestComposer:
    """Narrative composition and deterministic templates."""

    def test_model_narrative_used_when_available(self):
        """Model narrative used when available."""
        gateway = ScriptedGateway("Head left along the wide concourse.")
        text = NarrativeComposer(gateway=gateway).compose(
            "route_request", {"origin": "Gate A"}, "fan"
        )
        assert text == "Head left along the wide concourse."

    def test_fallback_route_template(self):
        """Fallback route template."""
        text = NarrativeComposer(gateway=FailingGateway()).compose(
            "route_request",
            {
                "origin": "Gate A",
                "destination": "Section 101",
                "total_distance_m": 100.0,
                "eta_minutes": 1.4,
            },
            "fan",
        )
        assert "Gate A" in text and "Section 101" in text

    def test_fallback_transit_template_flattens_nested(self):
        """Fallback transit template flattens nested."""
        text = NarrativeComposer(gateway=FailingGateway()).compose(
            "transit_query",
            {
                "departure": {"wave_start_minutes_after_final_whistle": 15},
                "lowest_carbon_transit_mode": "metro",
            },
            "fan",
        )
        assert "15" in text and "metro" in text

    def test_fallback_unknown_intent_generic(self):
        """Fallback unknown intent generic."""
        text = NarrativeComposer(gateway=FailingGateway()).compose(
            "mystery", {}, "fan"
        )
        assert text == "Your request has been processed."

    def test_fallback_missing_keys_generic(self):
        """Fallback missing keys generic."""
        text = NarrativeComposer(gateway=FailingGateway()).compose(
            "route_request", {}, "fan"
        )
        assert text == "Your request has been processed."

    def test_prompt_contains_result_payload(self):
        """Prompt contains result payload."""
        gateway = ScriptedGateway("ok")
        NarrativeComposer(gateway=gateway).compose(
            "crowd_report", {"zone": "north"}, "organizer"
        )
        assert "north" in gateway.prompts[0]
        assert "organizer" in gateway.prompts[0]


class TestTranslator:
    """Full-response translation contract."""

    def setup_method(self) -> None:
        """Echo translator marks every translated string."""
        self.translator = EchoTranslator()

    def test_english_passthrough(self):
        """English passthrough."""
        payload = {"guidance": "Turn left"}
        assert self.translator.translate_json_values(payload, "en") == payload

    def test_every_string_value_translated_recursively(self):
        """Every string value translated recursively."""
        payload = {
            "guidance": "Turn left",
            "result": {"steps": [{"note": "Take the ramp"}]},
        }
        translated = self.translator.translate_json_values(payload, "es")
        assert translated["guidance"] == "[es]Turn left"
        assert translated["result"]["steps"][0]["note"] == "[es]Take the ramp"

    def test_excluded_keys_not_translated(self):
        """Excluded keys not translated."""
        payload = {"zone": "north", "severity": "P1", "guidance": "Stay calm"}
        translated = self.translator.translate_json_values(payload, "hi")
        assert translated["zone"] == "north"
        assert translated["severity"] == "P1"
        assert translated["guidance"] == "[hi]Stay calm"

    def test_hashtags_not_translated(self):
        """Hashtags not translated."""
        payload = {"guidance": "#BuildWithAI"}
        translated = self.translator.translate_json_values(payload, "fr")
        assert translated["guidance"] == "#BuildWithAI"

    def test_urls_not_translated(self):
        """Urls not translated."""
        payload = {"note": "https://www.ipcc.ch/report/ar5/wg3/"}
        translated = self.translator.translate_json_values(payload, "de")
        assert translated["note"].startswith("https://")

    def test_numbers_and_booleans_untouched(self):
        """Numbers and booleans untouched."""
        payload = {"density": 42.5, "deferred": True, "count": 3}
        assert self.translator.translate_json_values(payload, "pt") == payload

    def test_unit_tokens_untouched(self):
        """Unit tokens untouched."""
        payload = {"note": "P1", "other": "m2"}
        translated = self.translator.translate_json_values(payload, "ar")
        assert translated == payload

    def test_supported_language_validation(self):
        """Supported language validation."""
        assert self.translator.validate_language("ES") == "es"
        assert self.translator.validate_language(None) == "en"

    def test_unsupported_language_raises(self):
        """Unsupported language raises."""
        try:
            self.translator.validate_language("xx")
        except ValueError as exc:
            assert "xx" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("expected ValueError")


class TestSentimentAndSecrets:
    """Fallback behaviour for sentiment and secret resolution."""

    def test_sentiment_neutral_without_credentials(self, monkeypatch):
        """Sentiment neutral without credentials."""
        lens = SentimentLens()
        monkeypatch.setattr(
            lens,
            "_ensure_client",
            lambda: (_ for _ in ()).throw(RuntimeError("no creds")),
        )
        assert lens.score("angry text") == 0.0

    def test_secret_env_fallback(self, monkeypatch):
        """Secret env fallback."""
        vault = SecretVault()
        monkeypatch.setattr(
            vault,
            "_ensure_client",
            lambda: (_ for _ in ()).throw(RuntimeError("no creds")),
        )
        monkeypatch.setenv("MATCH_KEY", "from-env")
        assert vault.get("match_key", default="fallback") == "from-env"

    def test_secret_default_fallback(self, monkeypatch):
        """Secret default fallback."""
        vault = SecretVault()
        monkeypatch.setattr(
            vault,
            "_ensure_client",
            lambda: (_ for _ in ()).throw(RuntimeError("no creds")),
        )
        monkeypatch.delenv("MISSING_KEY", raising=False)
        assert vault.get("missing_key", default="fallback") == "fallback"


class TestHeuristicCategories:
    """Remaining heuristic category branches."""

    def test_security_category(self):
        """Security category."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "there is a fight breaking out", "staff"
        )
        assert parsed["category"] == "security"

    def test_lost_item_category(self):
        """Lost item category."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "I lost my phone near gate d", "fan"
        )
        assert parsed["category"] == "lost_item"

    def test_facility_category(self):
        """Facility category."""
        parsed = IntentInterpreter(gateway=FailingGateway()).parse(
            "there is a broken railing with someone hurt", "volunteer"
        )
        assert parsed["intent"] == "incident_report"

    def test_facility_keyword_branch(self):
        """Facility keyword branch."""
        interpreter = IntentInterpreter(gateway=FailingGateway())
        assert interpreter._category("water leak in restroom") == "facility"
        assert interpreter._category("crowd trouble") == "crowd"


class TestRealClientConstructors:
    """Client construction paths execute without raising to callers."""

    def test_translator_health_probe_is_boolean(self):
        """Translator health probe is boolean."""
        assert isinstance(ResponseTranslator().is_healthy(), bool)

    def test_sentiment_health_probe_is_boolean(self):
        """Sentiment health probe is boolean."""
        assert isinstance(SentimentLens().is_healthy(), bool)

    def test_secret_health_probe_is_boolean(self):
        """Secret health probe is boolean."""
        assert isinstance(SecretVault().is_healthy(), bool)
