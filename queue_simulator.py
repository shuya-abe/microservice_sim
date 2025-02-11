import numpy.random as rd
import csv
import math
import time
from balancer import Balancer
from request import Request
from container import Container
from scaler import Scaler
from limit import Limit
from config import Config
from sim_flg import Flg
from cluster import Cluster
from generator import Generator
from sender import Sender
from status import Status
import datetime

class QueueSimulator:

    def __init__(self):
        return

    # def __init__(self, threshold, limit):
    #     self.clearAll()
    #     self.settingSimulate(threshold, limit)
    #     return
    
    def __init__(self, threshold, limit, step_per_time = Config.SIM_STEP_PER_TIME):
        self.clearAll()
        self.settingSimulate(threshold, limit, step_per_time)
        return
    
    def clearAll(self):
        self.sim_timer = -1
        self.limit = Limit.LIMIT_DEFAULT
        self.threshold = -1
        self.timestep = -1
        self.next_request_time = -1
        self.num_requests = -1
        self.reqs:list[Request] = []
        self.list_length = []
        self.list_is_process = []
        self.step_per_time = -1
        return
    
    def settingSimulate(self, threshold, limit, step_per_time = Config.SIM_STEP_PER_TIME):
        self.reqs.clear()
        self.list_length.clear()
        self.list_is_process.clear()

        self.addCluster(Cluster())
        balancer = Balancer()
        self.cluster.addBalancer(balancer)
        self.cluster.addScaler(Scaler(balancer))
        self.createContainers()

        generator = Generator(step_per_time)
        self.addGenerator(generator)

        sender = Sender()
        self.addSender(sender)

        self.setThreshold(threshold)
        self.setLimit(limit)
        self.setStepPerTime(step_per_time)
        self.setStep(0)

        # generator.setNumRequests(0)

        if Config.CONFIG_REQUEST_FLG == Flg.FLG_OUTPUT:
            reqs = generator.createAllRequests(limit, threshold)
            generator.outputRequests(Config.CONFIG_REQUEST_FILE)
        else:
            reqs = generator.inputRequests(Config.CONFIG_REQUEST_FILE)

        sender.setRequests(reqs)
        
        # time = generator.calculateNextRequest(0, step_per_time)
        # generator.setNextRequestTime(time)
        time = sender.reqs[0].getStartTime()
        sender.setNextRequestTime(time)
        self.next_request_time = time
        

        return
    
    def addGenerator(self, generator):
        self.generator = generator
        return
    
    def getGenerator(self):
        return self.generator

    def addSender(self, sender):
        self.sender = sender
        return
    
    def getSender(self):
        return self.sender

    def addCluster(self, cluster):
        self.cluster = cluster
        return

    def getCluster(self):
        return self.cluster
    
    def setStepPerTime(self, step_per_time):
        self.step_per_time = step_per_time
        return
    
    def getStepPerTime(self):
        return self.step_per_time
    
    def startSimulate(self):
        self.sim_timer = time.time()
        limit = self.getLimit()
        threshold = self.getThreshold()
        
        if Config.CONFIG_DEFAULT_FLG:
            outfile = Config.SIM_DEFAULT_SERVER_OUTPUT_FILE + "_num_container.csv"
        else:
            outfile = Config.SIM_OUTPUT_FILE + "_num_container.csv"
        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
        
            balancer = self.getCluster().getBalancer()
            before_containers = balancer.getNumOfContainers()
            
            if limit == Limit.LIMIT_DEFAULT:
                return
            elif limit == Limit.LIMIT_REQUEST:
                while(threshold > self.countReqs()):
                    self.simulateStep()
                    num_containers = balancer.getNumOfContainers()
                    if before_containers != num_containers:
                        writer.writerow([str(self.getStep()/self.getStepPerTime()), str(self.getStep()), num_containers])
                        before_containers = num_containers
            elif limit == Limit.LIMIT_TIMESTEP:
                while(threshold > self.getStep() or self.countReqs() < self.sender.countReqs()):
                    self.simulateStep()
                    num_containers = balancer.getNumOfContainers()
                    if before_containers != num_containers:
                        writer.writerow([str(self.getStep()/self.getStepPerTime()), str(self.getStep()), num_containers])
                        before_containers = num_containers
            elif limit == Limit.LIMIT_TIME:
                while(threshold > self.getTime() or self.countReqs() < self.sender.countReqs()):
                    self.simulateStep()
                    num_containers = balancer.getNumOfContainers()
                    if before_containers != num_containers:
                        writer.writerow([str(self.getStep()/self.getStepPerTime()), str(self.getStep()), num_containers])
                        before_containers = num_containers
            else:
                return

        return
    
    def simulateStep(self):
        sender = self.getSender()
        cluster = self.getCluster()
        balancer = cluster.getBalancer()
        scaler = cluster.getScaler()
        step = self.getStep()
        
        sender.runStep(cluster, step, self.step_per_time)
        balancer.runStep()
        scaler.runStep(step)
        list_length_step = []
        list_is_process_step = []
        for container in scaler.getContainers():
            reqs, length, is_process = container.runStep(step)
            self.registerReqs(reqs)
            list_length_step.append(length)
            list_is_process_step.append(is_process)
        self.list_length.append(list_length_step)
        self.list_is_process.append(list_is_process_step)
        self.incrementStep()
        
        return
    
    def endSimulate(self, flg):
        print("==SIMULATION FINISHED==")
        print("exec time (sec): %f" % (time.time() - self.sim_timer))
        self.outputConfig()
        total, total_wait = self.calcTotalTime(flg)
        return self.outputResult(total, total_wait)

    def outputConfig(self):
        print("---CONFIG---")

        print("mu: %f, lambda: %f" % (Config.CONFIG_MU, Config.CONFIG_LAMBDA))

        if Config.SIM_LIMIT == Limit.LIMIT_DEFAULT:
            print("Limit: DEFAULT")
        elif Config.SIM_LIMIT == Limit.LIMIT_REQUEST:
            print("Limit: Num of Requests")
        elif Config.SIM_LIMIT == Limit.LIMIT_TIMESTEP:
            print("Limit: Num of Timestep")
        elif Config.SIM_LIMIT == Limit.LIMIT_TIME:
            print("Limit: Time")
        else:
            print("Limit: OTHER")
        
        print("Threshold: " + str(Config.SIM_THRESHOLD))
        print("Steps / Time: " + str(self.getStepPerTime()))
        print("Default Container Capacity: " + str(Config.CONFIG_DEFAULT_CAPACITY))
        print("Default Container CPU: " + str(Config.CONFIG_DEFAULT_num_CPU))
        if Config.CONFIG_DEFAULT_QUEUE_LENGTH > 0:
            print("Default Queue Length: " + str(Config.CONFIG_DEFAULT_QUEUE_LENGTH))
        else:
            print("Default Queue Length: INF")
        
        print("--Container Config--")
        for container in self.getCluster().getContainers():
            if container.getMaxQueueLength() > 0:
                print("capacity: %d, num_CPU: %d, queue_length: %d" % (container.getCapacity() * self.step_per_time, container.getNumCPU(), container.getMaxQueueLength()))
            else:
                print("capacity: %d, num_CPU: %d, queue_length: INF" % (container.getCapacity() * self.step_per_time, container.getNumCPU()))
        
    def calcTotalTime(self, flg):
        if flg == Flg.FLG_VERBOSE:
            return self.calcTotalTimeVerbose()
        else:
            return self.calcTotalTimeSimple()

    def calcTotalTimeSimple(self):
        total = 0.
        total_wait = 0.
        for req in self.reqs:
            id, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
            total += time_lifetime
            total_wait += time_wait
        return total, total_wait

    def calcTotalTimeVerbose(self):
        total = 0.
        total_wait = 0.
        # print("---PACKET---")
        if Config.CONFIG_DEFAULT_FLG:
            outfile = Config.SIM_DEFAULT_SERVER_OUTPUT_FILE + "_container"
        else:
            outfile = Config.SIM_OUTPUT_FILE + "_container"
        with open(outfile + "_packet.csv", 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "processedBy", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
            for req in self.reqs:
                id, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
                processedBy = req.getProcessedBy()
                writer.writerow([id, processedBy, workload, start, end, time_lifetime, time_wait, time_lifetime - time_wait])
                total += time_lifetime
                total_wait += time_wait
                # print("ID: %d, WORKLOAD: %d, LIFETIMESTEP: %d -> %d: %d" % (id, workload, start, end, time_lifetime))
        return total, total_wait

    def calcResultPacket(self, req):
            step_per_time = self.getStepPerTime()
            id = req.getId()
            workload = req.getOrgWorkload()
            start = req.getStartTime()
            end = req.getEndTime()
            time_lifetime = req.getLifetime()
            time_wait = req.getWaitTime()
            return id, workload, start, end, time_lifetime, time_wait

    def outputResult(self, total, total_wait):
        balancer = self.cluster.getBalancer()
        # ideal_rho, ideal_time_wait, ideal_time_service, ideal_time_total = self.calcIdealResult()

        count_is_process = 0.
        for is_process_step in self.list_is_process:
            for is_process_container in is_process_step:
                if is_process_container:
                    count_is_process += 1

        num_reqs = len(self.reqs)
        num_steps = self.getStep()
        total_time = self.getTime()
        ex_time_service = (total - total_wait) / num_reqs
        ex_rho = count_is_process / (num_steps * len(balancer.getContainers()))
        ex_time_wait = total_wait/num_reqs
        ex_time_total = total/num_reqs

        print("---RESULT---")
        print("TOTAL SIM TIME: %d" % total_time)
        print("TOTAL SIM STEP: %d" % num_steps)
        print("TOTAL REQUEST: %d" % num_reqs)
        # print("RHO: (ideal) %f, (ex) %f" % (ideal_rho, ex_rho))
        # print("SERVICE TIME: (ideal) %f, (ex) %f" % (ideal_time_service, ex_time_service))
        # print("WAIT TIME: (ideal) %f, (ex) %f" % (ideal_time_wait, ex_time_wait))
        # print("Cluster TIME: (ideal) %f, (ex) %f" % (ideal_time_total, ex_time_total))
        print("RHO: (ex) %f" % (ex_rho))
        print("SERVICE TIME: (ex) %f" % (ex_time_service))
        print("WAIT TIME: (ex) %f" % (ex_time_wait))
        print("Cluster TIME: (ex) %f" % (ex_time_total))

        with open(Config.SIM_DEFAULT_OUTPUT_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.datetime.now(), Config.CONFIG_REQUEST_FILE, len(self.cluster.getContainers()), Config.CONFIG_DEFAULT_CAPACITY, Config.CONFIG_DEFAULT_num_CPU, self.step_per_time, total_time, num_steps, num_reqs, ex_rho, ex_time_service, ex_time_wait, ex_time_total])

        # datetime,lambda,mu,servers,step_per_time,total_time,num_steps,num_reqs, ex_rho, ex_time_service, ex_time_wait, ex_time_total
        
        # return [total_time, num_steps, num_reqs, ideal_rho, ex_rho, ideal_time_service, ex_time_service, ideal_time_wait, ex_time_wait, ideal_time_total, ex_time_total]
        return [total_time, num_steps, num_reqs, ex_rho, ex_time_service, ex_time_wait, ex_time_total]
    
    def registerReqs(self, reqs):
        self.reqs.extend(reqs)

    def countReqs(self):
        return len(self.reqs)
    
    def setLimit(self, limit):
        self.limit = limit
    
    def getLimit(self):
        return self.limit
    
    def setThreshold(self, threshold):
        self.threshold = threshold
    
    def getThreshold(self):
        return self.threshold
    
    def setStep(self, time):
        self.timestep = time
    
    def incrementStep(self):
        self.timestep += 1

    def getStep(self):
        return self.timestep
    
    def getTime(self):
        return self.timestep / self.getStepPerTime()

    def getNumRequests(self):
        return self.num_requests
    
    def createContainer(self, capacity = Config.CONFIG_DEFAULT_CAPACITY, num_CPU = Config.CONFIG_DEFAULT_num_CPU, queue_length = Config.CONFIG_DEFAULT_QUEUE_LENGTH, status = Config.CONFIG_DEFAULT_STATUS):
        container = Container(capacity, num_CPU, queue_length, status)
        return container
    
    def createContainers(self):
        cluster = self.getCluster()

        if Config.CONFIG_DEFAULT_FLG == True:
            if Config.CONFIG_DEFAULT_NUM <= 0:
                print("ERROR: Default FLG is True, but # of instance is wrong.")
            capacity = Config.CONFIG_DEFAULT_CAPACITY
            num_CPU = Config.CONFIG_DEFAULT_num_CPU
            queue_length = Config.CONFIG_DEFAULT_QUEUE_LENGTH
            status = Config.CONFIG_DEFAULT_STATUS
            
            container = self.createContainer(capacity, num_CPU, queue_length, Status.ACTIVE)
            container.setId(0)
            cluster.addContainer(container)
            cluster.registerContainer2Scaler(container)
            
            for i in range(1,Config.CONFIG_DEFAULT_NUM):
                container = self.createContainer(capacity, num_CPU, queue_length, status)
                container.setId(i)
                cluster.addContainer(container)
                cluster.registerContainer2Scaler(container)
        else:
            for i, container_conf in enumerate(Config.CONFIG_CONTAINERS):
                capacity, num_CPU, queue_length, status = container_conf
                container = self.createContainer(capacity, num_CPU, queue_length, status)
                container.setId(i)
                cluster.addContainer(container)
                cluster.registerContainer2Scaler(container)
        return