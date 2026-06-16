"""Regression tests for the scheduler-wedge bug (issue: pool counter leak).

Trailarr's global `PRAGMA foreign_keys=ON` listener was applied to Quiv's
engine too, which made Quiv's run-once task deletion raise a FOREIGN KEY
error. That exception skipped the active-job-count decrement, so after
`pool_size` run-once tasks the scheduler stopped dispatching anything.
"""

import time


def test_quiv_engine_has_foreign_keys_disabled():
    """core.tasks must turn FK enforcement OFF on Quiv's engine, otherwise
    run-once task cleanup hits a FOREIGN KEY constraint and leaks the pool."""
    from core.tasks import scheduler

    engine = scheduler.persistence._engine
    with engine.connect() as conn:
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert fk == 0, "FK enforcement must be OFF for the Quiv engine"


def test_run_once_tasks_past_pool_size_do_not_wedge(tmp_path):
    """Run more run-once tasks than the pool size and confirm the active-job
    counter returns to 0 (i.e. the scheduler keeps dispatching)."""
    from quiv import Quiv
    from sqlalchemy import event

    # Fresh scheduler with a tiny pool so the test is quick and decisive.
    sched = Quiv(timezone="UTC", pool_size=3)

    # Apply the same fix core/tasks applies (the global FK=ON listener from
    # engine.py is already registered process-wide by importing the app).
    engine = sched.persistence._engine

    @event.listens_for(engine, "connect")
    def _fk_off(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.close()

    engine.dispose()

    done = {"n": 0}

    def handler(i, *, _job_id=None, _stop_event=None):
        done["n"] += 1

    sched.start()
    try:
        n = 10  # > pool_size (3)
        for i in range(n):
            sched.add_task(
                task_name=f"job-{i}",
                func=handler,
                interval=86400.0,
                delay=1,
                run_once=True,
                args=(i,),
            )
            time.sleep(0.15)
        # Wait for all to drain
        deadline = time.time() + 20
        while done["n"] < n and time.time() < deadline:
            time.sleep(0.2)
        assert done["n"] == n, f"only {done['n']}/{n} ran — scheduler wedged"
        assert sched._active_job_count == 0
    finally:
        sched.shutdown()
