"""Request and response bodies for the public API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ringbridge_core.spec import Issue, Severity
from ringbridge_server.models import SLUG_PATTERN


class IssueOut(BaseModel):
    severity: Severity
    path: str = Field(description="Dotted path into the document, e.g. spec.graph.nodes[2].tools")
    message: str
    line: int | None = Field(description="1-based line in the submitted document, when known")

    @classmethod
    def of(cls, issue: Issue) -> IssueOut:
        return cls(
            severity=issue.severity, path=issue.dotted, message=issue.message, line=issue.line
        )


class SpecRejected(BaseModel):
    detail: str
    issues: list[IssueOut]


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        pattern=SLUG_PATTERN,
        max_length=63,
        description="Lowercase identifier; must equal metadata.name in every published spec.",
        examples=["smile-dental-receptionist"],
    )
    description: str | None = Field(default=None, max_length=2000)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    latest_version: int | None = None


class AgentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    api_version: str
    spec_sha256: str
    published_at: datetime


class AgentVersionOut(AgentVersionSummary):
    spec: dict[str, Any] = Field(description="The validated spec with defaults filled in")
    source: str = Field(description="The document exactly as submitted")


class PublishedVersion(AgentVersionOut):
    warnings: list[IssueOut] = Field(default_factory=list)
