from functools import partial
import inspect
from copy import copy
from typing import TypeVar, Awaitable, Type, List, Iterable, Any, Tuple, Callable

from ...Offline.Event import Event as uEvent
from ...Online.LoopOnline import LoopOnline as vLoop, Task as vTask, Event as vEvent
from ...Offline.LoopOffline import LoopOffline as uLoop, Task as uTask
from .state import State


class AggregateError(RuntimeError):
    """An exception that holds a list of errors.

    This exception is raised by :func:`Promise.any` when all of the input
    promises are rejected.

    :param errors: the list of erros.
    """

    def __init__(self, errors):
        self.errors = errors


T = TypeVar('T')


class Promise(Awaitable[Tuple[T, Exception]]):
    ''''''
    Task: 'Type[vTask]|Type[uTask]' = None
    Event: 'Type[vEvent]|Type[uEvent]' = None
    loop__: 'vLoop|uLoop' = None

    def __init__(self, func: Callable[[Any], T] = None, task: Task = None, loop: 'uLoop|vLoop' = None, data: T = None):

        self.data = data

        self._state = State.PENDING

        self._func = func
        self._task = task
        self._on_fulfillment: List[Promise[T]] = []
        self._on_rejection: List[Promise[T]] = []

        self._result = None
        self._error = None

        self.is_handling = False
        self.is_settled = None

        self._loop: 'vLoop|uLoop' = loop if loop is not None else self.loop__
        pass

    def set_result(self, result: T):
        if result is not None:
            self._state = State.FULLFILLED
        self._result: T = result
        self._loop = None
        if self.is_settled is not None:
            self.is_settled.set()

    def set_error(self, error):
        if error is not None:
            self._state = State.REJECTED
        self._error: 'Exception|None' = error
        self._loop = None
        if self.is_settled is not None:
            self.is_settled.set()

    async def _async_execute(self, *args, **kwargs) -> Tuple[T, 'None|Exception']:
        ''''''
        self.is_handling = True
        try:
            success = await self._func(*args, **kwargs)
            self.is_handling = False
            if not isinstance(success, tuple):
                success = (success, )
            self._fulfill(*success)
        except Exception as error:
            self.is_handling = False
            self._reject(error)
        finally:
            self.is_handling = False
            if self.is_settled is not None:
                self.is_settled.set()
        return self._result, self._error

    def _execute(self, *args, **kwargs) -> Tuple[T, 'None|Exception']:
        '''
        执行self._func
        '''
        self.is_handling = True
        try:
            success = self._func(*args, **kwargs)
            self.is_handling = False
            if not isinstance(success, tuple):
                success = (success, )
            self.set_result(success)
            self._fulfill(*success)
        except Exception as error:
            self.is_handling = False
            self.set_error(error)
            self._reject(error)
        finally:
            self.is_handling = False
            if self.is_settled is not None:
                self.is_settled.set()
        return self._result, self._error

    def _fulfill(self, *ret):
        self._state = State.FULLFILLED
        self.set_result(ret)
        _on_fulfillment = copy(self._on_fulfillment)
        self._on_fulfillment.clear()
        for promise in _on_fulfillment:
            promise.apply(*ret)

    def _reject(self, error):
        self._state = State.REJECTED
        self.set_error(error)
        _on_rejection = copy(self._on_rejection)
        self._on_rejection.clear()
        for promise in _on_rejection:
            promise.apply(error)

    def apply(self, *args, **kwargs):
        if self._result is not None:
            self._fulfill(*self._result)
        elif self._error is not None:
            self._reject(self._error)
        elif self._func is not None:
            if inspect.iscoroutinefunction(self._func):
                self._loop.async_call(self._async_execute, *args, **kwargs)
            elif callable(self._func):
                self._execute(*args, **kwargs)

    @classmethod
    def _then(cls, self: 'Promise[T]', on_fulfillment=None, on_rejection=None) -> 'Promise[T]':
        """
        """
        if on_rejection is not None:
            if not isinstance(on_rejection, cls):
                promise = cls(on_rejection, loop=self._loop)
            else:
                promise = on_rejection
            self._on_rejection.append(promise)
            if self._state.rejected:
                self._reject(self._error)
        if on_fulfillment is not None:
            if not isinstance(on_fulfillment, cls):
                promise = cls(on_fulfillment, loop=self._loop)
            else:
                promise = on_fulfillment
            self._on_fulfillment.append(promise)
            if self._state.fullfilled:
                self._fulfill(*self._result)

        return promise

    def then(self, on_fulfillment=None, on_rejection=None) -> 'Promise[T]':
        return self._then(self, on_fulfillment, on_rejection)

    def catch(self, on_rejected):
        return self.then(None, on_rejected)

    def finally_(self, on_settled):
        def _finally(result):
            return on_settled()

        return self.then(_finally, _finally)

    def cancel(self):
        ''''''
        if self._task is not None:
            self._task.cancel()
        self._reject(Exception('Cancelled'))

    def cancelled(self):
        ''''''
        if self._task is not None:
            return self._task.cancelled()
        else:
            return self._state is State.REJECTED

    @classmethod
    def resolve(cls, value, loop: 'vLoop|uLoop' = loop__) -> 'Promise[T]':
        ''''''
        promise = None
        if isinstance(value, cls):
            promise = cls(loop=loop)
            value.then(
                lambda *res: promise._fulfill(*res),
                lambda err: promise._reject(err)
            )
        elif isinstance(value, cls.Task):
            promise = cls(task=value, loop=loop)
            value.add_done_callback(
                partial(promise._fulfill, None))
        else:
            promise = cls(loop=loop)
            promise._fulfill(value)
        return promise

    @classmethod
    def reject(cls, reason, loop: 'vLoop|uLoop' = loop__) -> 'Promise[T]':
        ''''''
        promise = cls(loop=loop)
        promise._reject(reason)
        return promise

    @classmethod
    def all(cls, promises, loop: 'vLoop|uLoop' = loop__) -> 'Promise[T]':
        ''''''
        promise = cls(loop=loop)
        total = len(promises)
        cnt_fulfilled = 0
        cnt_reject = False

        def _resolve(index, result):
            nonlocal cnt_fulfilled
            if promise._result is None:
                promise._result = [None for _ in range(len(promises))]
            promise._result[index] = result
            cnt_fulfilled += 1
            if cnt_fulfilled >= total:
                promise._fulfill(promise._result)

        def _reject(reason):
            nonlocal cnt_reject
            if cnt_reject == 0:
                if promise._result is None:
                    promise._result = [None for _ in range(len(promises))]
                promise._reject(reason)
            cnt_reject += 1

        index = 0
        for p in promises:
            prm = cls.resolve(p, loop=loop)
            prm.then(partial(_resolve, index), promise.set_error)
            prm.catch(_reject)
            index += 1

        if total == cnt_fulfilled:
            promise._fulfill(promise._result)
        return promise

    @classmethod
    def all_settled(cls, promises: Iterable['Promise[T]'], loop: 'vLoop|uLoop' = loop__):
        ''''''
        return cls.all([promise.then(
            lambda value: {'status': State.FULLFILLED, 'value': value}).catch(
                lambda reason: {'status': State.REJECTED, 'reason': reason})
            for promise in promises], loop=loop)

    @classmethod
    def any(cls, promises, loop: 'vLoop|uLoop' = loop__) -> 'Promise[T]':
        ''''''
        promise = cls(loop=loop)
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
                promise._reject(AggregateError(errors))

        index = 0
        for promise in promises:
            cls.resolve(promise, loop=loop).then(
                promise._fulfill, partial(_reject, index))
            index += 1

        if total == rejected:
            promise._reject(AggregateError(errors))
        return promise

    @classmethod
    def race(cls, promises, loop: 'vLoop|uLoop' = loop__) -> 'Promise[T]':
        ''''''
        promise = cls(loop=loop)
        settled = False

        def _resolve(result):
            nonlocal settled
            if not settled:
                settled = True
                promise._fulfill(result)

        def _reject(error):
            nonlocal settled
            if not settled:
                settled = True
                promise._reject(error)

        for promise in promises:
            cls.resolve(promise, loop=loop).then(_resolve, _reject)
        return promise

    def __call__(self, *args, **kwargs) -> 'Promise[T]':
        self.apply(*args, **kwargs)
        return self

    def __await__(self):
        ''''''
        if self._result is not None:
            return self._result, self._error
        if self.is_settled is None:
            self.is_settled = self.Event(loop=self._loop.loop)

        yield from self.is_settled.wait().__await__()
        result: T
        result = self._result[0] if self._result is not None and len(
            self._result) == 1 else self._result
        return result, self._error

    def visualize(self):
        '''
        Pending: Blue, Fullfiled: Green, Rejected: Red
        fulfill: full line, reject: dashed line
        '''
        import networkx as nx
        import matplotlib.pyplot as plt

        G = nx.DiGraph()
        node_id = 0
        colors = {
            State.PENDING: 'blue',
            State.FULLFILLED: 'green',
            State.REJECTED: 'red',
        }

        def add(_G: nx.DiGraph, promise: Promise, nid, add_self=True, layer=0):
            nonlocal node_id
            if add_self:
                name = promise._func.__name__
                state = promise._state
                handling = promise.is_handling
                G.add_node(nid, name=name, state=state,
                           layer=layer, handling=handling)
                node_id += 1
                layer += 1
            for p in promise._on_fulfillment:
                name = p._func.__name__
                state = p._state
                handling = p.is_handling
                G.add_node(node_id, name=name, state=state,
                           layer=layer, handling=handling)
                G.add_edge(nid, node_id, condition='fulfill')
                nid2 = node_id
                node_id += 1
                add(_G, p, nid2, False, layer=layer+1)

            for p in promise._on_rejection:
                name = p._func.__name__
                state = p._state
                handling = p.is_handling
                G.add_node(node_id, name=name, state=state,
                           layer=layer, handling=handling)
                G.add_edge(nid, node_id, condition='reject')
                nid2 = node_id
                node_id += 1
                add(_G, p, nid2, False, layer=layer+1)

        add(G, self, node_id)
        pos = nx.multipartite_layout(G, subset_key="layer")
        color = [colors[data["state"]] for v, data in G.nodes(data=True)]
        nx.draw_networkx_nodes(G, pos, node_color=color)
        nodes_handling = [v for v, data in G.nodes.data() if data['handling']]
        nx.draw_networkx_nodes(
            G, pos, node_color='yellow', nodelist=nodes_handling)

        edges_fulfill = [data[:2] for data in G.edges.data(
        ) if data[2]['condition'] == 'fulfill']
        edges_reject = [data[:2]
                        for data in G.edges.data() if data[2]['condition'] == 'reject']
        if len(edges_fulfill) > 0:
            nx.draw_networkx_edges(G, pos, edgelist=edges_fulfill, style='-')
        if len(edges_reject) > 0:
            nx.draw_networkx_edges(G, pos, edgelist=edges_reject, style='--')

        labels = {v: data['name'] for v, data in G.nodes.data()}
        labels = nx.draw_networkx_labels(G, pos, labels)
        for t in labels.values():
            t.set_rotation(30)

        plt.tight_layout()
        plt.axis("off")
        plt.show()
        pass
