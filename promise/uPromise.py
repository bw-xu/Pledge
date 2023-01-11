from ...Offline.LoopOffline import LoopOffline as Loop, Task
from ...Offline.Event import Event
from typing import TypeVar
from .base import Promise

T = TypeVar('T')

_loop: Loop = Loop()


def get_event_loop():
    return _loop


def set_event_loop(loop):
    global _loop
    _loop = loop


class uPromise(Promise[T]):
    ''''''
    is_settled: Event
    Task = Task
    Event = Event
    __loop = _loop
