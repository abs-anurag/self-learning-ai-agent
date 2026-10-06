# -*- coding: utf-8 -*-
"""
Web search tool using Tavily API.

Source of truth: BLUEPRINT.md S13.

Returns title, URL, and snippet text. No arbitrary URL fetch.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.tools.registry import BaseTool
try:
    from backend.core.config import settings
except ImportError:
    from backend.config import settings

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Web search via Tavily API."""

    def __init__(self):
        super().__init__("web_search", "READ_ONLY_EXTERNAL")
        self.api_key = getattr(settings, "TAVILY_API_KEY", None)

    async def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query")
        if not query:
            return {
                "error": "Missing query parameter",
                "error_code": "MISSING_QUERY",
            }
        if not self.api_key:
            logger.error("[WebSearchTool] TAVILY_API_KEY not configured")
            return {
                "error": "Web search not configured",
                "error_code": "NOT_CONFIGURED",
            }
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=self.api_key)
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=True,
            )
            results = response.get("results", [])
            formatted = [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": r.get("content"),
                }
                for r in results
            ]
            return {
                "result": formatted,
                "answer": response.get("answer"),
            }
        except ImportError:
            logger.error("[WebSearchTool] tavily-python not installed")
            return {
                "error": "Web search library not available",
                "error_code": "LIBRARY_MISSING",
            }
        except Exception as e:
            logger.error(f"[WebSearchTool] Search error: {e}", exc_info=True)
            return {
                "error": str(e),
                "error_code": "SEARCH_ERROR",
            }


__all__ = ["WebSearchTool"]
