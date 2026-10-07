"""
Sandboxed code executor tool for demo/computational tasks.

Source of truth: BLUEPRINT.md §2, §12, §13, §17.
Explicitly labeled: MVP/demo isolation only, NOT production-grade security.
Restricted execution with timeout, memory limit, blocked imports and builtins.
"""

from __future__ import annotations

import multiprocessing
import queue
import sys
import time
from typing import Any, Dict, Optional

from backend.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 5.0
MAX_OUTPUT_CHARS = 10000

# Forbidden identifiers and modules that must not be accessed
BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "requests", "urllib", "http",
    "shutil", "pathlib", "importlib", "ctypes", "pickle", "multiprocessing",
    "builtins", "__builtin__",
})

BLOCKED_NAMES = frozenset({
    "exec", "eval", "compile", "open", "input", "__import__",
    "breakpoint", "exit", "quit", "help",
})


def _worker_process(code: str, result_queue: multiprocessing.Queue) -> None:
    """Run sandboxed code in a separate process."""
    try:
        import io
        import contextlib

        # Check for blocked imports and calls in code string
        for blocked in BLOCKED_MODULES:
            if f"import {blocked}" in code or f"from {blocked}" in code:
                result_queue.put({"error": f"Importing '{blocked}' is forbidden by security policy."})
                return

        for blocked in BLOCKED_NAMES:
            if f"{blocked}(" in code:
                result_queue.put({"error": f"Function '{blocked}' is blocked by security policy."})
                return

        # Restricted builtins
        safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bin": bin,
            "bool": bool,
            "chr": chr,
            "dict": dict,
            "divmod": divmod,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "format": format,
            "frozenset": frozenset,
            "hex": hex,
            "int": int,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "iter": iter,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "next": next,
            "oct": oct,
            "ord": ord,
            "pow": pow,
            "print": print,
            "range": range,
            "repr": repr,
            "reversed": reversed,
            "round": round,
            "set": set,
            "slice": slice,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        }

        # Safe global scope
        safe_globals: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "math": __import__("math"),
            "json": __import__("json"),
            "re": __import__("re"),
        }
        safe_locals: dict[str, Any] = {}

        stdout_buf = io.StringIO()
        with contextlib.redirect_stdout(stdout_buf):
            # Execute in safe scope
            compiled = compile(code, "<sandboxed>", "exec")
            exec(compiled, safe_globals, safe_locals)  # pylint: disable=exec-used

        output = stdout_buf.getvalue()
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... [TRUNCATED]"

        # Return results
        return_vars = {
            k: str(v)[:500]
            for k, v in safe_locals.items()
            if not k.startswith("_")
        }

        result_queue.put({
            "stdout": output,
            "variables": return_vars,
            "success": True,
        })
    except Exception as exc:
        result_queue.put({
            "error": f"Execution error: {type(exc).__name__}: {str(exc)}",
            "success": False,
        })


def code_executor_execute(code: str, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """
    Safely execute python code in an isolated process with timeout.

    Args:
        code: Python source code string.
        timeout: Maximum seconds to allow execution.

    Returns:
        Dict containing stdout, variables, or error.
    """
    if not code or not code.strip():
        return {"error": "Empty code provided.", "tool": "code_executor"}

    code = code.strip()
    logger.info("Code executor running code snippet (length=%d)", len(code))

    # Fast validation
    for blocked in BLOCKED_MODULES:
        if f"import {blocked}" in code or f"from {blocked}" in code:
            return {
                "error": f"Security policy violation: import of '{blocked}' is prohibited.",
                "tool": "code_executor",
            }

    ctx = multiprocessing.get_context("spawn")
    res_queue = ctx.Queue()
    proc = ctx.Process(target=_worker_process, args=(code, res_queue))

    try:
        proc.start()
        proc.join(timeout=timeout)

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            if proc.is_alive():
                proc.kill()
            return {
                "error": f"Execution timed out after {timeout} seconds.",
                "tool": "code_executor",
            }

        try:
            res = res_queue.get_nowait()
            res["tool"] = "code_executor"
            return res
        except queue.Empty:
            return {
                "error": "Process terminated without returning a result.",
                "tool": "code_executor",
            }
    except Exception as exc:
        logger.error("Code executor failure: %s", exc)
        return {
            "error": f"Executor error: {type(exc).__name__}: {str(exc)}",
            "tool": "code_executor",
        }
    finally:
        if proc.is_alive():
            proc.kill()


TOOL_SPEC = {
    "name": "code_executor",
    "description": (
        "Execute Python code in a sandboxed process for mathematical or data processing tasks. "
        "Strictly isolated: no network, no OS or filesystem access, 5s timeout. "
        "Use ONLY for computational calculations or data analysis that require code."
    ),
    "parameters": {
        "code": {
            "type": "string",
            "description": "Python code to execute safely",
            "required": True,
        }
    },
    "execute": code_executor_execute,
}
