from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexusai.documents.api import Category


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=3, max_length=500)
    k: int = Field(default=5, ge=1, le=5)
    document_ids: list[UUID] = Field(default_factory=list, max_length=200)
    category: Category | None = None

    @field_validator("query")
    @classmethod
    def meaningful_query(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Enter a question")
        return value.strip()


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(pattern=r"^S[1-5]$")
    quote: str = Field(min_length=1, max_length=600)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selections: list[Selection] = Field(max_length=3)


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_sha256: str
    chunk_sha256: str
    filename: str
    locator: str
    block: int
    start: int
    end: int
    quote: str
    url: str


class Answer(BaseModel):
    request_id: UUID
    status: Literal["EXTRACTIVE", "ABSTAINED"]
    answer: str
    citations: list[Citation]
    generation_id: UUID | None
    model: str | None
    model_digest: str | None
    prompt_version: str
    reason: str
    retrieved: int
    context_sources: int
    context_truncated: bool
    duration_ms: float
    support_assessment: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Quotes match source text; relevance and completeness are not independently verified.",
            "Conflicts, authority and numerical calculations are not assessed in this phase.",
        ]
    )
