"""
Self Search business logic service.

Coordinates document-grounded question answering:
- Formats grounded prompts with isolated document tags.
- Dispatches prompt to configured LLMProvider.generate().
- Robustly parses JSON completions.
- Programmatically verifies supporting passages against original document text.
- Rejects or downgrades fabricated or unsupported citations.
- Enforces zero-content logging (logs only lengths and metadata).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.providers.base import LLMProvider
from backend.agent.runtime import get_llm_provider
from backend.api.schemas_self_search import (
    SelfSearchResponse,
    SelfSearchSourcePassage,
)
from backend.core.logging import get_logger
from backend.self_search.prompts import (
    SELF_SEARCH_SYSTEM_PROMPT,
    SELF_SEARCH_USER_PROMPT,
)

logger = get_logger(__name__)


def _normalize_text(text: str) -> str:
    """
    Normalize text for robust fuzzy substring matching:
    - Collapses consecutive whitespace to single space
    - Normalizes smart quotes and dashes
    - Lowercases
    """
    if not text:
        return ""
    # Smart quotes and dashes
    t = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = t.replace("—", "-").replace("–", "-")
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t.lower()


class SelfSearchService:
    """
    Dedicated service for grounded document Q&A.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self.provider = provider or get_llm_provider()

    def verify_passages(
        self, document: str, raw_passages: List[Dict[str, Any]]
    ) -> Tuple[List[SelfSearchSourcePassage], int]:
        """
        Verify returned passages against the original document text.

        Returns:
            Tuple of (list of SelfSearchSourcePassage, count of verified passages)
        """
        verified_passages: List[SelfSearchSourcePassage] = []
        verified_count = 0

        norm_doc = _normalize_text(document)

        for p in raw_passages:
            if not isinstance(p, dict):
                continue

            raw_text = str(p.get("text", "")).strip()
            if not raw_text:
                continue

            relevance = str(p.get("relevance", "direct")).lower()
            if relevance not in ("direct", "inferred", "partial"):
                relevance = "direct"

            # 1. Exact match check
            exact_idx = document.find(raw_text)
            if exact_idx != -1:
                verified_passages.append(
                    SelfSearchSourcePassage(
                        text=raw_text,
                        relevance=relevance,
                        verified=True,
                        start_offset=exact_idx,
                        end_offset=exact_idx + len(raw_text),
                    )
                )
                verified_count += 1
                continue

            # 2. Normalized check (handling whitespace, quotes, dashes)
            norm_passage = _normalize_text(raw_text)
            if norm_passage and norm_passage in norm_doc:
                # Find approximate start offset in normalized document
                norm_idx = norm_doc.find(norm_passage)
                verified_passages.append(
                    SelfSearchSourcePassage(
                        text=raw_text,
                        relevance=relevance,
                        verified=True,
                        start_offset=norm_idx,
                        end_offset=norm_idx + len(norm_passage),
                    )
                )
                verified_count += 1
                continue

            # 3. Fabricated or altered quotation (not matched in document)
            verified_passages.append(
                SelfSearchSourcePassage(
                    text=raw_text,
                    relevance=relevance,
                    verified=False,
                    start_offset=None,
                    end_offset=None,
                )
            )

        return verified_passages, verified_count

    def _parse_llm_json(self, raw_output: str) -> Optional[Dict[str, Any]]:
        """
        Extract and parse JSON object from LLM response.
        Handles markdown fences and bracket searches.
        """
        if not raw_output or not raw_output.strip():
            return None

        text = raw_output.strip()

        # Try markdown code fence regex
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except Exception:
                pass

        # Try full string JSON parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try finding outer brackets
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass

        return None

    async def answer(self, document: str, question: str) -> SelfSearchResponse:
        """
        Answer question grounded in document with verified source citations.
        """
        doc_len = len(document)
        q_len = len(question)

        logger.info(
            "SelfSearchService.answer initiated (doc_length=%d, question_length=%d)",
            doc_len,
            q_len,
        )

        user_prompt = SELF_SEARCH_USER_PROMPT.format(document=document, question=question)

        try:
            raw_response = await self.provider.generate(
                prompt=user_prompt,
                system=SELF_SEARCH_SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.error(
                "SelfSearchService provider generate failed: %s (%s)",
                type(exc).__name__,
                exc,
            )
            raise RuntimeError(f"LLM generation failed: {type(exc).__name__}: {exc}")

        parsed = self._parse_llm_json(raw_response)

        # Fallback for malformed LLM responses
        if not parsed or not isinstance(parsed, dict) or "answer" not in parsed:
            logger.warning("SelfSearchService received malformed LLM response; returning safe fallback")
            return SelfSearchResponse(
                answer="Could not synthesize a structured grounded answer from the model output.",
                source_passages=[],
                confidence="unsupported",
                is_supported=False,
                explanation="The language model output was not valid structured JSON.",
            )

        answer_text = str(parsed.get("answer", "")).strip()
        confidence = str(parsed.get("confidence", "high")).lower()
        if confidence not in ("high", "medium", "low", "unsupported"):
            confidence = "medium"

        is_supported = bool(parsed.get("is_supported", True))
        explanation = parsed.get("explanation")
        if explanation is not None:
            explanation = str(explanation).strip() or None

        raw_passages = parsed.get("source_passages", [])
        if not isinstance(raw_passages, list):
            raw_passages = []

        # Programmatically verify source passages against document
        verified_passages, verified_count = self.verify_passages(document, raw_passages)

        # Safety Guard: If model claimed the answer is supported, but 0 passages could be verified
        if is_supported and verified_count == 0:
            logger.warning(
                "SelfSearchService: Model claimed support but 0 verified passages found; overriding to unsupported"
            )
            is_supported = False
            confidence = "unsupported"
            explanation = (
                "The response claimed support, but no verifiable supporting passages could "
                "be located in the provided document."
            )

        return SelfSearchResponse(
            answer=answer_text,
            source_passages=verified_passages,
            confidence=confidence,
            is_supported=is_supported,
            explanation=explanation,
        )
