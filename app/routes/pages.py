"""UI blueprint serving the single-page PitchSide interface."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.config import SUPPORTED_LANGUAGES

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def index() -> str:
    """Render the match-day copilot interface."""
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)
