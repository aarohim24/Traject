"""Traject transparent compression proxy.

Presents an OpenAI-compatible /v1/chat/completions endpoint that
compresses incoming context before forwarding to any OpenAI-compatible
backend. Zero client code changes required — point your existing agent
at http://localhost:8080 instead of https://api.openai.com.

Start with: traject proxy --port 8080 --backend https://api.openai.com
"""

from __future__ import annotations

from traject.proxy.app import create_app, run

__all__ = ["create_app", "run"]
