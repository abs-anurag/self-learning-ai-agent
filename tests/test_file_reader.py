"""
Unit tests for file reader tool.

Source of truth: BLUEPRINT.md §12, §13, §17.
Verifies sandbox containment, path traversal blocking, file size caps, and error handling.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from backend.core.config import settings
from backend.tools.file_reader import file_reader_execute, TOOL_SPEC, MAX_FILE_SIZE


@pytest.fixture
def sandbox_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        monkeypatch.setattr(settings, "FILE_READER_ROOT", str(tmp_path))
        yield tmp_path


def test_file_reader_spec():
    assert TOOL_SPEC["name"] == "file_reader"
    assert "file_path" in TOOL_SPEC["parameters"]
    assert TOOL_SPEC["parameters"]["file_path"]["required"] is True


def test_read_valid_file(sandbox_env):
    test_file = sandbox_env / "data.txt"
    test_file.write_text("Hello METIS Agent!", encoding="utf-8")

    res = file_reader_execute("data.txt")
    assert "content" in res
    assert res["content"] == "Hello METIS Agent!"
    assert res["file_name"] == "data.txt"


def test_traversal_attack_blocked(sandbox_env):
    res = file_reader_execute("../../../etc/passwd")
    assert "error" in res
    assert "denied" in res["error"].lower() or "sandbox" in res["error"].lower()


def test_file_not_found(sandbox_env):
    res = file_reader_execute("nonexistent.txt")
    assert "error" in res
    assert "not found" in res["error"].lower()


def test_file_size_limit(sandbox_env):
    large_file = sandbox_env / "large.txt"
    large_file.write_text("A" * (MAX_FILE_SIZE + 500), encoding="utf-8")

    res = file_reader_execute("large.txt")
    assert "error" in res
    assert "too large" in res["error"].lower()
