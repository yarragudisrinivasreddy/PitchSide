"""Shared fixtures: stub gateways and a credential-free application."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations

import pytest

from app import create_app
from app.services.assistant import MatchDayAssistant
from app.services.cache import InsightCache
from app.services.composer import NarrativeComposer
from app.services.interpreter import IntentInterpreter
from app.services.ledger import InMemoryLedger
from app.services.translator import ResponseTranslator


class FailingGateway:
    """Gateway stub whose generation always fails upstream."""

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        """Simulate an upstream outage."""
        raise RuntimeError("simulated upstream outage")

    def is_healthy(self) -> bool:
        """Report unavailable."""
        return False


class ScriptedGateway:
    """Gateway stub returning a fixed response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        """Return the scripted response, recording the prompt."""
        self.prompts.append(prompt)
        return self.response

    def is_healthy(self) -> bool:
        """Report available."""
        return True


class EchoTranslator(ResponseTranslator):
    """Translator stub marking translated strings instead of calling APIs."""

    def _translate_text(self, text: str, target_language: str) -> str:
        return f"[{target_language}]{text}"

    def is_healthy(self) -> bool:
        """Report available."""
        return True


class NeutralSentiment:
    """Sentiment stub returning a configurable fixed score."""

    def __init__(self, fixed: float = 0.0) -> None:
        self.fixed = fixed

    def score(self, text: str) -> float:
        """Return the configured score."""
        return self.fixed

    def is_healthy(self) -> bool:
        """Report available."""
        return True


class NullArchive:
    """Archive stub recording snapshots without any network access."""

    def __init__(self) -> None:
        self.snapshots: list[dict] = []

    def archive_snapshot(self, snapshot: dict) -> bool:
        """Record the snapshot locally."""
        self.snapshots.append(snapshot)
        return True

    def is_healthy(self) -> bool:
        """Report available."""
        return True


def build_assistant(gateway=None, sentiment=None) -> MatchDayAssistant:
    """Assistant wired entirely with offline components."""
    active_gateway = gateway or FailingGateway()
    return MatchDayAssistant(
        ledger=InMemoryLedger(),
        interpreter=IntentInterpreter(gateway=active_gateway),
        composer=NarrativeComposer(gateway=active_gateway),
        translator=EchoTranslator(),
        sentiment=sentiment or NeutralSentiment(),
        archive=NullArchive(),
        cache=InsightCache(),
    )


@pytest.fixture(name="assistant")
def assistant_fixture() -> MatchDayAssistant:
    """Offline assistant with heuristic-only interpretation."""
    return build_assistant()


@pytest.fixture(name="client")
def client_fixture(assistant):
    """Flask test client bound to the offline assistant."""
    application = create_app(assistant=assistant)
    application.config["TESTING"] = True
    return application.test_client()
