# Spike: durable workflow engine (#6)

- Date: 2026-11-21
- Decision: **DBOS Transact** (recorded in [ADR-0006](../adr/0006-durable-workflows-on-postgres.md))
- Code: [`spikes/0006-workflow-engine/`](../../spikes/0006-workflow-engine/), reproducible with one command

## Question

Ringbridge needs Postgres-backed durable execution for post-call processing, the outbox, outbound campaigns and delayed follow-ups ([architecture §3.4](../architecture.md#34-durable-workflows)). Which engine should it use: **DBOS Transact**, **Procrastinate**, or a **thin custom engine** on `FOR UPDATE SKIP LOCKED`?

## Method

Each engine runs the same three tests against Postgres 16 from the dev stack, on Linux (Docker), Python 3.12. Every job writes what it actually did to plain ledger tables, so all engines are judged the same way.

1. **Crash recovery.** A three-step post-call workflow (`extract → outbox → notify`). Step 2 performs its side effect and then holds for 3 s. The worker is killed with `SIGKILL` during that hold (worst case: the effect happened, but the step is not recorded as done). A fresh worker is started. Measured: did the workflow finish, how long recovery took, and how many times each step's side effect ran.
2. **Per-key concurrency** (per-trunk call limits). 10 jobs on `trunk-A` and 4 on `trunk-B`, each 1 s long, with a limit of **2 per key** and 8 worker slots. Measured: peak parallel jobs per key and wall time.
3. **Delayed job** (follow-up "in 10 minutes"). A job scheduled 3 s in the future. Measured: actual start delay.

Versions: `dbos==3.6.0`, `procrastinate==3.12.0`, `psycopg[binary]==3.3.9`.

## Results

Final clean run (all three engines in one pass):

| | DBOS 3.6 | Procrastinate 3.12 | Custom (SKIP LOCKED) |
|---|---|---|---|
| Workflow completed after `kill -9` | ✅ | ✅ (only with an extra stalled-job task) | ✅ |
| Recovery time | 4.2 s | 6.8 s | 4.3 s (= lease length) |
| Side-effect runs: extract / outbox / notify | 1 / **2** / 1 | 1 / **2** / 1 | 1 / **2** / 1 |
| Peak parallel per key (limit 2): A / B | **2 / 2** | 1 / 1 | **2 / 2** |
| Concurrency test wall time | 6.0 s | 10.8 s | 5.9 s |
| 3 s delayed job started after | 4.4 s | 4.7 s | 3.2 s |

Across earlier runs, DBOS recovery ranged from 2.3 to 4.2 s and its delay error from 0.4 to 1.4 s. The variation comes from polling intervals. It is irrelevant for follow-ups measured in minutes.

### What the numbers mean

- **Every engine re-runs the step that was in flight** (`outbox` ran twice). That is inherent: a crash between a side effect and its checkpoint cannot be detected. So exactly-once *in effect* must come from **idempotency keys** on every external call (ADR-0010), whichever engine we pick. Completed steps (`extract`) never re-ran with any engine.
- **Per-key concurrency is the deciding feature.**
  - DBOS has it natively (`partition_concurrency` + `queue_partition_key`).
  - Procrastinate's `lock` only serialises (1 per key). A limit of N would need N lock slots per trunk and our own bookkeeping, and the test took nearly twice as long.
  - The custom engine needed an advisory lock to make the per-key count race-free.
- **Recovery.**
  - DBOS recovers pending workflows when an executor with the same `executor_id` starts.
  - Procrastinate does not resurrect a dead worker's jobs by itself. We had to add a periodic task that retries stalled jobs and shorten the heartbeat to 1 s, because the defaults are a 10 s heartbeat and a 30 s stall timeout.
  - The custom engine recovers when a lease expires, so long steps need lease renewal, which we would have to build.

## Qualitative comparison

| | DBOS | Procrastinate | Custom |
|---|---|---|---|
| Model | Workflows of checkpointed steps | Tasks; workflows are hand-chained `defer()` calls | Whatever we build |
| Multi-step workflows | Native: a step's result is checkpointed and replayed | Next task deferred from inside a task (not atomic with the step's effect) | Our own step table |
| Per-key concurrency N | Native | 1 only | Built (advisory lock) |
| Delayed jobs | `delay_seconds` | `schedule_in` | `run_at` |
| Cron schedules | Schedules API | `@app.periodic` | Build it |
| Crash recovery | Automatic on executor restart | Needs our own stalled-job retry task | Lease expiry; renewal to build |
| OpenTelemetry | Built in (`dbos[otel]`, OTLP endpoints in config) | Middleware, our own | Our own |
| Extra infrastructure | None (Postgres) | None (Postgres) | None |
| Licence | MIT | MIT | — |
| Activity (Nov 2026) | ~1.7k stars, pushed today | ~1.5k stars, pushed today | — |
| Dependency weight | SQLAlchemy, psycopg; enterprise and OTel are optional extras | Pulls in Django, Sphinx, aiopg, psycopg2 as install requirements | None |

## Decision

**DBOS Transact**, behind Ringbridge's own small interface (`enqueue`, `start_workflow`, `schedule`), so it can be replaced.

## Gotchas found (carry into M1/M2)

1. **API churn.** In DBOS 3.x, `Queue(...)` can no longer be constructed directly. Queues are declared with `DBOS.register_queue(...)` and persisted in the system database. Pin the version and wrap it.
2. **Migrations race.** In one run, a `DBOSClient` enqueued before the worker had finished creating DBOS's system tables, which failed with `column "creator_xid" ... does not exist`. Run DBOS's system-schema migrations as an explicit deploy step (alongside Alembic), never implicitly at first use.
3. **Recovery is tied to `executor_id`.** The test restarted a worker with the same ID. In production, a workflow whose executor never returns must still be recovered: use stable executor IDs (e.g. a StatefulSet) or an explicit recovery path. Verify this in #23 before v0.1.
4. **At-least-once steps.** Design every step to be idempotent. The outbox (#24) must pass idempotency keys to providers.

## Reproduce

```sh
uv run poe up            # Postgres from the dev stack
cd spikes/0006-workflow-engine
docker run --rm --network ringbridge_default -v "$PWD":/spike -w /spike \
  ghcr.io/astral-sh/uv:0.10.12-python3.12-trixie-slim \
  uv run --no-project --with dbos==3.6.0 --with procrastinate==3.12.0 \
  --with "psycopg[binary]==3.3.9" python run.py
```

Results are written to `results.json`. The committed file is from the run in the table above.
