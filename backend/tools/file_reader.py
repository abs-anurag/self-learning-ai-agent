# -*- coding: utf-8 -*-
"""
File reader tool for safe local file reading.

Source of truth: BLUEPRINT.md S13.

Confined to FILE_READER_ROOT, realpath traversal check, 500 KB limit.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.tools.registry import BaseTool

try:
    from backend.core.config import settings
except ImportError:
    from backend.config import settings

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 500 * 1024


class FileReaderTool(BaseTool):
    """Safe file reader with path traversal protection."""

    def __init__(self):
        super().__init__("file_reader", "READ_ONLY")
        self.root = getattr(settings, "FILE_READER_ROOT", os.getcwd())

    async def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        path = kwargs.get("path") or kwargs.get("file_path")
        if not path:
            return {
                "error": "Missing path parameter",
                "error_code": "MISSING_PATH",
            }
        try:
            requested = os.path.join(self.root, path)
            real_requested = os.path.realpath(requested)
            real_root = os.path.realpath(self.root)
            if not real_requested.startswith(real_root):
                logger.warning(f"[FileReaderTool] Path traversal attempt: {path}")
                return {
                    "error": "Path traversal not allowed",
                    "error_code": "PATH_TRAVERSAL",
                }
            if not os.path.exists(real_requested):
                return {
                    "error": "File not found",
                    "error_code": "FILE_NOT_FOUND",
                }
            if not os.path.isfile(real_requested):
                return {
                    "error": "Not a file",
                    "error_code": "NOT_A_FILE",
                }
            file_size = os.path.getsize(real_requested)
            if file_size > MAX_READ_SIZE:
                return {
                    "error": "File too large (max 500 KB)",
                    "error_code": "FILE_TOO_LARGE",
                }
            with open(real_requested, "r", encoding="utf-8") as f:
                content = f.read(MAX_READ_SIZE)
            return {
                "result": content,
            }
        except UnicodeDecodeError:
            logger.warning(f"[FileReaderTool] Binary file: {path}")
            return {
                "error": "Cannot read binary file",
                "error_code": "BINARY_FILE",
            }
        except Exception as e:
            logger.error(f"[FileReaderTool] Read error: {e}", exc_info=True)
            return {
                "error": str(e),
                "error_code": "READ_ERROR",
            }


__all__ = ["FileReaderTool"]
