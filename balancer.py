from request import Request
from instance import Instance
from status import Status
from config import Config
from sim_flg import Flg

class Balancer:

    def __init__(self):
        self.instances: list[Instance] = []
        self.requests: list[Request] = []
        self.last_instance = -1
        self.mode = Config.CONFIG_INSTANCE_FLG
        self.scaler = None
        return
    
    def setScaler(self, scaler):
        self.scaler = scaler
        
    def getScaler(self):
        return self.scaler
    
    def addRequest(self, request: Request):
        request.setStatus(Status.UNASSIGNED)
        self.requests.append(request)
        return

    def getRequest(self, i: int):
        return self.requests(i)
    
    def getRequests(self):
        return self.requests

    def clearRequests(self):
        self.requests.clear()
        return
    
    def addInstance(self, instance):
        self.instances.append(instance)
        return
    
    def delInstance(self, instance):
        self.instances.remove(instance)
        return
    
    def getInstance(self, i: int):
        return self.instances[i]
    
    def getInstances(self):
        return self.instances
    
    def getNumOfInstances(self):
        return len(self.instances)
    
    def clearInstances(self):
        self.instances.clear()
        return

    def isContainedInstance(self, instance):
        return instance in self.instances

    def runStep(self):
        self.manageQueue()
        return

    def manageQueue(self):
        for req in self.getRequests():
            self.tryForward2Instance(req)
        return
    
    def tryForward2Instance(self, req):
        instance = self.chooseInstance()
        if instance:
            self.forward2Instance(instance, req)

    def chooseInstance(self):
        if self.mode == Flg.FLG_CONTAINER:
            # round robin
            instance = self.roundRobin()
        elif self.mode == Flg.FLG_SERVERLESS:
            # hottest
            instance = self.hottest()
            if instance == None:
                instance = self.coldStart()
        else:
            return None
        return instance
    
    def roundRobin(self):
        instance = None
        if self.last_instance + 1 < len(self.getInstances()):
            next_instance = self.last_instance + 1
        else:
            next_instance = 0
        instance = self.getInstance(next_instance)
        return instance
    
    def hottest(self):
        hottest = None
        last_time = -1
        for instance in self.getInstances():
            if instance.getStatus() == Status.ACTIVE:
                temp_last = instance.getLastTime()
                if last_time < temp_last:
                    last_time = temp_last
                    hottest = instance
        return hottest
    
    def coldStart(self):
        instance = None
        scaler = self.getScaler()
        instance = scaler.coldStartInstance()
        return instance

    def forward2Instance(self, instance: Instance, req: Request):
        self.delRequest(req)
        if self.mode == Flg.FLG_CONTAINER:
            req.setProcessedBy("container" + str(instance.getId()))
        elif self.mode == Flg.FLG_SERVERLESS:
            req.setProcessedBy("serverless" + str(instance.getId()))
        instance.addRequest(req)
        self.last_instance = self.getInstances().index(instance)
        return

    def delRequest(self, req:Request):
        self.requests.remove(req)
        return