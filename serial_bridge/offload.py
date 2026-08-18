"""Run blocking Hub calls off the asyncio event loop."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from anyio import to_thread


async def offload(call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Hub call off the event loop so mode/status stay responsive."""
    return await to_thread.run_sync(partial(call, *args, **kwargs))
