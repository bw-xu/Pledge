from ...Offline.LoopOffline import LoopOffline as Loop, Task
from functools import partial, wraps
import inspect
from ...Offline.Future import Future
import enum
from typing import Callable
from typing import List

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

class State(enum.IntEnum):
    PENDING = -1
    FULLFILLED = 0
    REJECTED = 1

    @property
    def pedning(self):
        return self is State.PENDING

    @property
    def fullfilled(self):
        return self is State.FULLFILLED

    @property
    def rejected(self):
        return self is State.REJECTED
    
    @property
    def settled(self):
        return self is State.REJECTED or self is State.FULLFILLED

class TaskCallback:
    def __init__(self) -> None:
        pass

class Pledge:
    ''''''

    def __init__(self, func: Callable=None, loop: Loop=None):
        self._state = State.PENDING

        self._loop = loop if loop is not None else _loop
        self._func = func
        self._on_fulfillment: List[Pledge] = []
        self._on_rejection: List[Pledge] = []

        self._result = None
        self._error = None

        self.is_handling = False
    
    def _set_result(self, result):
        if result is not None:
            self._state = State.FULLFILLED
            if not isinstance(result, tuple):
                result = (result, )
        self._result = result
    
    def _set_error(self, error):
        if error is not None:
            self._state = State.REJECTED
        self._error = error

    async def _async_execute(self, *args, **kwargs):
        ''''''
        self.is_handling = True
        try:
            success = await self._func(*args, **kwargs)
            self.is_handling = False
            if not isinstance(success, tuple):
                success = (success, )
            self._set_result(success)
            self._fullfill(*success)
        except Exception as error:
            self.is_handling = False
            self._set_error(error)
            self._reject(error)
        finally:
            self.is_handling = False

    def _execute(self, *args, **kwargs):
        '''
        执行self._func
        '''
        success, error = None, None
        if callable(self._func):
            if inspect.iscoroutinefunction(self._func):
                self._loop.async_call(self._async_execute, *args, **kwargs)
            else:
                self.is_handling = True
                try:
                    success = self._func(*args, **kwargs)
                    self.is_handling = False
                    if not isinstance(success, tuple):
                        success = (success, )
                    self._set_result(success)
                    self._fullfill(*success)
                except Exception as error:
                    self.is_handling = False
                    self._set_error(error)
                    self._reject(error)
                finally:
                    self.is_handling = False


    def _fullfill(self, *ret):
        self._state = State.FULLFILLED
        for pledge in self._on_fulfillment:
            pledge._execute(*ret)


    def _reject(self, error):
        self._state = State.REJECTED
        for pledge in self._on_rejection:
            pledge._execute(error)


    def apply(self, *args, **kwargs):
        if self._func is not None:
            self._execute(*args, **kwargs)
        elif self._result is not None:
            self._fullfill(*self._result)
        elif self._error is not None:
            self._reject(self._error)


    def then(self, on_fulfillment=None, on_rejection=None):
        """
        """
        if on_rejection is not None:
            pledge = Pledge(on_rejection, self._loop)
            self._on_rejection.append(pledge)
        if on_fulfillment is not None:
            pledge = Pledge(on_fulfillment, self._loop)
            self._on_fulfillment.append(pledge)

        return pledge


    def catch(self, on_rejected):
        return self.then(None, on_rejected)

    def finally_(self, on_settled):
        def _finally(result):
            return on_settled()

        return self.then(_finally, _finally)
    

    def cancel(self):
        ''''''

    def cancelled(self):
        ''''''
    
    @staticmethod
    def resolve(value):
        ''''''

    @staticmethod
    def reject(reason):
        ''''''
    
    @staticmethod
    def all(promises):
        ''''''

    @staticmethod
    def all_settled(promises):
        ''''''

    @staticmethod
    def any(promises):
        ''''''

    @staticmethod
    def race(promises):
        ''''''


    def __await__(self):
        ''''''

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
        def add(_G: nx.DiGraph, pledge: Pledge, nid, add_self=True, layer=0):
            nonlocal node_id
            if add_self:
                name = pledge._func.__name__
                state = pledge._state
                handling = pledge.is_handling
                G.add_node(nid, name=name, state=state, layer=layer, handling=handling)
                node_id += 1
                layer += 1
            for p in pledge._on_fulfillment:
                name = p._func.__name__
                state = p._state
                handling = p.is_handling
                G.add_node(node_id, name=name, state=state, layer=layer, handling=handling)
                G.add_edge(nid, node_id, condition='fulfill')
                nid2 = node_id
                node_id += 1
                add(_G, p, nid2, False, layer=layer+1)

            for p in pledge._on_rejection:
                name = p._func.__name__
                state = p._state
                handling = p.is_handling
                G.add_node(node_id, name=name, state=state, layer=layer, handling=handling)
                G.add_edge(nid, node_id, condition='reject')
                nid2 = node_id
                node_id += 1
                add(_G, p, nid2, False, layer=layer+1)


        add(G, self, node_id)
        pos = nx.multipartite_layout(G, subset_key="layer")
        color = [colors[data["state"]] for v, data in G.nodes(data=True)]
        nx.draw_networkx_nodes(G, pos, node_color=color)
        nodes_handling = [v for v, data in G.nodes.data() if data['handling']]
        nx.draw_networkx_nodes(G, pos, node_color='yellow', nodelist=nodes_handling)


        edges_fulfill = [data[:2] for data in G.edges.data() if data[2]['condition'] == 'fulfill']
        edges_reject = [data[:2] for data in G.edges.data() if data[2]['condition'] == 'reject']
        if len(edges_fulfill) > 0: nx.draw_networkx_edges(G, pos, edgelist=edges_fulfill, style='-')
        if len(edges_reject) > 0: nx.draw_networkx_edges(G, pos, edgelist=edges_reject, style='--')

        labels = {v: data['name'] for v, data in G.nodes.data()}
        labels = nx.draw_networkx_labels(G, pos, labels)
        for t in labels.values():
            t.set_rotation(30)

        plt.tight_layout()
        plt.axis("off")
        plt.show()
        pass

