import numpy.random as rd
import math
from request import Request
from instance import Instance
from limit import Limit
from config import Config
from status import Status

class Cluster:

    def __init__(self):
        self.balancer = None
        self.instances = []
        self.scaler = None
        self.num_CPU = Config.CONFIG_CLUSTER_CPU
        self.num_active_CPU = 0
        return

    def addBalancer(self, balancer):
        self.balancer = balancer
        return

    def getBalancer(self):
        return self.balancer
    
    def getActiveCPU(self):
        return self.num_active_CPU
    
    def setActiveCPU(self, cpu):
        self.num_active_CPU = cpu

    def getMaxCPU(self):
        return self.num_CPU

    def addInstance(self, instance):
        num_cpu = instance.getNumCPU() + self.getActiveCPU()
        if num_cpu > self.getMaxCPU():
            print("ERROR: shortage CPU")
            return
        else:
            self.instances.append(instance)
            self.setActiveCPU(num_cpu) 
        return

    def getInstances(self):
        return self.instances
    
    def getNumOfInstances(self):
        return len(self.instances)

    def addScaler(self, scaler):
        self.scaler = scaler
        return

    def getScaler(self):
        return self.scaler
    
    def registerInstance2Scaler(self, instance):
        self.scaler.addInstance(instance)
        return

    def addRequest(self, request: Request):
        self.getBalancer().addRequest(request)
        return