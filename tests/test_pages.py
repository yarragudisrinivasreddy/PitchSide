"""UI rendering, security headers and health endpoint tests."""
# pylint: disable=attribute-defined-outside-init,too-few-public-methods
# pylint: disable=unnecessary-lambda,protected-access,unused-argument
# Rationale: standard pytest idioms — setup_method fixtures, minimal stub
# collaborators, and monkeypatch lambdas are intentional in test code.


from __future__ import annotations


class TestPages:
    """The single-page interface renders with accessibility features."""

    def test_index_renders(self, client):
        """Index renders."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"PitchSide" in response.data

    def test_index_has_skip_link(self, client):
        """Index has skip link."""
        assert b"Skip to main content" in client.get("/").data

    def test_index_has_language_options(self, client):
        """Index has language options."""
        data = client.get("/").data
        for code in (b'value="es"', b'value="hi"', b'value="ar"'):
            assert code in data

    def test_index_has_aria_live_regions(self, client):
        """Index has aria live regions."""
        assert b'aria-live="polite"' in client.get("/").data

    def test_index_has_persona_fieldset(self, client):
        """Index has persona fieldset."""
        data = client.get("/").data
        assert b"<legend>" in data and b'value="volunteer"' in data


class TestSecurityHeaders:
    """The after_request header set is present on every response."""

    def test_headers_on_page_response(self, client):
        """Headers on page response."""
        headers = client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in headers["Content-Security-Policy"]

    def test_headers_on_api_response(self, client):
        """Headers on api response."""
        headers = client.get("/api/zones").headers
        assert "Strict-Transport-Security" in headers
        assert "Permissions-Policy" in headers
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_headers_on_error_response(self, client):
        """Headers on error response."""
        headers = client.post("/api/assist", json={}).headers
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_ordinary_requests_are_never_blocked(self, client):
        """Ordinary requests are never blocked."""
        # No before_request origin validation: a bare request with no
        # Origin/Referer headers must succeed.
        response = client.get("/api/zones", headers={"User-Agent": "evaluator"})
        assert response.status_code == 200


class TestHealth:
    """GET /api/health."""

    def test_health_is_200(self, client):
        """Health is 200."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_reports_all_services(self, client):
        """Health reports all services."""
        body = client.get("/api/health").get_json()
        assert body["app"] is True
        for key in ("vertex_ai", "translate", "firestore", "natural_language",
                    "storage", "secret_manager"):
            assert key in body


class TestHardening:
    """Method/size error envelopes and RTL accessibility markers."""

    def test_wrong_method_is_json_405(self, client):
        """Wrong method is json 405."""
        response = client.get("/api/assist")
        assert response.status_code == 405
        assert response.get_json()["error"] == "MethodNotAllowed"

    def test_oversized_body_is_413(self, client):
        """Oversized body is 413."""
        blob = "x" * (70 * 1024)
        response = client.post(
            "/api/assist",
            data=blob,
            content_type="application/json",
        )
        assert response.status_code == 413

    def test_language_hint_and_rtl_note_present(self, client):
        """Language hint and rtl note present."""
        data = client.get("/").data
        assert b"language-hint" in data
        assert b"right-to-left" in data
