"""Poll a condition until it holds or a deadline passes.

This is the only place in the repo that sleeps, and it is used only where waiting is
inherent: a container that is still starting, or a supervisor restarting a process.
Tests never sleep to "give something time"; they wait for an observable condition.
"""

import time
from collections.abc import Callable


def wait_until[T](
    check: Callable[[], T | None],
    *,
    timeout: float,
    description: str,
    interval: float = 0.25,
    ignore: tuple[type[Exception], ...] = (),
) -> T:
    """Call `check` until it returns a truthy value, and return that value.

    Exceptions listed in `ignore` count as "not ready yet" (for example, a refused
    connection while a server boots). Any other exception fails immediately, so a real
    bug is not hidden behind a retry loop.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            result = check()
            if result:
                return result
        except ignore as error:
            last_error = error
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {timeout}s waiting for {description}"
                + (f" (last error: {last_error!r})" if last_error else "")
            )
        time.sleep(interval)
