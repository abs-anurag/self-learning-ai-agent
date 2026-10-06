"""
Unit tests for the File Reader tool.

Source of truth: BLUEPRINT.md §13.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from backend.tools.file_reader import FileReaderTool


@pytest.mark.asyncio
async def test_file_reader_reads_valid_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = os.path.join(temp_dir, "sample.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Hello, agentic world!")

        tool = FileReaderTool()
        tool.root = temp_dir

        res = await tool.execute({}, path="sample.txt")
        assert "error" not in res
        assert res.get("result") == "Hello, agentic world!"


@pytest.mark.asyncio
async def test_file_reader_path_traversal_prevention():
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = FileReaderTool()
        tool.root = temp_dir

        res = await tool.execute({}, path="../../etc/passwd")
        assert "error" in res
        assert res["error_code"] == "PATH_TRAVERSAL"


@pytest.mark.asyncio
async def test_file_reader_missing_path():
    tool = FileReaderTool()
    res = await tool.execute({})
    assert "error" in res
    assert res["error_code"] == "MISSING_PATH"


@pytest.mark.asyncio
async def test_file_reader_nonexistent_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        tool = FileReaderTool()
        tool.root = temp_dir

        res = await tool.execute({}, path="does_not_exist.txt")
        assert "error" in res
        assert res["error_code"] == "FILE_NOT_FOUND"


def test_file_reader_metadata():
    tool = FileReaderTool()
    assert tool.name == "file_reader"
    assert tool.permission_level == "READ_ONLY"
