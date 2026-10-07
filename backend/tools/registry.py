"""
Tool registry and dispatcher for METIS agent tools.

Source of truth: BLUEPRINT.md §8, §12, §13, §17.
Tools registered:
- calculator (READ_ONLY)
- file_reader (READ_ONLY)
- web_search (READ_ONLY_EXTERNAL)
- code_executor (SANDBOXED_EXECUTION)
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from backend.core.logging import get_logger
from backend.tools.calculator import TOOL_SPEC as CALCULATOR_SPEC, calculator_execute
from backend.tools.file_reader import TOOL_SPEC as FILE_READER_SPEC, file_reader_execute
from backend.tools.web_search import TOOL_SPEC as WEB_SEARCH_SPEC, web_search_execute
from backend.tools.code_executor import TOOL_SPEC as CODE_EXECUTOR_SPEC, code_executor_execute

logger = get_logger(__name__)


class ToolPermission(str, Enum):
    READ_ONLY = "READ_ONLY"
    READ_ONLY_EXTERNAL = "READ_ONLY_EXTERNAL"
    SANDBOXED_EXECUTION = "SANDBOXED_EXECUTION"


class ToolRegistry:
    """Central registry and execution coordinator for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        self.register(
            name="calculator",
            spec=CALCULATOR_SPEC,
            func=calculator_execute,
            permission=ToolPermission.READ_ONLY,
            timeout=10.0,
        )
        self.register(
            name="file_reader",
            spec=FILE_READER_SPEC,
            func=file_reader_execute,
            permission=ToolPermission.READ_ONLY,
            timeout=10.0,
        )
        self.register(
            name="web_search",
            spec=WEB_SEARCH_SPEC,
            func=web_search_execute,
            permission=ToolPermission.READ_ONLY_EXTERNAL,
            timeout=15.0,
        )
        self.register(
            name="code_executor",
            spec=CODE_EXECUTOR_SPEC,
            func=code_executor_execute,
            permission=ToolPermission.SANDBOXED_EXECUTION,
            timeout=10.0,
        )

    def register(
        self,
        name: str,
        spec: dict[str, Any],
        func: Callable[..., Any],
        permission: ToolPermission = ToolPermission.READ_ONLY,
        timeout: float = 10.0,
    ) -> None:
        """Register a tool with its specification and runner."""
        self._tools[name] = {
            "name": name,
            "spec": spec,
            "func": func,
            "permission": permission,
            "timeout": timeout,
        }
        logger.debug("Registered tool: %s (%s)", name, permission.value)

    def get_tool(self, name: str) -> Optional[dict[str, Any]]:
        """Retrieve tool metadata by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tool specifications for prompt injection."""
        return [t["spec"] for t in self._tools.values()]

    def list_tool_names(self) -> list[str]:
        """List registered tool names."""
        return list(self._tools.keys())

    async def execute_tool(
        self,
        name: str,
        parameters: dict[str, Any],
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Execute a registered tool asynchronously with timeout and safety guarantees.

        Returns:
            Dict containing output data or error classification:
            - On success: {"success": True, "result": ..., ...}
            - On timeout: {"success": False, "error_code": "TOOL_TIMEOUT", "error": ...}
            - On validation error: {"success": False, "error_code": "TOOL_VALIDATION_ERROR", "error": ...}
            - On policy failure: {"success": False, "error_code": "TOOL_POLICY_FAILURE", "error": ...}
            - On exception: {"success": False, "error_code": "TOOL_EXCEPTION", "error": ...}
        """
        if name not in self._tools:
            logger.warning("Attempted invocation of unknown tool: %s", name)
            return {
                "success": False,
                "error_code": "TOOL_POLICY_FAILURE",
                "error": f"Tool '{name}' is not recognized or permitted.",
                "tool": name,
            }

        tool_meta = self._tools[name]
        func = tool_meta["func"]
        effective_timeout = timeout or tool_meta["timeout"]

        # Validate parameters against spec
        spec = tool_meta["spec"]
        spec_params = spec.get("parameters", {})
        for param_name, param_info in spec_params.items():
            if param_info.get("required", False) and param_name not in parameters:
                return {
                    "success": False,
                    "error_code": "TOOL_VALIDATION_ERROR",
                    "error": f"Missing required parameter '{param_name}' for tool '{name}'.",
                    "tool": name,
                }

        try:
            # If function is a coroutine, await it; otherwise run in thread pool
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(**parameters),
                    timeout=effective_timeout,
                )
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(**parameters)),
                    timeout=effective_timeout,
                )

            # Check if result contains explicit error
            if isinstance(result, dict) and "error" in result:
                err_msg = str(result["error"])
                if "security" in err_msg.lower() or "denied" in err_msg.lower() or "prohibited" in err_msg.lower():
                    return {
                        "success": False,
                        "error_code": "TOOL_POLICY_FAILURE",
                        "error": err_msg,
                        "tool": name,
                    }
                return {
                    "success": False,
                    "error_code": "TOOL_VALIDATION_ERROR",
                    "error": err_msg,
                    "tool": name,
                }

            return {
                "success": True,
                "output": result,
                "tool": name,
            }

        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %.1fs", name, effective_timeout)
            return {
                "success": False,
                "error_code": "TOOL_TIMEOUT",
                "error": f"Tool execution timed out after {effective_timeout}s.",
                "tool": name,
            }
        except TypeError as exc:
            logger.warning("Tool %s parameter validation error: %s", name, exc)
            return {
                "success": False,
                "error_code": "TOOL_VALIDATION_ERROR",
                "error": f"Parameter validation error: {exc}",
                "tool": name,
            }
        except Exception as exc:
            logger.error("Tool %s unhandled exception: %s", name, exc)
            return {
                "success": False,
                "error_code": "TOOL_EXCEPTION",
                "error": f"Tool encountered an error: {type(exc).__name__}",
                "tool": name,
            }


# Singleton registry instance
default_tool_registry = ToolRegistry()
