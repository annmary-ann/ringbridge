# ADR-0004: Python monorepo with a uv workspace; FastAPI control plane

- Status: Accepted
- Date: 2026-11-19

## Context
The agent worker must be Python (the LiveKit Agents ecosystem and provider plugins). A Go control plane would be fast, but contributors would then need two languages and two toolchains, and domain types would be duplicated.

## Decision
- One repository, one `uv` workspace, separate packages: `ringbridge-core`, `-agent`, `-server`, `-connectors`, `-sim`, `-cli`.
- Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2.
- Tooling: ruff (lint + format), mypy strict, pytest, pre-commit, gitleaks. Conventional commits, squash merges.
- The dashboard (Next.js) lives in `apps/dashboard` and uses only the public API.

## Consequences
Shared Pydantic models (AgentSpec, events, connector types) are written once in `ringbridge-core`. Packages are published to PyPI separately so a connector author depends only on `ringbridge-core`.
