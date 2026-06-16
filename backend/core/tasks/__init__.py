import os

from quiv import Quiv, Event, Task, Job
from sqlalchemy import event as _sa_event

from app_logger import ModuleLogger
from api.v1.websockets import ws_manager

# Get the timezone from the environment variable
timezone = os.getenv("TZ", "UTC")

# # Get a logger
tasks_logger = ModuleLogger("Tasks")

# Create a scheduler instance
scheduler = Quiv(timezone=timezone, logger=tasks_logger)


# Trailarr enables `PRAGMA foreign_keys=ON` for *every* SQLite connection via a
# global Engine connect listener (core/base/database/utils/engine.py). That also
# hits Quiv's own engine, where it breaks run-once task cleanup: when a run-once
# task (every trailer/clip download is one) finishes, Quiv deletes its quiv_task
# row while quiv_job history rows still reference it — which raises a FOREIGN KEY
# constraint error with enforcement on. That exception propagates out of Quiv's
# job runner *before* it decrements the active-job counter, so after `pool_size`
# (default 10) run-once tasks the counter is pinned at max and the scheduler
# silently stops dispatching ALL tasks until the container is restarted.
#
# Quiv's schema/cleanup assume SQLite's default of FK enforcement OFF, so turn it
# back off for Quiv's engine only — Trailarr's own databases keep FK ON. The
# instance listener runs after the global one, so the net per-connection state
# for Quiv connections is OFF. dispose() drops any connections opened before the
# listener was attached so the override applies to the whole pool.
try:
    _quiv_engine = scheduler.persistence._engine

    @_sa_event.listens_for(_quiv_engine, "connect")
    def _quiv_disable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    _quiv_engine.dispose()
except Exception as e:  # pragma: no cover - defensive against Quiv internals
    tasks_logger.warning(
        "Could not disable FK enforcement on the Quiv engine; the scheduler"
        f" may wedge after {getattr(scheduler, '_pool_size', '?')} downloads:"
        f" {e}"
    )


# Add event listeners to the scheduler
async def on_job_started_event(event: Event, task: Task, job: Job) -> None:
    await ws_manager.broadcast(
        f"'{task.task_name}' Task Started",
        type="Info",
        reload="media,tasks",
    )


async def on_job_completed_event(event: Event, task: Task, job: Job) -> None:
    await ws_manager.broadcast(
        f"'{task.task_name}' Task Completed",
        type="Success",
        reload="media,tasks",
    )


async def on_job_failed_event(event: Event, task: Task, job: Job) -> None:
    await ws_manager.broadcast(
        f"'{task.task_name}' Task Failed",
        type="Error",
        reload="media,tasks",
    )


scheduler.add_listener(Event.JOB_STARTED, on_job_started_event)
scheduler.add_listener(Event.JOB_COMPLETED, on_job_completed_event)
scheduler.add_listener(Event.JOB_FAILED, on_job_failed_event)
