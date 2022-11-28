from ...Offline.LoopOffline import LoopOffline as Loop
from functools import partial, wraps
import inspect
from .FutureSim import Future

_loop: Loop = Loop()

def get_event_loop():
    return _loop

def set_event_loop(loop):
    global _loop
    _loop = loop

class AggregateError(RuntimeError):
    """An exception that holds a list of errors.

    This exception is raised by :func:`Pledge.any` when all of the input
    promises are rejected.

    :param errors: the list of erros.
    """
    def __init__(self, errors):
        self.errors = errors


class Pledge:
    ''''''

    def __init__(self, func=None, *args, loop=None):
        self.func = func
        self.args = args
        self._loop = loop if loop is not None else _loop
        self.future = Future(loop=self._loop)

    def go(self):
        self.func(*self.args)

    def finish(self, success, error):
        ''''''
        if error is not None:
            if not isinstance(error, BaseException):
                error = Exception(error)
            self._reject(error)
        else:
            self._resolve(success)




    def then(self, on_resolved=None, on_rejected=None):
        """Appends fulfillment and rejection handlers to the promise.

        :param on_resolved: an optional fulfillment handler.
        :param on_rejected: an optional rejection handler.

        Returns a new promise that resolves to the return value of the called
        handler, or to the original settled value if a handler was not
        provided.
        """
        pledge = Pledge()
        self.future.add_done_callback(
            partial(self._handle_done, on_resolved, on_rejected, pledge)
        )
        return pledge

    def catch(self, on_rejected):
        """Appends a rejection handler callback to the promise.
        :param on_rejected: the rejection handler.
        Returns a new promise that resolves to the return value of the
        handler.
        """
        return self.then(None, on_rejected)

    def finally_(self, on_settled):
        """Appends a fulfillment and reject handler to the promise.
        :param on_settled: the handler.
        The handler is invoked when the promise is fulfilled or rejected.
        Returns a new promise that resolves when the original promise settles.
        """
        def _finally(result):
            return on_settled()

        return self.then(_finally, _finally)
    

    def cancel(self):
        """Cancels a promise, if possible.
        A promise that is cancelled rejects with a ``asyncio.CancelledError``.
        """
        return self.future.cancel()

    def cancelled(self):
        """Checks if a promise has been cancelled."""
        return self.future.cancelled()
    
    @staticmethod
    def resolve(value):
        """Returns a new Pledge object that resolves to the given value.

        :param value: the value the promise will resolve to.

        If the value is another ``Pledge`` instance, the new promise will
        resolve or reject when this promise does. If the value is an asyncio
        ``Task`` object, the new promise will be associated with the task and
        will pass cancellation requests to it if its :func:`Pledge.cancel`
        method is invoked. Any other value creates a promise that immediately
        resolves to the value.
        """
        pledge = None
        if isinstance(value, Pledge):
            pledge = Pledge()
            value.then(
                lambda res: pledge._resolve(res),
                lambda err: pledge._reject(err)
            )
        # elif isinstance(value, asyncio.Task):
        #     pledge = TaskPledge(value)
        #     value.add_done_callback(
        #         partial(Pledge._handle_done, None, None, pledge))
        else:
            pledge = Pledge()
            pledge._resolve(value)
        return pledge

    @staticmethod
    def reject(reason):
        """Returns a new promise object that is rejected with the given reason.

        :param reason: the rejection reason. Must be an ``Exception`` instance.
        """
        promise = Pledge()
        promise._reject(reason)
        return promise
    
    @staticmethod
    def all(promises):
        """Wait for all promises to be resolved, or for any to be rejected.
        :param promises: a list of promises to wait for.
        Returns a promise that resolves to a aggregating list of all the values
        from the resolved input promises, in the same order as given. If one or
        more of the input promises are rejected, the returned promise is
        rejected with the reason of the first rejected promise.
        """
        new_promise = Pledge()
        results = []
        total = len(promises)
        resolved = 0

        def _resolve(index, result):
            nonlocal results, resolved

            if len(results) < index + 1:
                results += [None] * (index + 1 - len(results))
            results[index] = result
            resolved += 1
            if resolved == total:
                new_promise._resolve(results)

        index = 0
        for promise in promises:
            Pledge.resolve(promise).then(partial(_resolve, index),
                                          new_promise._reject)
            index += 1

        if total == resolved:
            new_promise._resolve(results)
        return new_promise

    @staticmethod
    def all_settled(promises):
        """Wait until all promises are resolved or rejected.
        :param promises: a list of promises to wait for.
        Returns a promise that resolves to a list of dicts, where each dict
        describes the outcome of each promise. For a promise that was
        fulfilled, the dict has this format::
            {'status': 'fulfilled', 'value': <resolved-value>}
        For a promise that was rejected, the dict has this format::
            {'status': 'rejected', 'reason': <rejected-reason>}
        """
        return Pledge.all([promise.then(
            lambda value: {'status': 'fulfilled', 'value': value}).catch(
                lambda reason: {'status': 'rejected', 'reason': reason})
            for promise in promises])
    

    @staticmethod
    def any(promises):
        """Wait until any of the promises given resolves.
        :oaram promises: a list of promises to wait for.
        Returns a promise that resolves with the value of the first input
        promise. Pledge rejections are ignored, except when all the input
        promises are rejected, in which case the returned promise rejects with
        an :class:`AggregateError`.
        """
        new_promise = Pledge()
        errors = []
        total = len(promises)
        rejected = 0

        def _reject(index, error):
            nonlocal errors, rejected

            if len(errors) < index + 1:
                errors += [None] * (index + 1 - len(errors))
            errors[index] = error
            rejected += 1
            if rejected == total:
                new_promise._reject(AggregateError(errors))

        index = 0
        for promise in promises:
            Pledge.resolve(promise).then(new_promise._resolve,
                                          partial(_reject, index))
            index += 1

        if total == rejected:
            new_promise._reject(AggregateError(errors))
        return new_promise

    @staticmethod
    def race(promises):
        """Wait until any of the promises is fulfilled or rejected.
        :param promises: a list of promises to wait for.
        Returns a promise that resolves or rejects with the first input
        promise that settles.
        """
        new_promise = Pledge()
        settled = False

        def _resolve(result):
            nonlocal settled

            if not settled:
                settled = True
                new_promise._resolve(result)

        def _reject(error):
            nonlocal settled

            if not settled:
                settled = True
                new_promise._reject(error)

        for promise in promises:
            Pledge.resolve(promise).then(_resolve, _reject)
        return new_promise
    


    def _resolve(self, result):
        self.future.set_result(result)


    def _reject(self, error):
        self.future.set_exception(error)

    

    @staticmethod
    def _handle_done(on_resolved, on_rejected, pledge, future: Future):
        try:
            result = future.result()
            Pledge._handle_callback(result, on_resolved, pledge)
        except BaseException as error:
            Pledge._handle_callback(error, on_rejected, pledge, resolve=False)

    @staticmethod
    def _handle_callback(result, callback, pledge: 'Pledge', resolve=True):
        if callable(callback):
            try:
                callback_result = callback(result)
                if isinstance(callback_result, Pledge):
                    callback_result.then(
                        lambda res: pledge._resolve(res),
                        lambda err: pledge._reject(err)
                    )
                else:
                    pledge._resolve(callback_result)
            except BaseException as error:
                pledge._reject(error)
        elif resolve:
            pledge._resolve(result)
        else:
            pledge._reject(result)

    def __await__(self):
        def _reject(error):
            raise error

        return self.catch(_reject).future.__await__()


# class TaskPledge(Pledge):
#     def __init__(self, task):
#         super().__init__()
#         self.task: Task = task

#     def cancel(self):
#         # cancel the task associated with this future
#         # (the future will receive the cancellation error)
#         return self.task.cancel()

#     def cancelled(self):
#         return self.task.cancelled()

    
    


# def pledgify(func):
#     @wraps(func)
#     def wrapper(*args, **kwargs):
#         try:
#             result = func(*args, **kwargs)
#         except BaseException as error:
#             return Pledge.reject(error)
#         if inspect.iscoroutine(result):
#             result = _loop.async_call(result)
#         return Pledge.resolve(result)

#     return wrapper