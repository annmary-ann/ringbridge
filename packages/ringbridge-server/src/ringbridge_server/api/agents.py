"""Agents and their published, immutable versions."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ringbridge_core.spec import Issue, load_text
from ringbridge_server.api.deps import ProjectDep, SessionDep, SettingsDep
from ringbridge_server.api.schemas import (
    AgentCreate,
    AgentOut,
    AgentVersionOut,
    AgentVersionSummary,
    IssueOut,
    PublishedVersion,
    SpecRejected,
)
from ringbridge_server.models import Agent, AgentVersion

router = APIRouter(prefix="/v1/agents", tags=["agents"])

_SPEC_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "An AgentSpec document as YAML or JSON (see docs/agent-spec.md).",
        "content": {
            "application/yaml": {"schema": {"type": "string"}},
            "application/json": {
                "schema": {"$ref": "https://ringbridge.dev/schema/agent-v1alpha1.json"}
            },
        },
    }
}


def _canonical_sha256(spec: dict[str, Any]) -> str:
    """Hash of the normalised spec: formatting and comments do not change it."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _agent_or_404(
    session: SessionDep, project_id: uuid.UUID, agent_id: uuid.UUID, *, lock: bool = False
) -> Agent:
    stmt = select(Agent).where(Agent.id == agent_id, Agent.project_id == project_id)
    if lock:
        stmt = stmt.with_for_update()
    agent = (await session.execute(stmt)).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent


class SpecRejectedError(Exception):
    """A submitted spec failed validation; rendered as 422 listing every issue."""

    def __init__(self, detail: str, issues: list[Issue]) -> None:
        super().__init__(detail)
        self.body = SpecRejected(detail=detail, issues=[IssueOut.of(i) for i in issues])


async def spec_rejected_handler(_: Request, exc: Exception) -> JSONResponse:
    body = exc.body if isinstance(exc, SpecRejectedError) else None
    if body is None:  # pragma: no cover - only registered for SpecRejectedError
        raise exc
    return JSONResponse(body.model_dump(), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


@router.post(
    "", status_code=status.HTTP_201_CREATED, responses={409: {"description": "Name taken"}}
)
async def create_agent(body: AgentCreate, session: SessionDep, project_id: ProjectDep) -> AgentOut:
    agent = Agent(project_id=project_id, name=body.name, description=body.description)
    session.add(agent)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"an agent named {body.name!r} already exists"
        ) from None
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.get("")
async def list_agents(
    session: SessionDep,
    project_id: ProjectDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentOut]:
    latest = func.max(AgentVersion.version)
    rows = await session.execute(
        select(Agent, latest)
        .outerjoin(AgentVersion, AgentVersion.agent_id == Agent.id)
        .where(Agent.project_id == project_id)
        .group_by(Agent.id)
        .order_by(Agent.name)
        .limit(limit)
        .offset(offset)
    )
    return [
        AgentOut.model_validate(agent).model_copy(update={"latest_version": version})
        for agent, version in rows
    ]


@router.get("/{agent_id}", responses={404: {"description": "Not found"}})
async def get_agent(agent_id: uuid.UUID, session: SessionDep, project_id: ProjectDep) -> AgentOut:
    agent = await _agent_or_404(session, project_id, agent_id)
    latest = await session.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id)
    )
    return AgentOut.model_validate(agent).model_copy(update={"latest_version": latest})


@router.post(
    "/{agent_id}/versions",
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_SPEC_BODY,
    responses={
        200: {"model": PublishedVersion, "description": "Identical to the latest version"},
        404: {"description": "Agent not found"},
        413: {"description": "Spec too large"},
        422: {"model": SpecRejected, "description": "The spec has errors"},
    },
)
async def publish_version(
    agent_id: uuid.UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    project_id: ProjectDep,
    settings: SettingsDep,
) -> PublishedVersion:
    """Validate a spec and store it as the agent's next immutable version.

    Publishing a spec identical to the latest version (ignoring formatting and comments)
    returns that version with 200 instead of creating a new one, so CI can publish on every
    merge without piling up duplicates.
    """
    # Lock the agent row: concurrent publishes get consecutive version numbers.
    agent = await _agent_or_404(session, project_id, agent_id, lock=True)

    raw = await request.body()
    if len(raw) > settings.max_spec_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"spec exceeds {settings.max_spec_bytes} bytes"
        )
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the body must be UTF-8") from None

    report = load_text(source, source="spec")
    if not report.ok or report.spec is None:
        count = len(report.errors)
        raise SpecRejectedError(
            f"the spec has {count} error{'s' if count != 1 else ''}", report.errors
        )

    if report.spec.metadata.name != agent.name:
        mismatch = Issue(
            "error",
            ("metadata", "name"),
            f"metadata.name is {report.spec.metadata.name!r} but this agent is {agent.name!r}",
        )
        raise SpecRejectedError("the spec belongs to a different agent", [mismatch])

    spec = report.spec.model_dump(mode="json", by_alias=True)
    sha = _canonical_sha256(spec)
    warnings = [IssueOut.of(i) for i in report.warnings]

    latest = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None and latest.spec_sha256 == sha:
        response.status_code = status.HTTP_200_OK
        return PublishedVersion.model_validate(latest).model_copy(update={"warnings": warnings})

    version = AgentVersion(
        project_id=project_id,
        agent_id=agent.id,
        version=(latest.version + 1) if latest else 1,
        api_version=report.spec.api_version,
        spec=spec,
        source=source,
        spec_sha256=sha,
    )
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return PublishedVersion.model_validate(version).model_copy(update={"warnings": warnings})


@router.get("/{agent_id}/versions", responses={404: {"description": "Agent not found"}})
async def list_versions(
    agent_id: uuid.UUID, session: SessionDep, project_id: ProjectDep
) -> list[AgentVersionSummary]:
    await _agent_or_404(session, project_id, agent_id)
    rows = await session.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
    )
    return [AgentVersionSummary.model_validate(v) for v in rows]


@router.get("/{agent_id}/versions/{version}", responses={404: {"description": "Not found"}})
async def get_version(
    agent_id: uuid.UUID,
    version: int,
    session: SessionDep,
    project_id: ProjectDep,
) -> AgentVersionOut:
    await _agent_or_404(session, project_id, agent_id)
    found = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id, AgentVersion.version == version
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return AgentVersionOut.model_validate(found)
