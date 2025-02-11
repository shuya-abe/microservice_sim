from constant import Constant

class Status(Constant):
    DEFAULT = -1
    GENERATED = 0
    UNASSIGNED = 1
    QUEUEING = 2
    PROCESSING = 3
    FINISHED = 4
    DROP = 5
    
    INACTIVE = 11
    SETUP = 12
    ACTIVE = 13
    WORKING = 14
    SHUTDOWN = 15

    def __init__(self):
        return