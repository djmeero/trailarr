import asyncio
from fastapi import WebSocket


class WSConnectionManager:
    """Connection manager for websockets to keep track of active connections \n
    ***Singleton Class***
    """

    _instance = None

    def __new__(cls) -> "WSConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Guard against re-initialising the singleton on repeated construction.
        if getattr(self, "_initialized", False):
            return
        self.active_connections: list[WebSocket] = []
        # The main (uvicorn) event loop that owns the websocket transports.
        # Bound once at app startup via bind_loop(). Broadcasts originating from
        # other loops/threads (e.g. scheduler worker jobs) are handed to this
        # loop instead of awaiting a cross-loop send, which would hang the
        # caller's thread.
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._initialized = True

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the main event loop that owns the websocket connections."""
        self._main_loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def _send_all(self, payload: dict) -> None:
        """Send a payload to every active connection on the main loop.

        Iterates over a copy so connections can be removed while sending, and
        drops any connection whose send fails so one dead client can't wedge
        the broadcast.
        """
        for connection in list(self.active_connections):
            try:
                await connection.send_json(payload)
            except Exception:
                self.disconnect(connection)

    async def broadcast(
        self, message: str, type: str = "Success", reload: str = "none"
    ) -> None:
        """Send a message to all connected clients.

        Safe to call from any thread or event loop. When invoked off the main
        loop (e.g. from a scheduler worker job running in its own temporary
        loop), the send is scheduled onto the main loop and this returns
        immediately — it never awaits a cross-loop websocket send, which would
        block the worker thread forever and exhaust the scheduler thread pool.

        Args:
            message (str): The message to send.
            type (str, optional=success): The type of message.
            reload (str, optional=none): The reload instruction.
        Returns:
            None
        """
        payload = {"type": type, "message": message, "reload": reload}
        main_loop = self._main_loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if (
            main_loop is not None
            and not main_loop.is_closed()
            and running is not main_loop
        ):
            # Off the main loop — hand the send over and don't block the caller.
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_all(payload), main_loop
                )
            except Exception:
                pass
            return

        # On the main loop (e.g. API request handlers) — send directly.
        await self._send_all(payload)


def broadcast(
    message: str, type: str = "Success", reload: str = "none"
) -> None:
    """Send a message to all connected clients. Non-Async function.
    Args:
        message (str): The message to send.
        type (str, optional=success): The type of message.
        reload (str, optional=none): The reload instruction.
    Returns:
        None
    """

    def send_message() -> None:
        """Run the async task in a separate event loop."""
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(
            ws_manager.broadcast(message, type, reload)
        )
        new_loop.close()
        return

    send_message()
    return


ws_manager = WSConnectionManager()
