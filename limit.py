from constant import Constant

class Limit(Constant):
    LIMIT_DEFAULT = 0
    LIMIT_REQUEST = 1
    LIMIT_TIMESTEP = 2
    LIMIT_TIME = 3

    def __init__(self):
        return