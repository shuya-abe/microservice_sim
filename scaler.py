from status import Status
from config import Config
import math

class Scaler:
    
    def __init__(self, balancer = None):
        self.setBalancer(balancer)
        self.containers = []
        self.num_active_container = 0
        return
    
    def runStep(self, timestep):
        if not self.isTime2Check(timestep):
            return
        
        metrics = self.getMetrics()
        print(str(timestep) + ", METRICS: " + str(metrics))
        if metrics - 1 > Config.CONFIG_SCALE_SENSITIVE:
            self.scaleOut(metrics)
        elif 1 - metrics > Config.CONFIG_SCALE_SENSITIVE:
            self.scaleIn(metrics)
        else:
            print("no Scale change")
        return
    
    def setBalancer(self, balancer):
        self.balancer = balancer
        return
    
    def getBalancer(self):
        return self.balancer
    
    def addContainer(self, container):
        self.containers.append(container)
        if container.getStatus() == Status.ACTIVE:
            self.num_active_container += 1
            self.registerContainer2Balancer(container)
        return
    
    def getContainers(self):
        return self.containers
    
    # def activateContainer(self, container):
    #     return
    
    # def inactivateContainer(self, container):
    #     return
    
    def registerContainer2Balancer(self, container):
        self.getBalancer().addContainer(container)
        return
    
    def removeContainerFromBalancer(self, container):
        self.getBalancer().delContainer(container)
        return
    
    # def calculateTargetNumOfContainers(self):
    #     return
    
    # def calculateAverageUtilization(self):
    #     return
        
    def scaleOut(self, metrics):
        ideal_num_container = math.ceil(self.num_active_container * metrics)
        num_active_container = self.num_active_container
        for container in self.getContainers():
            if ideal_num_container <= num_active_container:
                return
            if container.getStatus() == Status.INACTIVE:
                print("Scale Out")
                container.activateContainer(self)
                num_active_container += 1
        return
    
    def scaleIn(self, metrics):
        ideal_num_container = max(1, math.ceil(self.num_active_container * metrics))
        num_active_container = self.num_active_container
        for container in reversed(self.getContainers()):
            if ideal_num_container >= num_active_container:
                return
            status = container.getStatus()
            if (status == Status.WORKING or status == Status.ACTIVE) and container.deactivatetimer < 0:
                print("Scale In")
                container.deactivateContainer()
                self.removeContainerFromBalancer(container)
                num_active_container -= 1
        return
    
    def getMetrics(self):
        self.num_active_container = 0
        cpu_util = 0
        for container  in self.getContainers():
            status = container.getStatus()
            if (status == Status.WORKING or status == Status.ACTIVE) and container.deactivatetimer < 0:
                cpu_util += container.getCpuUtilization()
                container.setCpuCtr(0)
                self.num_active_container += 1
        cpu_util /= self.num_active_container
        ideal_container =  cpu_util / Config.CONFIG_SCALE_TARGET
        return ideal_container
    
    def isTime2Check(self, timestep):
        return timestep != 0 and (timestep % (Config.CONFIG_SCALE_INTERVAL * Config.SIM_STEP_PER_TIME)) == 0
    