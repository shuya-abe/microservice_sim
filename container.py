from instance import Instance
from request import Request
from status import Status
from config import Config

class Container(Instance):
    def __init__(self, capacity, num_CPU, queue_length, status, config):
        super().__init__(capacity, num_CPU, queue_length, status, config)
        return
    
    def activateInstance(self, scaler):
        self.scaler = scaler
        self.setuptimer = self.config.CONFIG_DEFAULT_SETUPTIME * self.config.SIM_STEP_PER_TIME
        self.setStatus(Status.SETUP)
        # print("START SCALE OUT")
        return
    
    def setupInstance(self):
        self.setuptimer -= 1
        if self.setuptimer < 0:
            self.setStatus(Status.ACTIVE)
            # print("COMPLETE SCALE OUT: " + str(self.getId()))
            self.scaler.registerInstance2Balancer(self)
            self.scaler = None
        return

    def processRequest(self, req:Request, time):
        workload = req.workload
        if workload > 0:
            if req.status != Status.PROCESSING:
                req.status = Status.PROCESSING
                req.time_start_process = time / self.config.SIM_STEP_PER_TIME
            workload -= self.processing_capacity
            req.workload = workload
            # if workload <= 0:
            #     req.setStatus(Status.FINISHED)
            #     req.setEndTime(time / self.config.SIM_STEP_PER_TIME)
            #     self.delRequest(req)
            #     return req
        else:
            req.status = Status.FINISHED
            req.time_end = time / self.config.SIM_STEP_PER_TIME
            # self.delRequest(req)
            return req
        return None

