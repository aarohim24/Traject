"""Traject MCP server — exposes compression and observability as MCP tools.

Three tools are registered:
- traject_compress: compress a text blob, returns compressed text + token delta
- traject_stats: return compression metrics for the current session
- traject_budget: return token spend vs configured budget threshold

Start with: traject mcp --host localhost --port 3000
Or from Python: uvicorn traject.mcp.server:app
"""

from __future__ import annotations

from traject.mcp.server import create_mcp_server

__all__ = ["create_mcp_server"]
