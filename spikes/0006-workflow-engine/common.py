"""Shared ledger for the workflow-engine spike (#6).

Every engine records what its jobs actually did in plain tables, so the driver can judge
all engines the same way:

- effects: how many times each workflow step's side effect ran (exactly-once check)
- spans:   start/end of concurrency-test jobs per partition key (overlap check)
- starts:  when delayed jobs actually started (delay accuracy)
"""

import os
import time

import psycopg

PG = os.environ.get("SPIKE_PG", "postgresql://ringbridge:ringbridge@postgres:5432")


def url(db: str) -> str:
    return f"{PG}/{db}"


def reset_db(db: str) -> None:
    with psycopg.connect(url("ringbridge"), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{db}"')
    with psycopg.connect(url(db), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE effects (wf text, step text, n int NOT NULL, PRIMARY KEY (wf, step))"
        )
        conn.execute("CREATE TABLE spans (job text PRIMARY KEY, key text, t0 float, t1 float)")
        conn.execute("CREATE TABLE starts (job text PRIMARY KEY, enqueued float, started float)")


def effect(db: str, wf: str, step: str) -> None:
    with psycopg.connect(url(db), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO effects VALUES (%s, %s, 1) "
            "ON CONFLICT (wf, step) DO UPDATE SET n = effects.n + 1",
            (wf, step),
        )


def span(db: str, job: str, key: str, seconds: float = 1.0) -> None:
    t0 = time.time()
    time.sleep(seconds)
    with psycopg.connect(url(db), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO spans VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (job, key, t0, time.time()),
        )


def started(db: str, job: str, enqueued: float) -> None:
    with psycopg.connect(url(db), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO starts VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (job, enqueued, time.time()),
        )


def mark_ready() -> None:
    """Workers call this once they can accept work; the driver waits for the file."""
    path = os.environ.get("READY_FILE")
    if path:
        with open(path, "w") as f:
            f.write("ready")


def post_call_steps() -> list[tuple[str, float]]:
    """The three steps of the post-call workflow and how long each holds after its effect.

    Step 2 holds for a while *after* its side effect, so a crash there is the worst case:
    the effect happened but the engine never recorded the step as finished.
    """
    return [("extract", 0.0), ("outbox", float(os.environ.get("STEP2_HOLD", "0"))), ("notify", 0.0)]
