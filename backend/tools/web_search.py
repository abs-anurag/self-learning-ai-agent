"""
Web search tool using Tavily API.

Source of truth: BLUEPRINT.md §2, §12.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


def web_search_execute(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Search the web using Tavily API.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.

    Returns:
        Dict with 'results' on success or 'error' on failure.
    """
    if not query or not query.strip():
        return {"error": "Empty search query provided.", "tool": "web_search"}

    query = query.strip()
    logger.info("Web search for: %s", query[:100])

    try:
        from tavily import TavilyClient

        api_key = settings.TAVILY_API_KEY.get_secret_value()
        if not api_key or api_key == "tvly-placeholder-key-do-not-commit":
            return {
                "error": "Tavily API key not configured. Set TAVILY_API_KEY in environment.",
                "tool": "web_search",
            }

        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results)

        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:2000],  # Truncate large content
            })

        return {
            "results": results,
            "query": query,
            "result_count": len(results),
            "tool": "web_search",
        }

    except ImportError:
        logger.error("tavily-python not installed")
        return {"error": "Web search dependency (tavily-python) not available.", "tool": "web_search"}
    except Exception as exc:
        logger.error("Web search error for '%s': %s", query[:100], type(exc).__name__)
        return {"error": f"Web search failed: {type(exc).__name__}: {exc}", "tool": "web_search"}


TOOL_SPEC = {
    "name": "web_search",
    "description": (
        "Search the web for current, real-time information using Tavily. "
        "Use when the user asks about current events, latest versions, "
        "recent news, live data, or any information that requires up-to-date sources. "
        "Do NOT use for general knowledge questions that can be answered from training data."
    ),
    "parameters": {
        "query": {
            "type": "string",
            "description": "The search query to find current information",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results (default: 5)",
            "required": False,
        },
    },
    "execute": web_search_execute,
}
