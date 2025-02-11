from instance import Instance
from request import Request
from status import Status
from config import Config

class Serverless(Instance):
    def __init__(self, capacity = Config.CONFIG_DEFAULT_CAPACITY, num_CPU = Config.CONFIG_DEFAULT_num_CPU, queue_length = Config.CONFIG_DEFAULT_QUEUE_LENGTH, status = Config.CONFIG_DEFAULT_STATUS):
        super().__init__(capacity, num_CPU, queue_length, status)
        self.last_time = -1
        return
    
    def activateInstance(self):
        self.setuptimer = Config.CONFIG_DEFAULT_SETUPTIME * Config.SIM_STEP_PER_TIME
        self.setStatus(Status.SETUP)
        print("START SCALE OUT")
        return
    
    def setupInstance(self):
        self.setuptimer -= 1
        if self.setuptimer <= 0:
            self.setStatus(Status.ACTIVE)
            print("COMPLETE SCALE OUT: " + str(self.getId()))
        return
    
    def deactivateInstance(self):
        self.deactivatetimer = Config.CONFIG_DEFAULT_SHUTDOWNTIME * Config.SIM_STEP_PER_TIME
        print("START SCALE IN")
        return
    
    def shutdownInstance(self):
        self.deactivatetimer -= 1
        if self.deactivatetimer < 0:
            self.setStatus(Status.INACTIVE)
            self.setCpuCtr(0)
            print("COMPLETE SCALE IN: " + str(self.getId()))
        return
    
    def runStep(self, time):
        status = self.getStatus()
        if status == Status.ACTIVE or status == Status.WORKING:
            end_reqs, is_process = self.processRequests(time)
            length = self.getQueueLength()
            return end_reqs, length, is_process
        elif status == Status.SETUP:
            self.setupInstance()
        elif status == Status.SHUTDOWN:
            self.shutdownInstance()
        return [], self.getQueueLength(), False
    
    def getLastTime(self):
        return self.last_time
    
    def setLastTime(self, time):
        self.last_time = time
    
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
                self.setLastTime(time)
                return req
        else:
            req.setStatus(Status.FINISHED)
            req.setEndTime(time / Config.SIM_STEP_PER_TIME)
            self.delRequest(req)
            self.setLastTime(time)
            return req
        return None
