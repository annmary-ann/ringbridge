"""Run the same three tests against each engine and print a results table.

python run.py [dbos procrastinate custom]
"""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

import psycopg
from common import reset_db, url

ENGINES = {
    "dbos": ("engine_dbos.py", "spike_dbos"),
    "procrastinate": ("engine_procrastinate.py", "spike_proc"),
    "custom": ("engine_custom.py", "spike_custom"),
}
PY = sys.executable


def sh(script: str, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run([PY, script, *args], check=True, env={**os.environ, **(env or {})})


READY = "/tmp/worker.ready"


def spawn(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    if os.path.exists(READY):
        os.remove(READY)
    return subprocess.Popen(
        [PY, script, *args],
        env={**os.environ, "READY_FILE": READY, **(env or {})},
        stdout=subprocess.DEVNULL,
        stderr=open(f"/tmp/{script}.{args[0]}.log", "ab"),
        start_new_session=True,
    )


def kill(p: subprocess.Popen[bytes]) -> None:
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def q(db: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url(db)) as conn:
        return conn.execute(sql).fetchall()


def wait_for(pred: Callable[[], bool], timeout: float) -> float | None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return time.time() - t0
        time.sleep(0.1)
    return None


def fresh(name: str) -> tuple[str, str]:
    script, db = ENGINES[name]
    reset_db(db)
    if name in ("procrastinate", "custom"):
        sh(script, "init")
    return script, db


def test_crash(name: str) -> dict[str, object]:
    script, db = fresh(name)
    env = {"STEP2_HOLD": "3"}
    first = "start-post-call" if name == "dbos" else "worker"
    if name != "dbos":
        sh(script, "start-post-call")
    w = spawn(script, first, env=env)
    reached = wait_for(lambda: bool(q(db, "SELECT 1 FROM effects WHERE step='outbox'")), 60)
    kill(w)  # SIGKILL while step 2 holds after its side effect
    if reached is None:
        return {"completed": False, "note": "never reached step 2"}
    w = spawn(script, "worker", env={"STEP2_HOLD": "0"})
    recovered = wait_for(lambda: bool(q(db, "SELECT 1 FROM effects WHERE step='notify'")), 90)
    kill(w)
    counts = dict(q(db, "SELECT step, n FROM effects"))
    return {
        "completed": recovered is not None,
        "recovery_s": round(recovered, 1) if recovered else None,
        "runs": {s: counts.get(s, 0) for s in ("extract", "outbox", "notify")},
    }


def test_concurrency(name: str) -> dict[str, object]:
    script, db = fresh(name)
    w = spawn(script, "worker")
    wait_for(lambda: os.path.exists(READY), 60)
    sh(script, "enqueue-concurrency")
    done = wait_for(lambda: q(db, "SELECT count(*) FROM spans")[0][0] == 14, 90)
    kill(w)
    rows = q(db, "SELECT key, t0, t1 FROM spans")
    result: dict[str, object] = {"all_done": done is not None}
    for key in ("trunk-A", "trunk-B"):
        spans = [(float(a), float(b)) for k, a, b in rows if k == key]  # type: ignore[arg-type]
        events = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans])
        cur = peak = 0
        for _, d in events:
            cur += d
            peak = max(peak, cur)
        result[f"max_parallel_{key}"] = peak
    if rows:
        result["wall_s"] = round(max(float(r[2]) for r in rows) - min(float(r[1]) for r in rows), 1)  # type: ignore[arg-type]
    return result


def test_delay(name: str) -> dict[str, object]:
    script, db = fresh(name)
    w = spawn(script, "worker")
    wait_for(lambda: os.path.exists(READY), 60)
    sh(script, "enqueue-delay")
    wait_for(lambda: bool(q(db, "SELECT 1 FROM starts")), 30)
    kill(w)
    rows = q(db, "SELECT started - enqueued FROM starts")
    return {"requested_s": 3.0, "actual_s": round(float(rows[0][0]), 2) if rows else None}  # type: ignore[arg-type]


if __name__ == "__main__":
    names = sys.argv[1:] or list(ENGINES)
    results = {}
    for n in names:
        print(f"== {n}", flush=True)
        results[n] = {
            "crash": test_crash(n),
            "concurrency": test_concurrency(n),
            "delay": test_delay(n),
        }
        print(json.dumps(results[n], indent=2), flush=True)
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
