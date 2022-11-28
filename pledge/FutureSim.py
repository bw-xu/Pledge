"""A Future class similar to the one in PEP 3148."""

import logging
import sys
import reprlib
from . import exceptions
from enum import Enum
from AscellaQRIS.Scheduler.Offline.LoopOffline import LoopOffline as Loop

class _Status(Enum):
    _PENDING = 'Pending'
    _CANCELLED = 'Cancelled'
    _FINISHED = 'Finished'

_PENDING = _Status._PENDING
_CANCELLED = _Status._CANCELLED
_FINISHED = _Status._FINISHED

_loop: Loop = Loop()

def get_event_loop():
    return _loop

def set_event_loop(loop):
    global _loop
    _loop = loop




class Future:
    """This class is *almost* compatible with concurrent.futures.Future.

    Differences:

    - This class is not thread-safe.

    - result() and exception() do not take a timeout argument and
      raise an exception when the future isn't done yet.

    - Callbacks registered with add_done_callback() are always called
      via the event loop's call_soon().

    - This class is not compatible with the wait() and as_completed()
      methods in the concurrent.futures package.

    (In Python 3.4 or later we may be able to unify the implementations.)
    """

    # Class variables serving as defaults for instance variables.
    _state = _PENDING
    _result = None
    _exception: Exception = None
    _loop = None
    _cancel_message = None
    # A saved CancelledError for later chaining as an exception context.
    _cancelled_exc = None

    # This field is used for a dual purpose:
    # - Its presence is a marker to declare that a class implements
    #   the Future protocol (i.e. is intended to be duck-type compatible).
    #   The value must also be not-None, to enable a subclass to declare
    #   that it is not compatible by setting this to None.
    # - It is set by __iter__() below so that Task._step() can tell
    #   the difference between
    #   `await Future()` or`yield from Future()` (correct) vs.
    #   `yield Future()` (incorrect).
    _asyncio_future_blocking = False

    __log_traceback = False

    def __init__(self, *, loop=None):
        """Initialize the future.

        The optional event_loop argument allows explicitly setting the event
        loop object used by the future. If it's not provided, the future uses
        the default event loop.
        """
        if loop is None:
            self._loop = get_event_loop()
        else:
            self._loop = loop
        self._callbacks = []

    def __repr__(self):
        info = [self._state.value.lower()]
        if self._state == _FINISHED:
            if self._exception is not None:
                info.append(f'exception={self._exception!r}')
            else:
                # use reprlib to limit the length of the output, especially
                # for very long strings
                result = reprlib.repr(self._result)
                info.append(f'result={result}')
        if self._callbacks:
            info.append(str(self._callbacks))
        info = ' '.join(info)
        return f'<{self.__class__.__name__} {info}>'


    # def __del__(self):
    #     if not self.__log_traceback:
    #         # set_exception() was not called, or result() or exception()
    #         # has consumed the exception
    #         return
    #     exc = self._exception
    #     context = {
    #         'message':
    #             f'{self.__class__.__name__} exception was never retrieved',
    #         'exception': exc,
    #         'future': self,
    #     }
    #     if self._source_traceback:
    #         context['source_traceback'] = self._source_traceback
    #     self._loop.call_exception_handler(context)


    @property
    def _log_traceback(self):
        return self.__log_traceback

    @_log_traceback.setter
    def _log_traceback(self, val):
        if val:
            raise ValueError('_log_traceback can only be set to False')
        self.__log_traceback = False

    def get_loop(self):
        """Return the event loop the Future is bound to."""
        loop = self._loop
        if loop is None:
            raise RuntimeError("Future object is not initialized.")
        return loop

    def _make_cancelled_error(self):
        """Create the CancelledError to raise if the Future is cancelled.

        This should only be called once when handling a cancellation since
        it erases the saved context exception value.
        """
        if self._cancelled_exc is not None:
            exc = self._cancelled_exc
            self._cancelled_exc = None
            return exc

        if self._cancel_message is None:
            exc = exceptions.CancelledError()
        else:
            exc = exceptions.CancelledError(self._cancel_message)
        exc.__context__ = self._cancelled_exc
        # Remove the reference since we don't need this anymore.
        self._cancelled_exc = None
        return exc

    def cancel(self, msg=None):
        """Cancel the future and schedule callbacks.

        If the future is already done or cancelled, return False.  Otherwise,
        change the future's state to cancelled, schedule the callbacks and
        return True.
        """
        self.__log_traceback = False
        if self._state != _PENDING:
            return False
        self._state = _CANCELLED
        self._cancel_message = msg
        self.__schedule_callbacks()
        return True

    def __schedule_callbacks(self):
        """Internal: Ask the event loop to call all callbacks.

        The callbacks are scheduled to be called as soon as possible. Also
        clears the callback list.
        """
        callbacks = self._callbacks[:]
        if not callbacks:
            return

        self._callbacks[:] = []
        for callback in callbacks:
            self._loop.call(callback, self)

    def cancelled(self):
        """Return True if the future was cancelled."""
        return self._state == _CANCELLED

    # Don't implement running(); see http://bugs.python.org/issue18699

    def done(self) -> bool:
        """Return True if the future is done.

        Done means either that a result / exception are available, or that the
        future was cancelled.
        """
        return self._state != _PENDING

    def result(self):
        """Return the result this future represents.

        If the future has been cancelled, raises CancelledError.  If the
        future's result isn't yet available, raises InvalidStateError.  If
        the future is done and has an exception set, this exception is raised.
        """
        if self._state == _CANCELLED:
            exc = self._make_cancelled_error()
            raise exc
        if self._state != _FINISHED:
            raise exceptions.InvalidStateError('Result is not ready.')
        self.__log_traceback = False
        if self._exception is not None:
            raise self._exception.with_traceback(self._exception_tb)
        return self._result

    def exception(self):
        """Return the exception that was set on this future.

        The exception (or None if no exception was set) is returned only if
        the future is done.  If the future has been cancelled, raises
        CancelledError.  If the future isn't done yet, raises
        InvalidStateError.
        """
        if self._state == _CANCELLED:
            exc = self._make_cancelled_error()
            raise exc
        if self._state != _FINISHED:
            raise exceptions.InvalidStateError('Exception is not set.')
        self.__log_traceback = False
        return self._exception

    def add_done_callback(self, fn, ):
        """Add a callback to be run when the future becomes done.

        The callback is called with a single argument - the future object. If
        the future is already done when this is called, the callback is
        scheduled with call_soon.
        """
        if self._state != _PENDING:
            self._loop.call(fn, self)
        else:
            self._callbacks.append(fn)

    # New method not in PEP 3148.

    def remove_done_callback(self, fn):
        """Remove all instances of a callback from the "call when done" list.

        Returns the number of callbacks removed.
        """
        filtered_callbacks = [f
                              for f in self._callbacks
                              if f != fn]
        removed_count = len(self._callbacks) - len(filtered_callbacks)
        if removed_count:
            self._callbacks[:] = filtered_callbacks
        return removed_count

    # So-called internal methods (note: no set_running_or_notify_cancel()).

    def set_result(self, result):
        """Mark the future done and set its result.

        If the future is already done when this method is called, raises
        InvalidStateError.
        """
        if self._state != _PENDING:
            raise exceptions.InvalidStateError(f'{self._state}: {self!r}')
        self._result = result
        self._state = _FINISHED
        self.__schedule_callbacks()

    def set_exception(self, exception):
        """Mark the future done and set an exception.

        If the future is already done when this method is called, raises
        InvalidStateError.
        """
        if self._state != _PENDING:
            raise exceptions.InvalidStateError(f'{self._state}: {self!r}')
        if isinstance(exception, type):
            exception = exception()
        if type(exception) is StopIteration:
            raise TypeError("StopIteration interacts badly with generators "
                            "and cannot be raised into a Future")
        self._exception = exception
        self._exception_tb = exception.__traceback__
        self._state = _FINISHED
        self.__schedule_callbacks()
        self.__log_traceback = True

    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self  # This tells Task to wait for completion.
        if not self.done():
            raise RuntimeError("await wasn't used with future")
        return self.result()  # May raise too.

    __iter__ = __await__  # make compatible with 'yield from'.








