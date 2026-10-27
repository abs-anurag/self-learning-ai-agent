"""
Comprehensive unit and integration tests for the Self Search feature.

Covers:
1. Pydantic request & response validation (lengths, whitespace, limits).
2. Programmatic passage verification (exact match, normalized match, fabricated rejection).
3. Override safety: unsupported answers when verified passages are missing.
4. Robust JSON parsing and malformed response fallbacks.
5. Provider generation (FixtureProvider in demo mode and custom mocked providers).
6. FastAPI route authentication, validation, and error envelopes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.agent.providers.fixture import FixtureProvider
from backend.agent.runtime import get_llm_provider
from backend.api.dependencies import get_current_user
from backend.api.main import create_app
from backend.api.schemas_self_search import (
    SelfSearchRequest,
    SelfSearchResponse,
    SelfSearchSourcePassage,
)
from backend.core.config import ExecutionMode, settings
from backend.db.models import User
from backend.self_search.service import SelfSearchService, _normalize_text


# =====================================================================
# 1. Schema Validation Tests
# =====================================================================


class TestSelfSearchSchemas:
    """Verifies input and output validation constraints for Self Search."""

    def test_valid_request(self) -> None:
        req = SelfSearchRequest(
            document="PostgreSQL is an open-source relational database.",
            question="What type of database is PostgreSQL?",
        )
        assert req.document == "PostgreSQL is an open-source relational database."
        assert req.question == "What type of database is PostgreSQL?"

    def test_empty_or_whitespace_document_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SelfSearchRequest(document="   \n\t  ", question="Valid question?")
        assert "Document cannot be empty" in str(exc_info.value)

    def test_empty_or_whitespace_question_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SelfSearchRequest(
                document="Valid document text here.", question="   \t  "
            )
        assert "Question cannot be empty" in str(exc_info.value)

    def test_oversized_document_rejected(self) -> None:
        huge_doc = "A" * 100001
        with pytest.raises(ValidationError):
            SelfSearchRequest(document=huge_doc, question="Valid question?")

    def test_oversized_question_rejected(self) -> None:
        huge_q = "Q" * 2001
        with pytest.raises(ValidationError):
            SelfSearchRequest(
                document="Valid document content.", question=huge_q
            )

    def test_source_passage_schema_and_offsets(self) -> None:
        passage = SelfSearchSourcePassage(
            text="Relational database system.",
            relevance="direct",
            verified=True,
            start_offset=15,
            end_offset=42,
        )
        assert passage.verified is True
        assert passage.start_offset == 15
        assert passage.end_offset == 42

    def test_response_schema_defaults(self) -> None:
        res = SelfSearchResponse(
            answer="PostgreSQL is relational.",
            source_passages=[],
        )
        assert res.is_supported is True
        assert res.confidence == "high"
        assert res.explanation is None


# =====================================================================
# 2. Passage Verification Tests
# =====================================================================


class TestPassageVerification:
    """Tests the deterministic two-stage passage matching mechanism."""

    def setup_method(self) -> None:
        self.service = SelfSearchService(provider=FixtureProvider())
        self.sample_document = (
            "METIS is a self-learning AI agent architecture designed for repeatable task execution. "
            "It uses PostgreSQL 15 and Redis 7 as core persistence layers. "
            "The system promotes candidate recipes when the judge score reaches or exceeds 8.5."
        )

    def test_exact_passage_matching(self) -> None:
        exact_quote = "It uses PostgreSQL 15 and Redis 7 as core persistence layers."
        passages = [{"text": exact_quote, "relevance": "direct"}]

        verified, count = self.service.verify_passages(self.sample_document, passages)

        assert count == 1
        assert len(verified) == 1
        assert verified[0].verified is True
        assert verified[0].start_offset == self.sample_document.find(exact_quote)
        assert verified[0].end_offset == verified[0].start_offset + len(exact_quote)

    def test_normalized_whitespace_and_quote_matching(self) -> None:
        # Quote with collapsed line breaks and alternate quotes
        messy_quote = "It   uses\nPostgreSQL 15   and   Redis 7   as core persistence layers."
        passages = [{"text": messy_quote, "relevance": "direct"}]

        verified, count = self.service.verify_passages(self.sample_document, passages)

        assert count == 1
        assert verified[0].verified is True
        assert verified[0].start_offset is not None

    def test_fabricated_passage_rejected(self) -> None:
        fake_quote = "METIS uses MongoDB for document caching."
        passages = [{"text": fake_quote, "relevance": "direct"}]

        verified, count = self.service.verify_passages(self.sample_document, passages)

        assert count == 0
        assert len(verified) == 1
        assert verified[0].verified is False
        assert verified[0].start_offset is None
        assert verified[0].end_offset is None

    def test_override_unsupported_when_zero_verified_passages(self) -> None:
        """
        When the model asserts is_supported=True, but returns only fabricated passages
        or no verifiable passages, the service must override is_supported to False.
        """
        fake_passages = [{"text": "Completely hallucinated quote that does not exist in doc."}]
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "answer": "METIS uses MongoDB everywhere.",
                    "source_passages": fake_passages,
                    "confidence": "high",
                    "is_supported": True,
                    "explanation": None,
                }
            )
        )

        service = SelfSearchService(provider=mock_provider)
        response = pytest.run_async = asyncio = None

        import asyncio
        res = asyncio.run(service.answer(self.sample_document, "What database is used?"))

        assert res.is_supported is False
        assert res.confidence == "unsupported"
        assert "no verifiable supporting passages" in (res.explanation or "")


# =====================================================================
# 3. JSON Parsing & Malformed LLM Responses
# =====================================================================


class TestLLMResponseParsing:
    """Tests JSON extraction, code fence handling, and malformed fallback."""

    def test_parse_clean_json(self) -> None:
        service = SelfSearchService(provider=FixtureProvider())
        clean = '{"answer": "Test answer", "is_supported": true}'
        parsed = service._parse_llm_json(clean)
        assert parsed == {"answer": "Test answer", "is_supported": True}

    def test_parse_markdown_fenced_json(self) -> None:
        service = SelfSearchService(provider=FixtureProvider())
        fenced = """Here is the result:
