"""Tests for the loop-aware websocket broadcast (scheduler-pool hang fix)."""

import asyncio
import threading
import time

import pytest

from api.v1.websockets import WSConnectionManager


class FakeWS:
    """Minimal websocket stand-in recording the thread its send ran on."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.payloads: list[dict] = []
        self.send_thread_id: int | None = None

    async def send_json(self, payload: dict):
        if self.fail:
            raise RuntimeError("dead connection")
        self.send_thread_id = threading.get_ident()
        self.payloads.append(payload)


def _fresh_manager() -> WSConnectionManager:
    # Reset the singleton so each test gets a clean instance.
    WSConnectionManager._instance = None
    mgr = WSConnectionManager()
    mgr._initialized = False
    mgr.__init__()
    return mgr


@pytest.mark.asyncio
async def test_broadcast_on_main_loop_sends_directly():
    mgr = _fresh_manager()
    mgr.bind_loop(asyncio.get_running_loop())
    ws = FakeWS()
    mgr.active_connections.append(ws)

    await mgr.broadcast("hi", "Success", "media")

    assert ws.payloads == [{"type": "Success", "message": "hi", "reload": "media"}]


@pytest.mark.asyncio
async def test_send_all_drops_dead_connections():
    mgr = _fresh_manager()
    mgr.bind_loop(asyncio.get_running_loop())
    good = FakeWS()
    dead = FakeWS(fail=True)
    mgr.active_connections.extend([dead, good])

    await mgr.broadcast("x")

    assert dead not in mgr.active_connections  # dropped
    assert good in mgr.active_connections
    assert good.payloads  # good one still received


def test_broadcast_from_worker_loop_does_not_block_and_dispatches_to_main():
    """The critical regression test: calling broadcast from a different loop
    must return immediately (not await a cross-loop send) and run the send on
    the bound main loop's thread."""
    mgr = _fresh_manager()

    # Start a "main" loop in its own thread and bind it.
    main_loop = asyncio.new_event_loop()
    main_thread_id = {}
    ready = threading.Event()

    def run_main():
        asyncio.set_event_loop(main_loop)
        main_thread_id["id"] = threading.get_ident()
        ready.set()
        main_loop.run_forever()

    t = threading.Thread(target=run_main, daemon=True)
    t.start()
    ready.wait(2)
    mgr.bind_loop(main_loop)

    ws = FakeWS()
    mgr.active_connections.append(ws)

    # Call broadcast from a *different* loop (this thread's own temp loop),
    # mimicking a scheduler worker job. It must return promptly.
    worker_loop = asyncio.new_event_loop()
    start = time.perf_counter()
    worker_loop.run_until_complete(mgr.broadcast("from-worker"))
    elapsed = time.perf_counter() - start
    worker_loop.close()

    assert elapsed < 1.0  # did not block on a cross-loop send

    # The send should land on the main loop's thread shortly after.
    deadline = time.perf_counter() + 2
    while not ws.payloads and time.perf_counter() < deadline:
        time.sleep(0.01)

    main_loop.call_soon_threadsafe(main_loop.stop)
    t.join(2)

    assert ws.payloads == [{"type": "Success", "message": "from-worker", "reload": "none"}]
    assert ws.send_thread_id == main_thread_id["id"]  # ran on the main loop
