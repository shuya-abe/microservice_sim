from constant import Constant

class Flg(Constant):
    FLG_DEFAULT = 0
    FLG_VERBOSE = 1

    FLG_OUTPUT = 10
    FLG_INPUT = 11
    
    FLG_CONTAINER = 20
    FLG_SERVERLESS = 21
    # Serverless routing that may wait for warm capacity instead of always cold-starting.
    FLG_SERVERLESS_WARM_WAIT = 22

    def __init__(self):
        return

    @staticmethod
    def is_serverless(mode):
        return mode in (Flg.FLG_SERVERLESS, Flg.FLG_SERVERLESS_WARM_WAIT)
