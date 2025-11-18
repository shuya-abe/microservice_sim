import numpy.random as rd
import math
from config import Config
from request import Request
from limit import Limit
import csv

class Generator:

    def __init__(self, step_per_time, _lambda, mu, config:Config):
        self.config = config
        self.reqs = []
        self.step_per_time = step_per_time
        self._lambda = _lambda
        self.mu = mu
        # self.next_request_time = -1
        # self.request_ptr = 0
        return
    
    def outputRequests(self, outputfile):
        with open(outputfile, 'w', newline='') as f:
            writer = csv.writer(f)
            # writer.writerow(["id", "workload", "time"])
            for req in self.reqs:
                id = req.getId()
                workload = req.getOrgWorkload()
                time = req.getStartTime()
                writer.writerow([id, workload, time])
            f.flush()

    def inputRequests(self, inputfile):
        with open(inputfile, 'r', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                id = int(row[0])
                workload = float(row[1])
                time = float(row[2])
                request = self.createRequest(id, workload, time)
                self.reqs.append(request)
        return self.reqs

    def createAllRequests(self, limit, threshold):
        # self.setNumRequests(0)
        time = self.calculateNextRequest(0, self.step_per_time)
        # self.setNextRequestTime(timestep)

        if limit == Limit.LIMIT_DEFAULT:
            return
        elif limit == Limit.LIMIT_REQUEST:
            while(threshold > self.countReqs()):
                time = self.generateNextRequests(time)
        elif limit == Limit.LIMIT_TIMESTEP:
            while(threshold > time * self.step_per_time):
                time = self.generateNextRequests(time)
        elif limit == Limit.LIMIT_TIME:
           while(threshold > time):
                time = self.generateNextRequests(time)
        else:
            return
        
        return self.reqs
        
        # self.setNextRequestTime(-1)
        
    def generateNextRequests(self, time):
        id = self.getNumRequests()
        workload = self.calculateWorkload4Request(self.step_per_time)
        request = self.createRequest(id, workload, time)
        self.reqs.append(request)
        # self.incrementNumRequest()
        time_next = self.calculateNextRequest(time, self.step_per_time)
        # self.setNextRequestTime(time_next)
        return time_next

    def countReqs(self):
        return len(self.reqs)

    def createRequest(self, id, workload, time):
        request = Request(id, workload, time)
        return request

    def getNumRequests(self):
        # return self.num_requests
        return len(self.reqs)
        
    def setNextRequestTime(self, time):
        self.next_request_time = time
    
    # def getNextRequestTime(self):
    #     return self.reqs[self.request_ptr].getStartTime()
    
    def calculateNextRequest(self, time, step_per_time):
        scale = 1./self._lambda
        # step = max([1, math.ceil(rd.exponential(scale))])
        # step = math.ceil(rd.exponential(scale) * step_per_time)
        step = math.ceil(rd.exponential(scale) * step_per_time)
        # step = round(rd.exponential(scale))
        # step = math.floor(rd.exponential(scale))
        return time + step / step_per_time
    
    def calculateWorkload4Request(self, step_per_time):
        scale = 1./self.mu
        service_time = rd.exponential(scale)
        workload = self.config.CONFIG_DEFAULT_CAPACITY * service_time
        return workload