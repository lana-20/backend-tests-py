"""Serve an ASGI app over real HTTP on a free localhost port, for the length of a test."""

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI

from common.polling import wait_until


@contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    """Run `app` with uvicorn in a background thread and yield its base URL.

    The socket is bound here, to port 0, so the OS picks a free port and nothing else
    can grab it between "find a port" and "listen on it". That keeps parallel test
    runs from colliding.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        # Startup takes milliseconds, but it happens on another thread: wait for the flag.
        wait_until(lambda: server.started, timeout=10, interval=0.01, description="uvicorn to start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
