import csv
import time
from balancer import Balancer
from request import Request
from instance import Instance
from scaler import Scaler
from limit import Limit
from config import Config
from sim_flg import Flg
from cluster import Cluster
from generator import Generator
from sender import Sender
from status import Status
from container import Container
from serverless import Serverless
import datetime
import os

class QueueSimulator:

    def __init__(self, threshold, limit, step_per_time, _lambda, mu, config):
        self.clearAll()
        self.settingSimulate(threshold, limit, step_per_time, _lambda, mu, config)
        return
    
    def clearAll(self):
        self.sim_timer = -1
        self.limit = Limit.LIMIT_DEFAULT
        self.threshold = -1
        self.timestep = -1
        self.next_request_time = -1
        self.num_requests = -1
        self.reqs:list[Request] = []
        # self.list_length = []
        # self.list_is_process = []
        self.step_per_time = -1
        self._lambda = None
        self.mu = None
        self.total = 0
        self.total_wait = 0
        return
    
    def settingSimulate(self, threshold, limit, step_per_time, _lambda, mu, config:Config):
        self._lambda = _lambda
        self.mu = mu
        self.config = config
        self.reqs.clear()
        # self.list_length.clear()
        # self.list_is_process.clear()
        self.num_reqs = 0
        
        self.mode = self.config.CONFIG_INSTANCE_FLG

        self.addCluster(Cluster(config))
        balancer = Balancer(config)
        self.cluster.addBalancer(balancer)
        scaler = Scaler(balancer, config)
        self.cluster.addScaler(scaler)
        balancer.setScaler(scaler)
        self.createInstances()

        generator = Generator(step_per_time, _lambda, mu, config)
        self.addGenerator(generator)

        sender = Sender()
        self.addSender(sender)

        self.setThreshold(threshold)
        self.setLimit(limit)
        self.setStepPerTime(step_per_time)
        self.setStep(0)
        
        self.CONFIG_REQUEST_FILE = config.CONFIG_REQUEST_FILE
        
        # if (limit == Limit.LIMIT_TIME):
        #     self.CONFIG_REQUEST_FILE = "./requests/" + str(threshold) + "sec" + "_lambda" + str(_lambda) + "_mu" + str(mu) + ".csv"
        # elif (limit == Limit.LIMIT_TIMESTEP):
        #     self.CONFIG_REQUEST_FILE = "./requests/" + str(threshold) + "step" + "_lambda" + str(_lambda) + "_mu" + str(mu) + ".csv"
        # elif (limit == Limit.LIMIT_REQUEST):
        #     self.CONFIG_REQUEST_FILE = "./requests/" + str(threshold) + "reqs" + "_lambda" + str(_lambda) + "_mu" + str(mu) + ".csv"
        # else:
        #     self.CONFIG_REQUEST_FILE = "./requests/" + str(threshold) + "sec" + "_lambda" + str(_lambda) + "_mu" + str(mu) + ".csv"

        if os.path.isfile(self.CONFIG_REQUEST_FILE):
            reqs = generator.inputRequests(self.CONFIG_REQUEST_FILE)
        else:
            reqs = generator.createAllRequests(limit, threshold)
            generator.outputRequests(self.CONFIG_REQUEST_FILE)

        sender.setRequests(reqs, step_per_time)

        time = sender.reqs[0].getStartTime()
        sender.setNextRequestTime(time)
        self.next_request_time = time
        
        outfile = self.config.OUTPUT_FILE_PACKET
        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "processedBy", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
        
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
        
        outfile = self.config.OUTPUT_FILE_NUM_INSTANCE
        
        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
        
            # balancer = self.getCluster().getBalancer()
            # before_instances = balancer.getNumOfInstances()
            before_instances = -1
            
            if limit == Limit.LIMIT_DEFAULT:
                return
            elif limit == Limit.LIMIT_REQUEST:
                while(threshold > self.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
                    f.flush()
            elif limit == Limit.LIMIT_TIMESTEP:
                while(threshold > self.getStep() or self.countReqs() < self.sender.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
                    f.flush()
            elif limit == Limit.LIMIT_TIME:
                while(threshold > self.getTime() or self.countReqs() < self.sender.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
                    f.flush()
            else:
                return

        return
    
    def simulateStepWrapper(self, writer, before_instances):
        self.simulateStep()
        # num_instances = balancer.getNumOfInstances()
        num_instances = self.getNumOfHotInstance()
        step = self.getStep()
        simtime = step / self.getStepPerTime()
        if before_instances != num_instances:
            writer.writerow([str(simtime), str(step), num_instances])
            before_instances = num_instances
        self.incrementStep()
        return num_instances
    
    def getNumOfHotInstance(self):
        scaler = self.getCluster().getScaler()
        num = 0
        for instance in scaler.getInstances():
            status = instance.getStatus()
            if status == Status.ACTIVE or status == Status.WORKING:
                num += 1
        return num
    
    def simulateStep(self):
        sender = self.getSender()
        cluster = self.getCluster()
        balancer = cluster.getBalancer()
        scaler = cluster.getScaler()
        step = self.getStep()
        
        sender.runStep(cluster, step, self.step_per_time)
        balancer.runStep()
        scaler.runStep(step)
        # list_length_step = []
        # list_is_process_step = []
        for instance in scaler.getInstances():
            reqs, length, is_process = instance.runStep(step)
            self.registerReqs(reqs)
        #     list_length_step.append(length)
        #     list_is_process_step.append(is_process)
        # self.list_length.append(list_length_step)
        # self.list_is_process.append(list_is_process_step)
        
        return
    
    def endSimulate(self, flg):
        print("==SIMULATION FINISHED==")
        print("exec time (sec): %f" % (time.time() - self.sim_timer))
        self.outputConfig()
        total, total_wait = self.calcTotalTimeVerbose()
        return self.outputResult(total, total_wait)

    def outputConfig(self):
        print("---CONFIG---")

        print("mu: %f, lambda: %f" % (self.mu, self._lambda))

        if self.config.SIM_LIMIT == Limit.LIMIT_DEFAULT:
            print("Limit: DEFAULT")
        elif self.config.SIM_LIMIT == Limit.LIMIT_REQUEST:
            print("Limit: Num of Requests")
        elif self.config.SIM_LIMIT == Limit.LIMIT_TIMESTEP:
            print("Limit: Num of Timestep")
        elif self.config.SIM_LIMIT == Limit.LIMIT_TIME:
            print("Limit: Time")
        else:
            print("Limit: OTHER")
        
        print("Threshold: " + str(self.config.SIM_THRESHOLD))
        print("Steps / Time: " + str(self.getStepPerTime()))
        print("Default Instance Capacity: " + str(self.config.CONFIG_DEFAULT_CAPACITY))
        print("Default Instance CPU: " + str(self.config.CONFIG_DEFAULT_num_CPU))
        if self.config.CONFIG_DEFAULT_QUEUE_LENGTH > 0:
            print("Default Queue Length: " + str(self.config.CONFIG_DEFAULT_QUEUE_LENGTH))
        else:
            print("Default Queue Length: INF")
        
        # print("--Instance Config--")
        # for instance in self.getCluster().getInstances():
        #     if instance.getMaxQueueLength() > 0:
        #         print("capacity: %d, num_CPU: %d, queue_length: %d" % (instance.getCapacity() * self.step_per_time, instance.getNumCPU(), instance.getMaxQueueLength()))
        #     else:
        #         print("capacity: %d, num_CPU: %d, queue_length: INF" % (instance.getCapacity() * self.step_per_time, instance.getNumCPU()))
        
    # def calcTotalTime(self, flg):
    #     if flg == Flg.FLG_VERBOSE:
    #         return self.calcTotalTimeVerbose()
    #     else:
    #         return self.calcTotalTimeSimple()

    # def calcTotalTimeSimple(self):
    #     total = 0.
    #     total_wait = 0.
    #     for req in self.reqs:
    #         id, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
    #         total += time_lifetime
    #         total_wait += time_wait
    #     return total, total_wait

    def calcTotalTimeVerbose(self):
        total = 0.
        total_wait = 0.
        # print("---PACKET---")
        outfile = self.config.OUTPUT_FILE_PACKET
        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "processedBy", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
            for req in self.reqs:
                id, processedBy, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
                writer.writerow([id, processedBy, workload, start, end, time_lifetime, time_wait, time_lifetime - time_wait])
                total += time_lifetime
                total_wait += time_wait
            f.flush()
        return total, total_wait

    def calcResultPacket(self, req):
            id = req.getId()
            processedBy = req.getProcessedBy()
            workload = req.getOrgWorkload()
            start = req.getStartTime()
            end = req.getEndTime()
            time_lifetime = req.getLifetime()
            time_wait = req.getWaitTime()
            return id, processedBy, workload, start, end, time_lifetime, time_wait

    def outputResult(self, total, total_wait):
        balancer = self.cluster.getBalancer()

        # count_is_process = 0.
        # for is_process_step in self.list_is_process:
        #     for is_process_instance in is_process_step:
        #         if is_process_instance:
        #             count_is_process += 1

        # num_reqs = len(self.reqs)
        num_reqs = self.countReqs()
        num_steps = self.getStep()
        total_time = self.getTime()
        ex_time_service = (total - total_wait) / num_reqs
        # ex_rho = count_is_process / (num_steps * len(balancer.getInstances()))
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
        # print("RHO: (ex) %f" % (ex_rho))
        print("SERVICE TIME: (ex) %f" % (ex_time_service))
        print("WAIT TIME: (ex) %f" % (ex_time_wait))
        print("Cluster TIME: (ex) %f" % (ex_time_total))


        with open(self.config.SIM_DEFAULT_OUTPUT_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.datetime.now(), self.CONFIG_REQUEST_FILE, self.config.CONFIG_LAMBDA, self.config.CONFIG_MU, len(self.cluster.getInstances()), self.config.CONFIG_DEFAULT_CAPACITY, self.config.CONFIG_DEFAULT_num_CPU, self.step_per_time, total_time, num_steps, num_reqs, ex_time_service, ex_time_wait, ex_time_total])

        return [total_time, num_steps, num_reqs, ex_time_service, ex_time_wait, ex_time_total]
    
    def registerReqs(self, reqs):
        self.reqs.extend(reqs)
        
        # outfile = self.config.OUTPUT_FILE_PACKET
        # with open(outfile, 'a', newline='') as f:
        #     writer = csv.writer(f)
        #     # writer.writerow(["id", "processedBy", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
        #     for req in reqs:
        #         id, processedBy, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
        #         writer.writerow([id, processedBy, workload, start, end, time_lifetime, time_wait, time_lifetime - time_wait])
        #         self.total += time_lifetime
        #         self.total_wait += time_wait
        #         self.num_reqs += 1
        #     f.flush()


    def countReqs(self):
        return len(self.reqs)
        # return self.num_reqs
    
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
        return self.num_reqs
    
    def createInstance(self, capacity, num_CPU, queue_length, status):
        if self.mode == Flg.FLG_CONTAINER:
            instance = Container(capacity, num_CPU, queue_length, status, self.config)
        elif self.mode == Flg.FLG_SERVERLESS:
            instance = Serverless(capacity, num_CPU, queue_length, status, self.config)
        return instance
    
    def createInstances(self):
        cluster = self.getCluster()

        if self.config.CONFIG_DEFAULT_FLG == True:
            if self.config.CONFIG_DEFAULT_NUM <= 0:
                print("ERROR: Default FLG is True, but # of instance is wrong.")
            capacity = self.config.CONFIG_DEFAULT_CAPACITY
            num_CPU = self.config.CONFIG_DEFAULT_num_CPU
            queue_length = self.config.CONFIG_DEFAULT_QUEUE_LENGTH
            status = self.config.CONFIG_DEFAULT_STATUS
            
            start = 0
            if self.mode == Flg.FLG_CONTAINER:
                instance = self.createInstance(capacity, num_CPU, queue_length, Status.ACTIVE)
                instance.setId(0)
                cluster.addInstance(instance)
                cluster.registerInstance2Scaler(instance)
                start += 1
            
            for i in range(start,self.config.CONFIG_DEFAULT_NUM):
                instance = self.createInstance(capacity, num_CPU, queue_length, status)
                instance.setId(i)
                if not cluster.addInstance(instance):
                    break
                cluster.registerInstance2Scaler(instance)

        else:
            for i, instance_conf in enumerate(self.config.CONFIG_INSTANCES):
                capacity, num_CPU, queue_length, status = instance_conf
                instance = self.createInstance(capacity, num_CPU, queue_length, status)
                instance.setId(i)
                if not cluster.addInstance(instance):
                    break
                cluster.registerInstance2Scaler(instance)
        return