from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def _run_in_browser_loop(async_fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    if sys.platform == "win32" and hasattr(asyncio, "ProactorEventLoop"):
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_fn(*args, **kwargs))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        loop.close()


def _needs_browser_worker_loop() -> bool:
    if sys.platform != "win32":
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return "SelectorEventLoop" in type(loop).__name__


async def run_with_browser_loop(
    async_fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
) -> T:
    if _needs_browser_worker_loop():
        return await asyncio.to_thread(_run_in_browser_loop, async_fn, *args, **kwargs)
    try:
        return await async_fn(*args, **kwargs)
    except NotImplementedError:
        if sys.platform != "win32":
            raise
        return await asyncio.to_thread(_run_in_browser_loop, async_fn, *args, **kwargs)
