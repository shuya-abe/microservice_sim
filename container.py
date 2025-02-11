from instance import Instance
from request import Request
from status import Status
from config import Config

class Container(Instance):
    def __init__(self, capacity = Config.CONFIG_DEFAULT_CAPACITY, num_CPU = Config.CONFIG_DEFAULT_num_CPU, queue_length = Config.CONFIG_DEFAULT_QUEUE_LENGTH, status = Config.CONFIG_DEFAULT_STATUS):
        super().__init__(capacity, num_CPU, queue_length, status)
        return
    
    def activateInstance(self, scaler):
        self.scaler = scaler
        self.setuptimer = Config.CONFIG_DEFAULT_SETUPTIME * Config.SIM_STEP_PER_TIME
        self.setStatus(Status.SETUP)
        print("START SCALE OUT")
        return
    
    def setupInstance(self):
        self.setuptimer -= 1
        if self.setuptimer <= 0:
            self.setStatus(Status.ACTIVE)
            print("COMPLETE SCALE OUT: " + str(self.getId()))
            self.scaler.registerInstance2Balancer(self)
            self.scaler = None
        return

    def processRequest(self, req:Request, time):
        workload = req.getWorkload()
        if workload > 0:
            if req.getStatus() != Status.PROCESSING:
                req.setStatus(Status.PROCESSING)
                req.setStartProcessTime(time / Config.SIM_STEP_PER_TIME)
            workload -= self.processing_capacity
            req.setWorkload(workload)
            if workload <= 0:
                req.setStatus(Status.FINISHED)
                req.setEndTime(time / Config.SIM_STEP_PER_TIME)
                self.delRequest(req)
                return req
        else:
            req.setStatus(Status.FINISHED)
            req.setEndTime(time / Config.SIM_STEP_PER_TIME)
            self.delRequest(req)
            return req
        return None