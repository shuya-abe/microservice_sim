from request import Request
from status import Status
from config import Config

class Container:
    # id = -1
    # processing_capacity = -1
    # num_CPU = -1
    # max_queue_length = -1

    def __init__(self, capacity = Config.CONFIG_DEFAULT_CAPACITY, num_CPU = Config.CONFIG_DEFAULT_num_CPU, queue_length = Config.CONFIG_DEFAULT_QUEUE_LENGTH, status = Config.CONFIG_DEFAULT_STATUS):
        self.id = -1
        self.setuptimer = -1
        self.deactivatetimer = -1
        self.status = status
        self.processing_capacity = capacity / Config.SIM_STEP_PER_TIME
        self.num_CPU = num_CPU
        self.max_queue_length = queue_length
        self.queue: list[Request] = []
        self.CpuCtr = 0
        return
    
    def setId(self, id):
        self.id = id

    def getId(self):
        return self.id

    def setCapacity(self, capacity):
        self.processing_capacity = capacity
        return

    def getCapacity(self):
        return self.processing_capacity
    
    def getQueueLength(self):
        return len(self.queue)
    
    def setNumCPU(self, num_CPU):
        self.num_CPU = num_CPU
        return

    def getNumCPU(self):
        return self.num_CPU

    def getMaxQueueLength(self):
        return self.max_queue_length
    
    def addRequest(self, req:Request):
        if self.getMaxQueueLength() < self.getQueueLength() or self.getMaxQueueLength() < 0:
            req.setStatus(Status.QUEUEING)
            self.queue.append(req)
        else:
            req.setStatus(Status.DROP)
        return
    
    def delRequest(self, req:Request):
        req.setStatus(Status.FINISHED)
        self.queue.remove(req)
        return
    
    def setStatus(self, status):
        self.status = status
        return
    
    def getStatus(self):
        return self.status
    
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

    def processRequests(self, time):
        end_reqs: list[Request] = []
        num_CPU = self.num_CPU
        is_process = False
        for req in self.queue:
            if num_CPU > 0:
                self.setStatus(Status.WORKING)
                return_req = self.processRequest(req, time)
                is_process = True
                if return_req is not None:
                    end_reqs.append(return_req)
                self.incrementCpuCtr()
                num_CPU -= 1
            else:
                break
        if not is_process:
            if self.deactivatetimer < 0:
                self.setStatus(Status.ACTIVE)
            else:
                self.setStatus(Status.SHUTDOWN)
        return end_reqs, is_process
    
    def getCpuUtilization(self):
        return self.getCpuCtr() / ((Config.CONFIG_SCALE_INTERVAL * Config.SIM_STEP_PER_TIME) * self.getNumCPU())
    
    def incrementCpuCtr(self):
        self.CpuCtr += 1

    def setCpuCtr(self, ctr):
        self.CpuCtr = ctr
    
    def getCpuCtr(self):
        return self.CpuCtr
    
    def activateContainer(self, scaler):
        self.scaler = scaler
        self.setuptimer = Config.CONFIG_DEFAULT_SETUPTIME * Config.SIM_STEP_PER_TIME
        self.setStatus(Status.SETUP)
        print("START SCALE OUT")
        return
    
    def setupContainer(self):
        self.setuptimer -= 1
        if self.setuptimer <= 0:
            self.setStatus(Status.ACTIVE)
            print("COMPLETE SCALE OUT: " + str(self.getId()))
            self.scaler.registerContainer2Balancer(self)
            self.scaler = None
        return
    
    def deactivateContainer(self):
        self.deactivatetimer = Config.CONFIG_DEFAULT_SHUTDOWNTIME * Config.SIM_STEP_PER_TIME
        print("START SCALE IN")
        return
    
    def shutdownContainer(self):
        self.deactivatetimer -= 1
        if self.deactivatetimer < 0:
            self.setStatus(Status.INACTIVE)
            self.setCpuCtr(0)
            print("COMPLETE SCALE IN: " + str(self.getId()))
        return
    
    def stopContainer(self):
        self.de
    
    def runStep(self, time):
        status = self.getStatus()
        if status == Status.ACTIVE or status == Status.WORKING:
            end_reqs, is_process = self.processRequests(time)
            length = self.getQueueLength
            return end_reqs, length, is_process
        elif status == Status.SETUP:
            self.setupContainer()
        elif status == Status.SHUTDOWN:
            self.shutdownContainer()
        return [], self.getQueueLength, False
