# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-11-19

## Context
Ringbridge is open source from day one. Contributors need to know why the system looks the way it does, not only what it looks like.

## Decision
Significant decisions are recorded as short ADRs in `docs/adr/`, numbered, using `0000-template.md`. An ADR is **Proposed** until the spike or discussion behind it is done, then **Accepted**. ADRs are never edited after acceptance except to mark them superseded.

## Consequences
Every PR that changes an architectural boundary links an ADR or adds one.
