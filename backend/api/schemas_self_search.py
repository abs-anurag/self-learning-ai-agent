"""
Request and Response Schemas for Self Search.

Provides Pydantic models for document-grounded question answering:
- SelfSearchRequest: Validates document and question lengths and rejects empty/whitespace input.
- SelfSearchSourcePassage: Supporting source quotation with deterministic verification metadata and offsets.
- SelfSearchResponse: Grounded answer response format.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SelfSearchRequest(BaseModel):
    """
    Request payload for answering a question grounded in a user-provided document.
    """
    model_config = ConfigDict(extra="forbid")

    document: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="The source text document (up to 100,000 characters).",
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The natural-language question grounded in the document (up to 2,000 characters).",
    )

    @field_validator("document")
    @classmethod
    def validate_document(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Document cannot be empty or contain only whitespace.")
        return trimmed

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Question cannot be empty or contain only whitespace.")
        return trimmed


class SelfSearchSourcePassage(BaseModel):
    """
    A quotation or passage from the document that supports the answer.
    """
    model_config = ConfigDict(extra="ignore")

    text: str = Field(..., description="Quotation text from the document.")
    relevance: str = Field(
        default="direct",
        description="Relevance classification: 'direct' | 'inferred' | 'partial'.",
    )
    verified: bool = Field(
        default=False,
        description="Whether this passage was programmatically verified in the document.",
    )
    start_offset: Optional[int] = Field(
        default=None,
        description="Start character index of the passage in the original document.",
    )
    end_offset: Optional[int] = Field(
        default=None,
        description="End character index of the passage in the original document.",
    )


class SelfSearchResponse(BaseModel):
    """
    Structured grounded answer response.
    """
    model_config = ConfigDict(extra="ignore")

    answer: str = Field(..., description="Grounded answer to the question.")
    source_passages: List[SelfSearchSourcePassage] = Field(
        default_factory=list,
        description="Supporting passages from the document.",
    )
    confidence: str = Field(
        default="high",
        description="Confidence level: 'high' | 'medium' | 'low' | 'unsupported'.",
    )
    is_supported: bool = Field(
        default=True,
        description="True if the document provides evidence supporting the answer; False otherwise.",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Explanation when an answer is unsupported or ambiguous.",
    )
