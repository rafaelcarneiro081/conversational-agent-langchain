"""Script that contains the Pydantic Models for the Rest Response."""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    """Status."""

    SUCCESS = "success"
    FAILURE = "failure"


class SearchResponse(BaseModel):
    """The request parameters for explaining the output."""

    text: str = Field(..., title="Text", description="The text of the document.")
    page: int = Field(..., title="Page", description="The page of the document.")
    source: str = Field(..., title="Source", description="The source of the document.")
    score: float = Field(..., title="Score", description="The score of the document.")


class EmbeddingResponse(BaseModel):
    """The Response for the Embedding endpoint."""

    status: Status = Field(Status.SUCCESS, title="Status", description="The status of the request.")
    files: List[str] = Field([], title="Files", description="The list of files that were embedded.")


class QAResponse(BaseModel):
    """The Response for the QA endpoint."""

    answer: str = Field(..., title="Answer", description="The answer to the question.")
    prompt: str = Field(..., title="Prompt", description="The prompt used to generate the answer.")
    meta_data: Optional[dict[str, str]] = Field(None, title="Meta Data", description="The meta data of the answer.")


class ExplainQAResponse(BaseModel):
    """The Response for the Explain QA endpoint."""

    answer: str = Field(..., title="Answer", description="The answer to the question.")
    meta_data: Optional[dict[str, str]] = Field(None, title="Meta Data", description="The meta data of the answer.")
    explanation: str = Field(..., title="Explanation", description="The explanation for the answer.")
    text: str = Field(..., title="Text", description="The text of the document.")
    score: float = Field(..., title="Score", description="The score of the document.")
