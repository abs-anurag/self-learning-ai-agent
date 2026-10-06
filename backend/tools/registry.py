# -*- coding: utf-8 -*-
"""
Tool Registry for LangGraph agent.

Source of truth: BLUEPRINT.md S13.

Registry manages available tools and dispatches tool calls.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Base class for all tools."""

    def __init__(self, name: str, permission_level: str = "READ_ONLY"):
        self.name = name
        self.permission_level = permission_level

    @abstractmethod
    async def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with given state and arguments."""
        pass


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default tools."""
        from backend.tools.calculator import CalculatorTool
        from backend.tools.file_reader import FileReaderTool
        from backend.tools.web_search import WebSearchTool

        self.register(CalculatorTool())
        self.register(FileReaderTool())
        self.register(WebSearchTool())

        logger.info("Registered tools: " + str(list(self._tools.keys())))

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())


tool_registry = ToolRegistry()


__all__ = ["ToolRegistry", "BaseTool", "tool_registry"]
