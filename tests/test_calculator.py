"""
Unit tests for safe calculator tool.

Source of truth: BLUEPRINT.md §2, §12, §13.
Verifies arithmetic operations, safe math functions, and security constraints (no eval, no exec).
"""

from __future__ import annotations

import math
import pytest

from backend.tools.calculator import calculator_execute, TOOL_SPEC


def test_calculator_spec():
    assert TOOL_SPEC["name"] == "calculator"
    assert "expression" in TOOL_SPEC["parameters"]
    assert TOOL_SPEC["parameters"]["expression"]["required"] is True


def test_basic_arithmetic():
    assert calculator_execute("2 + 2")["result"] == 4
    assert calculator_execute("10 - 3")["result"] == 7
    assert calculator_execute("125 * 36")["result"] == 4500
    assert calculator_execute("100 / 4")["result"] == 25.0
    assert calculator_execute("2 ** 8")["result"] == 256
    assert calculator_execute("17 % 5")["result"] == 2


def test_safe_math_functions():
    assert calculator_execute("sqrt(144)")["result"] == 12.0
    assert calculator_execute("abs(-42)")["result"] == 42
    assert calculator_execute("round(3.14159, 2)")["result"] == 3.14
    assert calculator_execute("min(5, 2, 8)")["result"] == 2
    assert calculator_execute("max(5, 2, 8)")["result"] == 8
    assert math.isclose(calculator_execute("sin(pi / 2)")["result"], 1.0)


def test_invalid_expressions():
    res1 = calculator_execute("")
    assert "error" in res1

    res2 = calculator_execute("2 + +")
    assert "error" in res2

    res3 = calculator_execute("1 / 0")
    assert "error" in res3


def test_security_blocked_operations():
    # Attempting to call blocked builtins or import
    res1 = calculator_execute("__import__('os').system('ls')")
    assert "error" in res1

    res2 = calculator_execute("eval('2 + 2')")
    assert "error" in res2

    res3 = calculator_execute("open('/etc/passwd')")
    assert "error" in res3
