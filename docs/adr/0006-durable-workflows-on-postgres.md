# ADR-0006: Durable workflows on Postgres with DBOS Transact

- Status: Accepted (spike #6, 2026-11-21)
- Date: 2026-11-19 (proposed), 2026-11-21 (accepted)

## Context
Post-call processing, CRM sync, campaign scheduling, retries and delayed follow-ups must survive crashes and deploys, be exactly-once in effect, and be easy to self-host. Temporal is excellent but adds a cluster. Kafka is unnecessary at our scale. Outbound campaigns need a concurrency limit **per SIP trunk**, not just per worker.

## Decision
Use **DBOS Transact** (`dbos`, MIT). Its durable workflows and steps are checkpointed in Postgres, so the only stateful dependency stays Postgres.

- **Post-call, follow-ups and the outbox dispatcher** are DBOS workflows made of steps. Every step that touches the outside world passes an idempotency key (ADR-0010).
- **Campaign calls** go through a DBOS queue with `partition_concurrency`, using the SIP trunk as `queue_partition_key`.
- **Delays** use `delay_seconds` or durable sleep. **Recurring jobs** use DBOS schedules.
- **Tracing:** DBOS's OpenTelemetry export (`dbos[otel]`) feeds the same OTLP endpoint as the rest of Ringbridge (ADR-0012).
- **Isolation:** all use goes through a small internal interface in `ringbridge-server` (`enqueue`, `start_workflow`, `schedule`), so the engine can be replaced.

## Evidence
[docs/spikes/workflow-engine.md](../spikes/workflow-engine.md): the same crash, per-key concurrency and delay tests against DBOS, Procrastinate and a custom SKIP LOCKED engine.
- DBOS completed the crashed workflow automatically, held per-key concurrency at exactly 2, and needed no custom recovery code.
- Procrastinate supports only 1 per key and needs a hand-written stalled-job task.
- The custom engine works, but we would own leases, lease renewal, step checkpoints, schedules and tracing ourselves.

## Alternatives considered
- **Procrastinate.** Mature and MIT-licensed. Per-key concurrency is limited to 1, multi-step workflows are hand-chained and not atomic, dead-worker recovery is manual, and it has heavy install requirements (Django, Sphinx).
- **Thin custom engine.** Simple to start, but it becomes a project of its own.
- **Temporal.** The strongest guarantees, but it is a separate cluster to run, against goal 8 (easy self-hosting).

## Consequences
- Pin `dbos` and wrap it. Its 3.x API already removed direct `Queue(...)` construction.
- Run DBOS system-schema migrations as an explicit deploy and CI step, never on first use (the spike hit a race).
- Plan executor identity and recovery for multi-worker deployments (stable executor IDs or explicit recovery). Verify in #23.
- Every step is at-least-once: idempotency is mandatory, not optional.
