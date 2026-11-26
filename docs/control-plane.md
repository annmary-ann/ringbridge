# Control plane

`ringbridge-server` holds all durable state: agents and their published versions, SIP trunks,
phone numbers, calls and call events. It is a FastAPI app on Postgres 16 (SQLAlchemy 2 async +
asyncpg, Alembic migrations). Design: [architecture §3.3 and §9](architecture.md).

## Run it

```sh
uv run poe up        # Postgres and the rest of the dev stack (docs/dev-stack.md)
uv run poe migrate   # create or upgrade the tables
uv run poe serve     # http://127.0.0.1:8088, OpenAPI UI at /docs
```

`python -m ringbridge_server serve --migrate` does both steps in one, which suits containers.

Settings come from `RINGBRIDGE_*` environment variables or `.env`:

| Variable | Default | |
|---|---|---|
| `RINGBRIDGE_DATABASE_URL` | `postgresql://ringbridge:ringbridge@localhost:5435/ringbridge` | Any `postgresql://` URL; the asyncpg driver is added for you |
| `RINGBRIDGE_HOST` / `RINGBRIDGE_PORT` | `127.0.0.1` / `8088` | |
| `RINGBRIDGE_LOG_LEVEL` | `INFO` | |
| `RINGBRIDGE_LOG_JSON` | `true` | One JSON object per line; `false` for plain text |
| `RINGBRIDGE_DB_POOL_SIZE` / `RINGBRIDGE_DB_MAX_OVERFLOW` | `5` / `10` | |
| `RINGBRIDGE_MAX_SPEC_BYTES` | `1000000` | Largest spec a publish accepts |
| `RINGBRIDGE_WORKER_TOKEN` | unset | Shared secret for agent workers on `/internal` routes; unset disables them |

## Health

- `GET /healthz`: the process is up. Never touches the database.
- `GET /readyz`: 200 when the database answers within 2 s **and** its schema is at the
  migration head this build ships; 503 with a reason otherwise. Point load balancer readiness
  probes here, so a server never takes traffic against an unmigrated database.

Every response carries `x-request-id` (the caller's, or a new one), and every API request is
logged once with its id, status and duration.

## Agents and versions

An agent is a name. Its behaviour lives in **versions**: each publish validates an
[AgentSpec](agent-spec.md) and stores an immutable snapshot.

```sh
# create the agent (the name must equal metadata.name in its specs)
curl -X POST localhost:8088/v1/agents -H 'content-type: application/json' \
  -d '{"name": "smile-dental-receptionist"}'

# publish a version from YAML (application/json works too)
curl -X POST localhost:8088/v1/agents/$AGENT_ID/versions \
  -H 'content-type: application/yaml' --data-binary @examples/dental-clinic/agent.yaml
```

| Result | Meaning |
|---|---|
| `201` | New version stored (`version` counts up from 1), with any validator warnings |
| `200` | The spec is identical to the latest version, so nothing new was stored. Formatting and comments do not count, so CI can publish on every merge |
| `422` | The spec has errors: `{"detail", "issues": [{"severity", "path", "message", "line"}]}`, the same issues `ringbridge agent validate` prints |
| `404` / `413` / `400` | Unknown agent / body over the size limit / body not UTF-8 |

Each version stores both `spec` (the validated document with defaults filled in, which is
exactly what a worker runs) and `source` (the text as submitted, comments included) plus a
SHA-256 of the canonical spec. Concurrent publishes lock the agent row, so version numbers never
collide or skip.

Other endpoints: `GET /v1/agents`, `GET /v1/agents/{id}`, `GET /v1/agents/{id}/versions`,
`GET /v1/agents/{id}/versions/{n}`.

## Calls and events

Agent workers report what happens on a call as **events**. The control plane stores them in
order, exactly once, and builds the transcript from them.

**Worker API** (`/internal/calls`, needs `Authorization: Bearer $RINGBRIDGE_WORKER_TOKEN`;
without that setting the internal API answers 503):

| Endpoint | |
|---|---|
| `POST /internal/calls` | Register a call for a LiveKit room: `{"direction", "livekit_room", ...}`. Repeating it for the same room returns the same call (200 instead of 201) |
| `POST /internal/calls/{id}/events` | A batch of up to 500 events: `{"events": [...]}`. Returns `{"accepted", "duplicates", "status"}` |

Every event has `event_id` (chosen by the worker, unique within the call), `seq` (its order on
the call), `occurred_at` (with a time zone) and a `type`:

| Type | Fields |
|---|---|
| `call.started` | `from_number`, `to_number`. The call becomes `in_progress` |
| `turn` | `speaker` (`caller` or `agent`), `text`, `language`, `node`, `interrupted`, `started_at` |
| `tool_call` | `tool_call_id`, `name`, `arguments` |
| `tool_result` | `tool_call_id`, `name`, `ok`, `result`, `error`, `duration_ms` |
| `transition` | `from_node`, `to_node`, `reason` |
| `metric` | `name` (e.g. `voice_to_voice_ms`), `value`, `unit`, `turn_seq` |
| `call.ended` | `status` (`completed`, `no_answer`, `busy`, `failed`, `canceled`), `reason` |

The models live in `ringbridge_core.events`, so workers and the server share one definition.

Retrying is always safe. Events already stored are skipped by `event_id` and listed under
`duplicates`, even when several retries race. `call.started` and `call.ended` change the call
only the first time, so a replayed batch never reopens a finished call. Batches may arrive out
of order; `seq` decides the order when reading.

**Reading** (`/v1/calls`):

- `GET /v1/calls`: newest first, `?status=` to filter.
- `GET /v1/calls/{id}` and `GET /v1/calls/{id}/events` (`?type=turn&type=tool_call` to filter).
- `GET /v1/calls/{id}/transcript`: speaker, text and milliseconds since the call started for
  each turn, plus `complete` once the call has ended. `?format=text` gives plain text:

```
[00:01] Agent: Hello, Smile Dental. This call is answered by an AI assistant.
[00:05] Caller: I'd like a cleaning tomorrow morning.
```

## Data model

| Table | Notes |
|---|---|
| `projects` | Tenant boundary. One `default` project exists until multi-tenancy (#46) |
| `agents` | Unique `(project_id, name)`; name is a lowercase slug |
| `agent_versions` | Immutable: a trigger rejects every `UPDATE` |
| `sip_trunks` | `direction` is `inbound`, `outbound` or `both` |
| `phone_numbers` | E.164 only, globally unique. Routes to an agent, optionally pinned to one version |
| `calls` | `direction` (`inbound`, `outbound`, `web`) and `status` checked by constraints; one call per LiveKit room |
| `call_events` | Append-only (`UPDATE` rejected); unique `(call_id, event_id)` makes ingestion idempotent |

Every tenant table has `project_id`. Row-level security on it arrives with #46; until then all
requests act on the default project.

## Migrations

Migrations live in `packages/ringbridge-server/src/ringbridge_server/migrations/` and ship
inside the package, so no `alembic.ini` is needed.

```sh
uv run poe revision "add contacts"            # autogenerate from the models, then review it
uv run python -m ringbridge_server downgrade -1
```

A test compares the models with the migrated database and fails if a model changed without a
migration. Migrations never import from `models.py`, because a migration must not change when the
models do later.

## Tests

Integration tests (`pytest -m integration`) create a throwaway `ringbridge_test` database on the
dev stack's Postgres. They skip when Postgres is down. CI runs them against a Postgres service
with `RINGBRIDGE_REQUIRE_DB=1`, which turns a missing database into a failure.
