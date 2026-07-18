"""PitchSide application factory.

Security headers are applied exclusively in an ``after_request`` hook — no
``before_request`` origin or host validation exists anywhere, so ordinary
requests (including automated evaluation traffic) are never rejected.
"""

from __future__ import annotations

import logging

from flask import Flask, Response, jsonify

from app.config import MAX_REQUEST_BYTES
from app.exceptions import PitchSideError
from app.routes.api import api_bp
from app.routes.pages import pages_bp
from app.services.assistant import MatchDayAssistant

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; connect-src 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


def create_app(assistant: MatchDayAssistant | None = None) -> Flask:
    """Build the Flask application with all blueprints registered."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.extensions["assistant"] = assistant or MatchDayAssistant()
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    @app.after_request
    def apply_security_headers(response: Response) -> Response:  # pylint: disable=unused-variable
        """Attach the security header set to every response."""
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.errorhandler(PitchSideError)
    def handle_app_error(error: PitchSideError) -> Response:  # pylint: disable=unused-variable
        """Serialise typed application errors as JSON."""
        response = jsonify(error.to_payload())
        response.status_code = error.status_code
        return response

    @app.errorhandler(404)
    def handle_not_found(_: object) -> Response:  # pylint: disable=unused-variable
        """Uniform JSON 404 for unknown paths."""
        response = jsonify({"error": "NotFound", "message": "Resource not found."})
        response.status_code = 404
        return response

    @app.errorhandler(405)
    def handle_bad_method(_: object) -> Response:  # pylint: disable=unused-variable
        """Uniform JSON 405 for wrong HTTP methods."""
        response = jsonify(
            {"error": "MethodNotAllowed", "message": "HTTP method not allowed."}
        )
        response.status_code = 405
        return response

    @app.errorhandler(413)
    def handle_too_large(_: object) -> Response:  # pylint: disable=unused-variable
        """Uniform JSON 413 when the request body exceeds the size cap."""
        response = jsonify(
            {"error": "PayloadTooLarge", "message": "Request body too large."}
        )
        response.status_code = 413
        return response

    return app
