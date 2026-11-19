# ADR-0009: Multi-tenancy with organisations, projects and Postgres row-level security

- Status: Accepted
- Date: 2026-11-19

## Context
Agencies and SaaS builders will run many businesses on one deployment. A missed `WHERE project_id = ...` must not leak another business's call recordings.

## Decision
`organizations → projects`. Every tenant table has `project_id`. Postgres RLS policies use `current_setting('app.project_id')`, set per transaction from the authenticated API key. The application uses a non-superuser role so RLS cannot be bypassed. Single-tenant self-hosters get one default project.

## Consequences
Background workflows must set the tenant context explicitly. Tests include cross-tenant access attempts that must fail.
