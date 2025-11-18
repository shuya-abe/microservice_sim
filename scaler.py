from status import Status
from config import Config
import math
from sim_flg import Flg

class Scaler:
    
    def __init__(self, balancer, config:Config):
        self.config = config
        self.setBalancer(balancer)
        self.instances = []
        self.num_active_instance = 0
        self.mode = self.config.CONFIG_INSTANCE_FLG
        return
    
    def runStep(self, timestep):
        if self.mode == Flg.FLG_CONTAINER:
            self.runStep4Container(timestep)
        elif self.mode == Flg.FLG_SERVERLESS:
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
        for instance in self.getInstances():
            if instance.getStatus() == Status.ACTIVE:
                if timestep - instance.getLastTime() >= self.config.CONFIG_SERVERLESS_TIMER * self.config.SIM_STEP_PER_TIME:
                    self.deactivateOldInstance(instance)
    
    def setBalancer(self, balancer):
        self.balancer = balancer
        return
    
    def getBalancer(self):
        return self.balancer
    
    def addInstance(self, instance):
        self.instances.append(instance)
        if instance.getStatus() == Status.ACTIVE:
            self.num_active_instance += 1
            self.registerInstance2Balancer(instance)
        return
    
    def getInstances(self):
        return self.instances
    
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
        for instance  in self.getInstances():
            status = instance.getStatus()
            # if (status == Status.WORKING or status == Status.ACTIVE) and instance.deactivatetimer < 0:
            if status == Status.WORKING or status == Status.ACTIVE:
                cpu_util += instance.getCpuUtilization()
                instance.setCpuCtr(0)
                self.num_active_instance += 1
        cpu_util /= self.num_active_instance
        ideal_instance =  cpu_util / self.config.CONFIG_SCALE_TARGET
        return ideal_instance
    
    def isTime2Check(self, timestep):
        return timestep != 0 and (timestep % (self.config.CONFIG_SCALE_INTERVAL * self.config.SIM_STEP_PER_TIME)) == 0
    