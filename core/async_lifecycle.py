"""Small structured-concurrency helpers for request-owned asyncio tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any


def _collect_tasks(
    task_groups: tuple[
        asyncio.Task[Any] | Iterable[asyncio.Task[Any]] | None,
        ...,
    ],
) -> list[asyncio.Task[Any]]:
    tasks: list[asyncio.Task[Any]] = []
    for task_group in task_groups:
        if task_group is None:
            continue
        if isinstance(task_group, asyncio.Task):
            tasks.append(task_group)
        else:
            tasks.extend(task_group)
    return tasks


async def _cancel_and_gather(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _shield_drain_from_repeated_cancellation(
    drain_task: asyncio.Task[None],
) -> asyncio.CancelledError | None:
    interrupted: asyncio.CancelledError | None = None
    while not drain_task.done():
        try:
            await asyncio.shield(drain_task)
        except asyncio.CancelledError as exc:
            interrupted = interrupted or exc
    return interrupted


async def cancel_and_drain_tasks(
    *task_groups: asyncio.Task[Any] | Iterable[asyncio.Task[Any]] | None,
) -> None:
    """Cancel and retrieve every supplied task despite repeated parent cancellation."""
    tasks = _collect_tasks(task_groups)
    if not tasks:
        return

    # A shield alone is insufficient: a second ``Task.cancel()`` still interrupts
    # the caller awaiting the shield. Keep ownership until the drain itself has
    # completed, then restore cancellation so request shutdown semantics remain
    # observable to the caller.
    drain_task = asyncio.create_task(_cancel_and_gather(tasks))
    interrupted = await _shield_drain_from_repeated_cancellation(drain_task)
    drain_task.result()
    if interrupted is not None:
        raise interrupted
