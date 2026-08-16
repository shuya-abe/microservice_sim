from status import Status
from config import Config
import math
from sim_flg import Flg

class Scaler:
    
    def __init__(self, balancer, config:Config):
        self.config = config
        self.setBalancer(balancer)
        self.instances = []
        self.runnable_instances = []
        self.runnable_instance_set = set()
        self.num_active_instance = 0
        self.mode = self.config.CONFIG_INSTANCE_FLG
        return
    
    def runStep(self, timestep):
        if self.mode == Flg.FLG_CONTAINER:
            self.runStep4Container(timestep)
        elif Flg.is_serverless(self.mode):
            self.runStep4Serverless(timestep)
    
    def runStep4Container(self, timestep):
        if not self.isTime2Check(timestep):
            return
        
        metrics = self.getMetrics()
        # print(str(timestep) + ", METRICS: " + str(metrics))
        if metrics - 1 > self.config.CONFIG_SCALE_SENSITIVE:
            self.scaleOut(metrics)
        elif 1 - metrics > self.config.CONFIG_SCALE_SENSITIVE:
            self.scaleIn(metrics)
        # else:
            # print("no Scale change")
        return
    
    def runStep4Serverless(self, timestep):
        # In warm-wait mode, keep warm instances while requests are queued at the balancer.
        defer_idle = (
            self.mode == Flg.FLG_SERVERLESS_WARM_WAIT
            and bool(self.getBalancer().getRequests())
        )
        for instance in self.getRunnableInstances():
            if instance.getStatus() == Status.ACTIVE:
                if defer_idle:
                    continue
                if timestep - instance.getLastTime() >= self.config.CONFIG_SERVERLESS_TIMER * self.config.SIM_STEP_PER_TIME:
                    self.deactivateOldInstance(instance)
    
    def setBalancer(self, balancer):
        self.balancer = balancer
        return
    
    def getBalancer(self):
        return self.balancer
    
    def addInstance(self, instance):
        self.instances.append(instance)
        instance.setStatusManager(self)
        if instance.getStatus() != Status.INACTIVE:
            self.registerRunnableInstance(instance)
        if instance.getStatus() == Status.ACTIVE:
            self.num_active_instance += 1
            self.registerInstance2Balancer(instance)
        return
    
    def getInstances(self):
        return self.instances

    def getRunnableInstances(self):
        return self.runnable_instances

    def registerRunnableInstance(self, instance):
        if instance not in self.runnable_instance_set:
            self.runnable_instances.append(instance)
            self.runnable_instance_set.add(instance)
        return

    def removeRunnableInstance(self, instance):
        if instance in self.runnable_instance_set:
            self.runnable_instance_set.remove(instance)
            self.runnable_instances.remove(instance)
        return
    
    def registerInstance2Balancer(self, instance):
        self.getBalancer().addInstance(instance)
        return
    
    def removeInstanceFromBalancer(self, instance):
        self.getBalancer().delInstance(instance)
        return
    
    def scaleOut(self, metrics):
        ideal_num_instance = math.ceil(self.num_active_instance * metrics)
        num_active_instance = self.num_active_instance
        for instance in self.getInstances():
            if ideal_num_instance <= num_active_instance:
                return
            
            status = instance.getStatus()
            if status == Status.SETUP:
                num_active_instance += 1
            elif (status == Status.WORKING or status == Status.ACTIVE) and instance.deactivatetimer >= 0:
                    instance.deactivatetimer = -1
                    self.registerInstance2Balancer(instance)
                    # print("scaleOut")
                    num_active_instance += 1
            elif status == Status.INACTIVE or status == Status.SHUTDOWN:
                # print("scaleOut")
                instance.deactivatetimer = -1
                instance.activateInstance(self)
                num_active_instance += 1
        return
    
    def coldStartInstance(self):
        for instance in self.getInstances():
            if instance.getStatus() == Status.INACTIVE:
                # print("Cold Start")
                instance.activateInstance(self)
                self.registerInstance2Balancer(instance)
                return instance
        return None
    
    def scaleIn(self, metrics):
        ideal_num_instance = max(1, math.ceil(self.num_active_instance * metrics))
        num_active_instance = self.num_active_instance
        # print(ideal_num_instance - num_active_instance)
        for instance in reversed(self.getInstances()):
            if ideal_num_instance >= num_active_instance:
                return
            status = instance.getStatus()
            # if (status == Status.WORKING or status == Status.ACTIVE) and instance.deactivatetimer < 0:
            if (status == Status.WORKING or status == Status.ACTIVE):
                if instance.deactivatetimer < 0:
                    # print("Scale In")
                    instance.deactivateInstance()
                    self.removeInstanceFromBalancer(instance)
                num_active_instance -= 1
            elif status == Status.SETUP:
                instance.deactivateInstance()
                instance.setStatus(Status.SHUTDOWN)
                instance.setuptimer = -1
                num_active_instance -= 1
                # print("scaleIn")
        return
    
    def deactivateOldInstance(self, instance):
        status = instance.getStatus()
        if status == Status.ACTIVE:
            # print("deactivate Old Instance")
            instance.deactivateInstance()
            self.removeInstanceFromBalancer(instance)
   
    def getMetrics(self):
        self.num_active_instance = 0
        cpu_util = 0
        for instance in self.getRunnableInstances():
            status = instance.getStatus()
            # if (status == Status.WORKING or status == Status.ACTIVE) and instance.deactivatetimer < 0:
            if status == Status.WORKING or status == Status.ACTIVE:
                cpu_util += instance.getCpuUtilization()
                instance.setCpuCtr(0)
                self.num_active_instance += 1
        if self.num_active_instance == 0:
            return 1.0
        cpu_util /= self.num_active_instance
        ideal_instance =  cpu_util / self.config.CONFIG_SCALE_TARGET
        return ideal_instance
    
    def isTime2Check(self, timestep):
        return timestep != 0 and (timestep % (self.config.CONFIG_SCALE_INTERVAL * self.config.SIM_STEP_PER_TIME)) == 0
    