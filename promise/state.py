import enum

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
