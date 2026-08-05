from request import Request
from instance import Instance
from status import Status
from config import Config
from sim_flg import Flg

class Balancer:

    def __init__(self, config):
        self.config = config
        self.instances: list[Instance] = []
        self.requests: list[Request] = []
        self.last_instance = -1
        self.mode = self.config.CONFIG_INSTANCE_FLG
        self.scaler = None
        return
    
    def setScaler(self, scaler):
        self.scaler = scaler
        return
        
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
        reqs = self.getRequests()
        remain_reqs = []
        for req in reqs:
            # 1-based position among still-unassigned requests (FIFO front = 1).
            queue_position = len(remain_reqs) + 1
            if self.tryForward2Instance(req, queue_len=queue_position) is None:
                remain_reqs.append(req)
        reqs[:] = remain_reqs
        return
    
    def tryForward2Instance(self, req, queue_len=None):
        instance = self.chooseInstance(queue_len=queue_len)
        if instance:
            return self.forward2Instance(instance, req)
        else:
            return None

    def chooseInstance(self, queue_len=None):
        if queue_len is None:
            queue_len = len(self.getRequests())

        if self.mode == Flg.FLG_CONTAINER:
            # round robin
            # instance = self.roundRobin()
            
            # 0916 balancer with queue
            for instance in self.getInstances():
                if (instance.getStatus() == Status.ACTIVE or instance.getStatus() == Status.WORKING) and instance.getQueueLength() == 0:
                    return instance
            return None

        elif self.mode == Flg.FLG_SERVERLESS:
            # hottest
            instance = self.hottest()
            if instance == None:
                instance = self.coldStart()
            return instance

        elif self.mode == Flg.FLG_SERVERLESS_WARM_WAIT:
            instance = self.hottest()
            if instance is not None:
                return instance
            # Prefer an already-starting instance over opening another cold start.
            setup = self.idleSetupInstance()
            if setup is not None:
                return setup
            if self.shouldColdStartRatherThanWait(queue_len=queue_len):
                return self.coldStart()
            return None

        return None

    def idleSetupInstance(self):
        """SETUP instance with empty queue (capacity reserved for one waiting request)."""
        for instance in self.getInstances():
            if instance.getStatus() == Status.SETUP and instance.getQueueLength() == 0:
                return instance
        return None

    def countWarmCapacity(self):
        """Number of warm (ACTIVE/WORKING) CPU slots currently registered to the balancer."""
        warm_cpus = 0
        for instance in self.getInstances():
            status = instance.getStatus()
            if status == Status.ACTIVE or status == Status.WORKING:
                warm_cpus += instance.getNumCPU()
        return warm_cpus

    def expectedWarmWaitTime(self, queue_position):
        """
        Expected wait (logical time) for the request at 1-based position
        `queue_position` in the balancer queue: p / (warm_cpus * mu).
        """
        warm_cpus = self.countWarmCapacity()
        mu = float(self.config.CONFIG_MU)
        if warm_cpus <= 0 or mu <= 0:
            return float("inf")
        p = max(int(queue_position), 1)
        return p / (warm_cpus * mu)

    def shouldColdStartRatherThanWait(self, queue_len):
        """
        Cold-start only when THIS request's expected warm-wait exceeds setup time.

        With warm capacity W (CPU slots), setup time S, service rate μ:
          absorb ≈ S * W * μ   # requests warm pool can drain within S
          cold-start iff queue_position > absorb

        `queue_len` here is the 1-based position of the current request among
        still-unassigned balancer requests (earlier deferred + current).
        """
        setup_time = float(self.config.CONFIG_DEFAULT_SETUPTIME)
        warm_cpus = self.countWarmCapacity()
        mu = float(self.config.CONFIG_MU)
        position = max(int(queue_len), 1)

        if warm_cpus <= 0 or mu <= 0:
            # No warm capacity: open a new instance (idle SETUP handled earlier).
            return True

        absorb = setup_time * warm_cpus * mu
        return position > absorb

    def hasAssignableOrScalableWork(self):
        """True if balancer queue can be progressed this step (assign or cold-start)."""
        if not self.getRequests():
            return False
        if self.mode != Flg.FLG_SERVERLESS_WARM_WAIT:
            return True
        if self.hottest() is not None:
            return True
        if self.idleSetupInstance() is not None:
            return True
        return self.shouldColdStartRatherThanWait(queue_len=1)
    
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
            if instance.getStatus() == Status.ACTIVE and instance.getQueueLength() == 0:
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
        # self.delRequest(req)
        if self.mode == Flg.FLG_CONTAINER:
            req.setProcessedBy("container" + str(instance.getId()))
        elif self.mode == Flg.FLG_SERVERLESS:
            req.setProcessedBy("serverless" + str(instance.getId()))
        elif self.mode == Flg.FLG_SERVERLESS_WARM_WAIT:
            req.setProcessedBy("serverless_warm_wait" + str(instance.getId()))
        instance.addRequest(req)
        self.last_instance = self.getInstances().index(instance)
        return req

    def delRequest(self, req:Request):
        self.requests.remove(req)
        return
