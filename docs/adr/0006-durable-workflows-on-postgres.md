# ADR-0006: Durable workflows on Postgres

- Status: Proposed (spike in M0)
- Date: 2026-11-19

## Context
Post-call processing, CRM sync, campaign scheduling, retries and delayed follow-ups must survive crashes and deploys, run exactly-once in effect, and be easy to self-host. Temporal is excellent but adds a cluster. Kafka is unnecessary at our scale.

## Decision (proposed)
Use a Postgres-backed durable workflow library so the only stateful dependency is Postgres. Candidates for the M0 spike:
1. **DBOS Transact (Python)**: durable workflows and steps checkpointed in Postgres, queues with concurrency limits, scheduled workflows.
2. **Procrastinate**: a mature Postgres task queue. Workflows would be composed by hand.
3. **Thin custom engine** on `SELECT ... FOR UPDATE SKIP LOCKED`.

Selection criteria: crash-recovery test, per-key concurrency (trunk limits), delayed and scheduled jobs, observability hooks (OTel), licence, maintenance activity.

## Consequences
Whichever we pick sits behind a small internal interface (`enqueue`, `schedule`, `run_workflow`) so it can be replaced.
