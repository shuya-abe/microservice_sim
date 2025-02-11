import numpy.random as rd
import math
from config import Config
from request import Request
from limit import Limit

class Sender:

    def __init__(self):
        self.reqs = []
        # self.step_per_time = step_per_time
        self.next_request_time = -1
        self.request_ptr = 0
        return
    
    def runStep(self, cluster, step, step_per_time):
        while self.request_ptr < self.countReqs() and self.getNextRequestTime() * step_per_time <= step:
            # id = self.getNumRequests()
            # workload = self.calculateWorkload4Request(step_per_time)
            # request = self.createRequest(id, workload, step)
            # cluster.addRequest(request)
            # self.incrementNumRequest()
            # time_next = self.calculateNextRequest(step, step_per_time)
            # self.setNextRequestTime(time_next)
            cluster.addRequest(self.reqs[self.request_ptr])
            # self.incrementNumRequest()
            self.request_ptr += 1
        return

    def countReqs(self):
        return len(self.reqs)
    
    def appendRequest(self, request):
        self.reqs.append(request)
        return
    
    def setRequests(self, reqs):
        self.reqs.extend(reqs)

    def getNumRequests(self):
        # return self.num_requests
        return len(self.reqs)
        
    def setNextRequestTime(self, time):
        self.next_request_time = time
    
    def getNextRequestTime(self):
        return self.reqs[self.request_ptr].getStartTime()
    
