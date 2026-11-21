"""Procrastinate: a Postgres task queue. Workflows are chains of tasks.

python engine_procrastinate.py worker
python engine_procrastinate.py start-post-call | enqueue-concurrency | enqueue-delay
"""

import sys
import time
from datetime import UTC, datetime

from common import effect, mark_ready, post_call_steps, span, started, url
from procrastinate import App, PsycopgConnector, RetryStrategy

DB = "spike_proc"
app = App(connector=PsycopgConnector(conninfo=url(DB)))
STEPS = post_call_steps()


@app.task(queue="calls", retry=RetryStrategy(max_attempts=5, wait=1))
def post_call_step(wf: str, index: int) -> None:
    name, hold = STEPS[index]
    effect(DB, wf, name)
    time.sleep(hold)
    if index + 1 < len(STEPS):
        # Not atomic with the effect above: a crash between them loses the rest of the chain
        # unless the effect is idempotent and this task is retried.
        post_call_step.defer(wf=wf, index=index + 1)


@app.task(queue="calls", pass_context=True)
def call_job(context, job: str, key: str) -> None:  # type: ignore[no-untyped-def]
    span(DB, job, key)


@app.task(queue="calls")
def delayed_job(job: str, enqueued: float) -> None:
    started(DB, job, enqueued)


@app.periodic(cron="* * * * * */2")  # every 2 seconds
@app.task(queue="calls")
async def retry_stalled(timestamp: int) -> None:
    """Procrastinate does not resurrect jobs of a dead worker by itself; this is the
    documented pattern: periodically retry jobs whose worker stopped heart-beating."""
    jobs = await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=4)  # type: ignore[misc]
    for job in jobs:
        assert job.id is not None
        await app.job_manager.retry_job_by_id_async(job.id, retry_at=datetime.now(UTC))


if __name__ == "__main__":
    cmd = sys.argv[1]
    with app.open():
        if cmd == "init":
            app.schema_manager.apply_schema()
        elif cmd == "worker":
            # Heartbeat every second so a dead worker is noticed after ~4 s (default: 10 s / 30 s).
            mark_ready()  # schema is applied by "init" before the worker starts
            app.run_worker(queues=["calls"], concurrency=8, wait=True, update_heartbeat_interval=1)
        elif cmd == "start-post-call":
            post_call_step.defer(wf="wf1", index=0)
        elif cmd == "enqueue-concurrency":
            # Procrastinate's `lock` serialises jobs sharing a lock: concurrency 1 per key, not N.
            for i in range(10):
                call_job.configure(lock="trunk-A").defer(job=f"A{i}", key="trunk-A")
            for i in range(4):
                call_job.configure(lock="trunk-B").defer(job=f"B{i}", key="trunk-B")
        elif cmd == "enqueue-delay":
            delayed_job.configure(schedule_in={"seconds": 3}).defer(job="d1", enqueued=time.time())
