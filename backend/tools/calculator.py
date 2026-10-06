# -*- coding: utf-8 -*-
"""
Calculator tool for safe arithmetic evaluation.

Source of truth: BLUEPRINT.md S13.

Uses simpleeval with strict AST operator whitelist. No eval().
"""

from __future__ import annotations

import logging
from typing import Any

from backend.tools.registry import BaseTool
from simpleeval import simple_eval, DEFAULT_OPERATORS, DEFAULT_FUNCTIONS

logger = logging.getLogger(__name__)


class CalculatorTool(BaseTool):
    """Safe arithmetic calculator using simpleeval."""

    def __init__(self):
        super().__init__("calculator", "READ_ONLY")
        self._operators = {
            **DEFAULT_OPERATORS,
        }
        self._functions = {
            **DEFAULT_FUNCTIONS,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
        }

    def _extract_expression(self, expr: str) -> str:
        """Extract clean arithmetic expression from natural language text."""
        import re
        text = str(expr).lower().strip()
        text = re.sub(r'\bmultiplied\s+by\b', '*', text)
        text = re.sub(r'\btimes\b', '*', text)
        text = re.sub(r'\bdivided\s+by\b', '/', text)
        text = re.sub(r'\bplus\b', '+', text)
        text = re.sub(r'\bminus\b', '-', text)
        text = re.sub(r'\bx\b', '*', text)

        match = re.search(r'(\d+[\d\s\.\+\-\*/\(\)]*[\+\-\*/][\d\s\.\+\-\*/\(\)]*\d+)', text)
        if match:
            return match.group(1).strip()
        return text

    async def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        expression = kwargs.get("expression") or kwargs.get("query")
        if not expression:
            return {
                "error": "Missing expression parameter",
                "error_code": "MISSING_EXPRESSION",
            }
        try:
            result = simple_eval(
                expression,
                operators=self._operators,
                functions=self._functions,
            )
            return {
                "result": result,
            }
        except SyntaxError:
            # Fallback: try extracting arithmetic expression from natural language
            cleaned = self._extract_expression(expression)
            if cleaned != expression:
                try:
                    result = simple_eval(
                        cleaned,
                        operators=self._operators,
                        functions=self._functions,
                    )
                    return {
                        "result": result,
                    }
                except Exception:
                    pass
            logger.warning(f"[CalculatorTool] Syntax error in expression: {expression}")
            return {
                "error": "Invalid expression syntax",
                "error_code": "INVALID_SYNTAX",
            }
        except Exception as e:
            logger.error(f"[CalculatorTool] Evaluation error: {e}", exc_info=True)
            return {
                "error": str(e),
                "error_code": "EVALUATION_ERROR",
            }


__all__ = ["CalculatorTool"]
