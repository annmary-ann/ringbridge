"""DBOS Transact: durable workflows and steps checkpointed in Postgres.

python engine_dbos.py worker            # process queues, recover pending workflows
python engine_dbos.py start-post-call   # launch, start the post-call workflow, keep working
python engine_dbos.py enqueue-concurrency | enqueue-delay
"""

import sys
import time

from common import effect, mark_ready, post_call_steps, span, started, url
from dbos import DBOS, DBOSClient, DBOSConfig, EnqueueOptions

DB = "spike_dbos"
config: DBOSConfig = {"name": "spike", "system_database_url": url(DB), "executor_id": "local"}
DBOS(config=config)


def register_queues() -> None:
    # DBOS 3.x: queues are declared through DBOS and persisted in the system database.
    DBOS.register_queue("calls", partition_concurrency=2, polling_interval_sec=0.2)
    DBOS.register_queue("timers", polling_interval_sec=0.2)


@DBOS.step()
def step(wf: str, name: str, hold: float) -> None:
    effect(DB, wf, name)
    time.sleep(hold)


@DBOS.workflow()
def post_call(wf: str) -> None:
    for name, hold in post_call_steps():
        step(wf, name, hold)


@DBOS.workflow()
def call_job(job: str, key: str) -> None:
    span(DB, job, key)


@DBOS.workflow()
def delayed_job(job: str, enqueued: float) -> None:
    started(DB, job, enqueued)


def client_enqueue(workflow: str, queue: str, *args: object, **opts: object) -> None:
    client = DBOSClient(system_database_url=url(DB))
    options: EnqueueOptions = {"workflow_name": workflow, "queue_name": queue, **opts}  # type: ignore[typeddict-item]
    client.enqueue(options, *args)
    client.destroy()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd in ("worker", "start-post-call"):
        DBOS.launch()
        register_queues()
        mark_ready()
        if cmd == "start-post-call":
            DBOS.start_workflow(post_call, "wf1")
        while True:
            time.sleep(1)
    elif cmd == "enqueue-concurrency":
        for i in range(10):
            client_enqueue("call_job", "calls", f"A{i}", "trunk-A", queue_partition_key="trunk-A")
        for i in range(4):
            client_enqueue("call_job", "calls", f"B{i}", "trunk-B", queue_partition_key="trunk-B")
    elif cmd == "enqueue-delay":
        client_enqueue("delayed_job", "timers", "d1", time.time(), delay_seconds=3.0)
