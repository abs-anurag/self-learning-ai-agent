"""
Unit tests for the Calculator tool.

Source of truth: BLUEPRINT.md §13.
"""

from __future__ import annotations

import pytest

from backend.tools.calculator import CalculatorTool


@pytest.mark.asyncio
async def test_calculator_direct_multiplication():
    tool = CalculatorTool()
    res = await tool.execute({}, expression="25 * 48")
    assert res.get("result") == 1200
    assert "error" not in res


@pytest.mark.asyncio
async def test_calculator_natural_language_phrase():
    tool = CalculatorTool()
    res = await tool.execute({}, expression="25 multiplied by 48")
    assert res.get("result") == 1200
    assert "error" not in res


@pytest.mark.asyncio
async def test_calculator_natural_language_sentence():
    tool = CalculatorTool()
    res = await tool.execute({}, expression="Calculate 25 multiplied by 48 and explain the result.")
    assert res.get("result") == 1200
    assert "error" not in res


@pytest.mark.asyncio
async def test_calculator_basic_operations():
    tool = CalculatorTool()
    assert (await tool.execute({}, expression="100 / 4"))["result"] == 25
    assert (await tool.execute({}, expression="15 + 35"))["result"] == 50
    assert (await tool.execute({}, expression="50 - 18"))["result"] == 32


@pytest.mark.asyncio
async def test_calculator_missing_expression():
    tool = CalculatorTool()
    res = await tool.execute({})
    assert "error" in res
    assert res["error_code"] == "MISSING_EXPRESSION"


@pytest.mark.asyncio
async def test_calculator_invalid_syntax():
    tool = CalculatorTool()
    res = await tool.execute({}, expression="this is not a math problem at all")
    assert "error" in res
    assert res["error_code"] == "INVALID_SYNTAX"


def test_calculator_metadata():
    tool = CalculatorTool()
    assert tool.name == "calculator"
    assert tool.permission_level == "READ_ONLY"
