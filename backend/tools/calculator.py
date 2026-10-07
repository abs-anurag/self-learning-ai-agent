"""
Safe calculator tool using simpleeval.

Source of truth: BLUEPRINT.md §2, §12.
The calculator NEVER uses eval(). Uses simpleeval for safe expression parsing.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from backend.core.logging import get_logger

logger = get_logger(__name__)

# Allowed functions and names for the calculator
SAFE_NAMES: Dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "pow": pow,
    "sqrt": math.sqrt,
    "pi": math.pi,
    "e": math.e,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}

SAFE_FUNCTIONS: Dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "pow": pow,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}


def calculator_execute(expression: str) -> dict[str, Any]:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: Mathematical expression string (e.g., "125 * 36")

    Returns:
        Dict with 'result' on success or 'error' on failure.
    """
    if not expression or not expression.strip():
        return {"error": "Empty expression provided.", "tool": "calculator"}

    expression = expression.strip()
    logger.info("Calculator evaluating: %s", expression)

    try:
        from simpleeval import simple_eval, InvalidExpression

        result = simple_eval(
            expression,
            names=SAFE_NAMES,
            functions=SAFE_FUNCTIONS,
        )

        # Ensure result is a JSON-serializable number
        if isinstance(result, (int, float, complex)):
            if isinstance(result, complex):
                result_str = str(result)
            else:
                result_str = str(result)
            return {
                "result": result,
                "result_text": result_str,
                "expression": expression,
                "tool": "calculator",
            }
        else:
            return {
                "result": result,
                "result_text": str(result),
                "expression": expression,
                "tool": "calculator",
            }

    except ImportError:
        logger.error("simpleeval not installed")
        return {"error": "Calculator dependency (simpleeval) not available.", "tool": "calculator"}
    except (InvalidExpression, SyntaxError, TypeError, ValueError) as exc:
        logger.warning("Calculator error for '%s': %s", expression, exc)
        return {"error": f"Invalid expression: {exc}", "tool": "calculator"}
    except Exception as exc:
        logger.error("Unexpected calculator error for '%s': %s", expression, type(exc).__name__)
        return {"error": f"Calculator error: {type(exc).__name__}: {exc}", "tool": "calculator"}


TOOL_SPEC = {
    "name": "calculator",
    "description": (
        "Evaluate mathematical expressions safely. "
        "Supports arithmetic (+, -, *, /, **, %), "
        "functions (sqrt, log, sin, cos, tan, abs, round, min, max), "
        "and constants (pi, e). "
        "Use ONLY for numerical computation."
    ),
    "parameters": {
        "expression": {
            "type": "string",
            "description": "The mathematical expression to evaluate (e.g., '125 * 36', 'sqrt(144)')",
            "required": True,
        }
    },
    "execute": calculator_execute,
}
