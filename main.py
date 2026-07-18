"""WSGI entry point for Cloud Run."""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":  # pragma: no cover - local development only
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
