"""
Tools package for METIS agent.

Provides calculator, file_reader, web_search, code_executor, and ToolRegistry.
"""

from backend.tools.calculator import calculator_execute
from backend.tools.code_executor import code_executor_execute
from backend.tools.file_reader import file_reader_execute
from backend.tools.registry import ToolPermission, ToolRegistry, default_tool_registry
from backend.tools.web_search import web_search_execute

__all__ = [
    "calculator_execute",
    "code_executor_execute",
    "file_reader_execute",
    "web_search_execute",
    "ToolPermission",
    "ToolRegistry",
    "default_tool_registry",
]
