# ADR-0007: Connector SDK via entry points; HTTP and MCP tools

- Status: Accepted
- Date: 2026-11-19

## Context
"Any business" means many calendars, CRMs and messaging providers. We cannot maintain them all in core, and businesses also need their own systems (an inventory lookup, a policy check).

## Decision
- Typed provider protocols in `ringbridge-core`: `CalendarProvider`, `CRMProvider`, `MessagingProvider`. Every side-effecting method takes an `idem_key`.
- Connectors are Python packages registered under the `ringbridge.connectors` entry-point group. Built-ins live in `ringbridge-connectors`.
- A shared **contract test suite** that every connector must pass against a sandbox or fake.
- Custom tools: **HTTP webhook tools** (JSON Schema arguments, signed requests, timeout budget) and **MCP servers** (streamable HTTP), both scoped per graph node.

## Consequences
Credentials for connectors live in `connector_installs`, envelope-encrypted, and are resolved by the server, never by the LLM.
