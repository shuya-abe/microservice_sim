from instance import Instance
from request import Request
from status import Status
from config import Config

class Serverless(Instance):
    def __init__(self, capacity, num_CPU, queue_length, status, config:Config):
        super().__init__(capacity, num_CPU, queue_length, status, config)
        self.last_time = -1
        return
    
    def getLastTime(self):
        return self.last_time
    
    def setLastTime(self, time):
        self.last_time = time
        
    def activateInstance(self):
        self.setuptimer = self.config.CONFIG_DEFAULT_SETUPTIME * self.config.SIM_STEP_PER_TIME + 1
        self.setStatus(Status.SETUP)
        # print("START SCALE OUT")
        return
    
    def setupInstance(self):
        self.setuptimer -= 1
        if self.setuptimer <= 0:
            self.setStatus(Status.ACTIVE)
            # print("COMPLETE SCALE OUT: " + str(self.getId()))
        return

    def processRequest(self, req:Request, time):
        workload = req.getWorkload()
        if workload > 0:
            if req.getStatus() != Status.PROCESSING:
                req.setStatus(Status.PROCESSING)
                req.setStartProcessTime(time / self.config.SIM_STEP_PER_TIME)
            workload -= self.processing_capacity
            req.setWorkload(workload)
            # if workload <= 0:
            #     req.setStatus(Status.FINISHED)
            #     req.setEndTime(time / Config.SIM_STEP_PER_TIME)
            #     self.delRequest(req)
            #     self.setLastTime(time)
            #     return req
            self.setLastTime(time)
        else:
            req.setStatus(Status.FINISHED)
            req.setEndTime(time / self.config.SIM_STEP_PER_TIME)
            # self.delRequest(req)
            self.setLastTime(time)
            return req
        return None
