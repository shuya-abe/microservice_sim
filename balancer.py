import numpy.random as rd
import math
from request import Request
from container import Container
from limit import Limit
from config import Config
from status import Status

class Balancer:
    # containers: list[Container] = []
    # requests: list[Request] = []
    # last_Container = -1

    def __init__(self):
        self.containers: list[Container] = []
        self.requests: list[Request] = []
        self.last_Container = -1
        return
    
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
    
    def addContainer(self, container: Container):
        # container.setId(len(self.getContainers()))
        self.containers.append(container)
        return
    
    def delContainer(self, container: Container):
        self.containers.remove(container)
        return
    
    def getContainer(self, i: int):
        return self.containers[i]
    
    def getContainers(self):
        return self.containers
    
    def getNumOfContainers(self):
        return len(self.containers)
    
    def clearContainers(self):
        self.containers.clear()
        return

    def isContainedContainer(self, container: Container):
        return container in self.containers

    def runStep(self):
        self.manageQueue()
        return

    def manageQueue(self):
        for req in self.getRequests():
            self.tryForward2Container(req)
        return
    
    def tryForward2Container(self, req):
        container = self.chooseContainer()
        if container:
            self.forward2Container(container, req)

    def chooseContainer(self):
        # round robin
        container = None
        if self.last_Container + 1 < len(self.getContainers()):
            next_container = self.last_Container + 1
        else:
            next_container = 0
        container = self.getContainer(next_container)
        # for container in self.getContainers():
        #     if container.getQueueLength() == 0:
        #         return container
        # return container
        return container

    def forward2Container(self, container: Container, req: Request):
        self.delRequest(req)
        req.setProcessedBy("container" + str(container.getId()))
        container.addRequest(req)
        self.last_Container = self.getContainers().index(container)
        return

    def delRequest(self, req:Request):
        self.requests.remove(req)
        return