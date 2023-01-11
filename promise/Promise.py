from ...Online.LoopOnline import LoopOnline as Loop, Task
from asyncio import Event
from typing import TypeVar
from .base import Promise

import asyncio


if not hasattr(asyncio, 'create_task'):  # pragma: no cover
    asyncio.create_task = asyncio.ensure_future

T = TypeVar('T')

_loop: Loop =  Loop()


def get_event_loop():
    return _loop


def set_event_loop(loop):
    global _loop
    _loop = loop


class vPromise(Promise[T]):
    ''''''
    is_settled: Event
    Task = Task
    Event = Event
    __loop = _loop