```json
{
  "answer": "Grounded answer from fence",
  "confidence": "high",
  "is_supported": true
}
```
Hope that helps!"""
        parsed = service._parse_llm_json(fenced)
        assert parsed is not None
        assert parsed["answer"] == "Grounded answer from fence"

    def test_parse_bracket_embedded_json(self) -> None:
        service = SelfSearchService(provider=FixtureProvider())
        embedded = "Sure! Here is the JSON: {\"answer\": \"Extracted\", \"confidence\": \"medium\"} Thanks."
        parsed = service._parse_llm_json(embedded)
        assert parsed is not None
        assert parsed["answer"] == "Extracted"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_safe_fallback(self) -> None:
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value="I am an LLM and I forgot to return JSON entirely!"
        )
        service = SelfSearchService(provider=mock_provider)

        res = await service.answer("Some document.", "Some question?")

        assert res.is_supported is False
        assert res.confidence == "unsupported"
        assert "Could not synthesize a structured grounded answer" in res.answer
        assert "valid structured JSON" in (res.explanation or "")


# =====================================================================
# 4. Provider Generation & Fixture Mode Tests
# =====================================================================


class TestProviderGeneration:
    """Verifies generate() on FixtureProvider and error safety."""

    @pytest.mark.asyncio
    async def test_fixture_provider_grounded_answer(self) -> None:
        fixture = FixtureProvider()
        doc = (
            "The capital of Japan is Tokyo. "
            "Mount Fuji is the tallest mountain in Japan at 3,776 meters."
        )
        question = "What is the tallest mountain in Japan?"

        service = SelfSearchService(provider=fixture)
        res = await service.answer(doc, question)

        assert res.is_supported is True
        assert "Mount Fuji" in res.answer
        assert len(res.source_passages) >= 1
        assert res.source_passages[0].verified is True
        assert "Mount Fuji" in res.source_passages[0].text

    @pytest.mark.asyncio
    async def test_fixture_provider_unsupported_topic(self) -> None:
        fixture = FixtureProvider()
        doc = "This document only discusses baking sourdough bread and hydration levels."
        question = "Who won the 1994 World Cup?"

        service = SelfSearchService(provider=fixture)
        res = await service.answer(doc, question)

        assert res.is_supported is False
        assert res.confidence == "unsupported"

    @pytest.mark.asyncio
    async def test_provider_failure_raises_runtime_error(self) -> None:
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("Provider timed out"))
        service = SelfSearchService(provider=mock_provider)

        with pytest.raises(RuntimeError) as exc_info:
            await service.answer("Doc content", "Question?")
        assert "LLM generation failed: RuntimeError" in str(exc_info.value)


# =====================================================================
# 5. FastAPI Route Integration Tests (POST /self-search/ask)
# =====================================================================


class TestSelfSearchApiEndpoint:
    """Tests the /self-search/ask endpoint with authentication and validation."""

    def setup_method(self) -> None:
        self.app = create_app()
        self.mock_user = User(
            id=uuid.uuid4(),
            api_key_hash="hash_dummy",
            display_name="Test User",
        )

    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(self.app, raise_server_exceptions=False)
        payload = {
            "document": "Some valid document content.",
            "question": "Some valid question?",
        }
        res = client.post("/self-search/ask", json=payload)
        assert res.status_code == 401
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_authenticated_request_succeeds(self) -> None:
        # Override get_current_user dependency
        self.app.dependency_overrides[get_current_user] = lambda: self.mock_user
        client = TestClient(self.app, raise_server_exceptions=False)

        payload = {
            "document": "The speed of light in vacuum is approximately 299,792,458 meters per second.",
            "question": "What is the speed of light?",
        }

        res = client.post(
            "/self-search/ask",
            json=payload,
            headers={"X-API-Key": "test_valid_key"},
        )

        assert res.status_code == 200
        data = res.json()
        assert "answer" in data
        assert "source_passages" in data
        assert "is_supported" in data
        assert "confidence" in data
        assert data["is_supported"] is True

    def test_empty_document_returns_422(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: self.mock_user
        client = TestClient(self.app, raise_server_exceptions=False)

        payload = {
            "document": "   ",
            "question": "Valid question?",
        }
        res = client.post(
            "/self-search/ask",
            json=payload,
            headers={"X-API-Key": "test_valid_key"},
        )
        assert res.status_code == 422
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_question_returns_422(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: self.mock_user
        client = TestClient(self.app, raise_server_exceptions=False)

        payload = {
            "document": "Valid document content.",
            "question": "   \n\t  ",
        }
        res = client.post(
            "/self-search/ask",
            json=payload,
            headers={"X-API-Key": "test_valid_key"},
        )
        assert res.status_code == 422
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"
