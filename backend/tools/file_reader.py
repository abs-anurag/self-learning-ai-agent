"""
File reader tool with sandbox confinement.

Source of truth: BLUEPRINT.md §2, §12, §17.
File access is confined to FILE_READER_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

MAX_FILE_SIZE = 100_000  # 100KB max file read


def file_reader_execute(file_path: str) -> dict[str, Any]:
    """
    Read the contents of a file within the sandbox root.

    Args:
        file_path: Path to the file (relative to FILE_READER_ROOT or absolute within it).

    Returns:
        Dict with 'content' on success or 'error' on failure.
    """
    if not file_path or not file_path.strip():
        return {"error": "Empty file path provided.", "tool": "file_reader"}

    file_path = file_path.strip()
    sandbox_root = Path(settings.FILE_READER_ROOT).resolve()

    # Resolve the target path
    target = Path(file_path)
    if not target.is_absolute():
        target = sandbox_root / target
    target = target.resolve()

    # Security: ensure path is within sandbox
    try:
        target.relative_to(sandbox_root)
    except ValueError:
        logger.warning("File reader path escape attempt: %s", file_path)
        return {
            "error": f"Access denied. File must be within sandbox: {settings.FILE_READER_ROOT}",
            "tool": "file_reader",
        }

    if not target.exists():
        return {"error": f"File not found: {file_path}", "tool": "file_reader"}

    if not target.is_file():
        return {"error": f"Path is not a file: {file_path}", "tool": "file_reader"}

    try:
        file_size = target.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {
                "error": f"File too large ({file_size} bytes). Maximum: {MAX_FILE_SIZE} bytes.",
                "tool": "file_reader",
            }

        content = target.read_text(encoding="utf-8", errors="replace")
        logger.info("File reader read %d bytes from %s", len(content), target.name)
        return {
            "content": content,
            "file_name": target.name,
            "file_size": file_size,
            "tool": "file_reader",
        }

    except PermissionError:
        return {"error": f"Permission denied: {file_path}", "tool": "file_reader"}
    except Exception as exc:
        logger.error("File reader error for '%s': %s", file_path, type(exc).__name__)
        return {"error": f"File read failed: {type(exc).__name__}: {exc}", "tool": "file_reader"}


TOOL_SPEC = {
    "name": "file_reader",
    "description": (
        "Read the contents of a file from the sandbox directory. "
        "Use when the user asks to read, analyze, or process a file. "
        "Files must be within the configured sandbox root."
    ),
    "parameters": {
        "file_path": {
            "type": "string",
            "description": "Path to the file to read (relative to sandbox root)",
            "required": True,
        }
    },
    "execute": file_reader_execute,
}
