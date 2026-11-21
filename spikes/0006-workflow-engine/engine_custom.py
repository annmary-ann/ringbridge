"""A thin custom engine: one jobs table, FOR UPDATE SKIP LOCKED, leases, step checkpoints.

python engine_custom.py init | worker
python engine_custom.py start-post-call | enqueue-concurrency | enqueue-delay
"""

import json
import sys
import threading
import time

import psycopg
from common import effect, mark_ready, post_call_steps, span, started, url

DB = "spike_custom"
LEASE_S = 4
PARTITION_LIMIT = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id bigserial PRIMARY KEY, kind text NOT NULL, key text, payload jsonb NOT NULL,
  run_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL DEFAULT 'queued',
  attempts int NOT NULL DEFAULT 0, lease_until timestamptz);
CREATE TABLE IF NOT EXISTS steps (wf text, step text, PRIMARY KEY (wf, step));
"""

# Claims are serialised with one advisory lock so the per-key count can't race.
CLAIM = """
WITH c AS (
  SELECT id FROM jobs j
  WHERE (status = 'queued' OR (status = 'running' AND lease_until < now()))
    AND run_at <= now()
    AND (key IS NULL OR (SELECT count(*) FROM jobs r WHERE r.key = j.key AND r.status = 'running'
                         AND r.lease_until >= now()) < %(limit)s)
  ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE jobs SET status = 'running', attempts = attempts + 1,
                lease_until = now() + make_interval(secs => %(lease)s)
FROM c WHERE jobs.id = c.id RETURNING jobs.id, jobs.kind, jobs.key, jobs.payload;
"""


def enqueue(
    kind: str, payload: dict[str, object], key: str | None = None, delay: float = 0
) -> None:
    with psycopg.connect(url(DB), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO jobs (kind, key, payload, run_at) "
            "VALUES (%s, %s, %s, now() + make_interval(secs => %s))",
            (kind, key, json.dumps(payload), delay),
        )


def run_step(wf: str, name: str, hold: float) -> None:
    with psycopg.connect(url(DB), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM steps WHERE wf=%s AND step=%s", (wf, name)).fetchone():
            return  # checkpointed: skip
    effect(DB, wf, name)
    time.sleep(hold)
    with psycopg.connect(url(DB), autocommit=True) as conn:
        conn.execute("INSERT INTO steps VALUES (%s, %s) ON CONFLICT DO NOTHING", (wf, name))


def handle(kind: str, key: str | None, p: dict[str, object]) -> None:
    if kind == "post_call":
        for name, hold in post_call_steps():
            run_step(str(p["wf"]), name, hold)
    elif kind == "call_job":
        span(DB, str(p["job"]), str(key))
    elif kind == "delayed_job":
        started(DB, str(p["job"]), float(p["enqueued"]))  # type: ignore[arg-type]


def worker_loop() -> None:
    while True:
        with psycopg.connect(url(DB)) as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(6006)")
            row = conn.execute(CLAIM, {"limit": PARTITION_LIMIT, "lease": LEASE_S}).fetchone()
        if row is None:
            time.sleep(0.2)
            continue
        job_id, kind, key, payload = row
        handle(kind, key, payload)
        with psycopg.connect(url(DB), autocommit=True) as conn:
            conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (job_id,))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        with psycopg.connect(url(DB), autocommit=True) as conn:
            conn.execute(SCHEMA)
    elif cmd == "worker":
        for _ in range(8):
            threading.Thread(target=worker_loop, daemon=True).start()
        mark_ready()
        while True:
            time.sleep(1)
    elif cmd == "start-post-call":
        enqueue("post_call", {"wf": "wf1"})
    elif cmd == "enqueue-concurrency":
        for i in range(10):
            enqueue("call_job", {"job": f"A{i}"}, key="trunk-A")
        for i in range(4):
            enqueue("call_job", {"job": f"B{i}"}, key="trunk-B")
    elif cmd == "enqueue-delay":
        enqueue("delayed_job", {"job": "d1", "enqueued": time.time()}, delay=3)
