"""
Unit tests for code executor tool.

Source of truth: BLUEPRINT.md §12, §13, §17.
Verifies safe code execution, forbidden imports blocking, and timeout handling.
"""

from __future__ import annotations

import pytest
from backend.tools.code_executor import code_executor_execute, TOOL_SPEC


def test_code_executor_spec():
    assert TOOL_SPEC["name"] == "code_executor"
    assert "code" in TOOL_SPEC["parameters"]


def test_safe_computation():
    code = """
a = 10
b = 20
c = a + b
print(f"Result: {c}")
"""
    res = code_executor_execute(code)
    assert res.get("success") is True
    assert "Result: 30" in res.get("stdout", "")
    assert res.get("variables", {}).get("c") == "30"


def test_blocked_os_import():
    code = "import os\nos.system('echo hacked')"
    res = code_executor_execute(code)
    assert "error" in res
    assert "prohibited" in res["error"].lower() or "forbidden" in res["error"].lower()


def test_blocked_subprocess():
    code = "import subprocess\nsubprocess.run(['ls'])"
    res = code_executor_execute(code)
    assert "error" in res


def test_execution_timeout():
    code = """
x = 0
while True:
    x = (x + 1) % 1000000
"""
    res = code_executor_execute(code, timeout=1.0)
    assert "error" in res
    assert "timed out" in res["error"].lower()
