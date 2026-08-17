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
from steady_state import (
    BatchAccumulator,
    consecutive_stable,
    merge_batches,
    _z_from_ci_level,
)
import datetime
import os
import math

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
        self.enable_hybrid_skip = bool(getattr(self.config, "SIM_ENABLE_HYBRID_SKIP", True))
        self.enable_scale_check_skip = bool(getattr(self.config, "SIM_ENABLE_SCALE_CHECK_SKIP", True))
        self.steady_enabled = bool(getattr(self.config, "STEADY_ENABLED", False))
        self.steady_batches = []
        self.steady_acc = None
        self.steady_result = None
        self.steady_reached = False
        self.steady_z = _z_from_ci_level(float(getattr(self.config, "STEADY_CI_LEVEL", 0.95)))
        self._packet_streamed = False
        self.num_reqs = 0

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

        # Shared arrival stream: same (threshold, λ, μ, sim_index) file is reused
        # across system configs. Steady mode may later append extra rows to it.
        if os.path.isfile(self.CONFIG_REQUEST_FILE):
            generator.inputRequests(self.CONFIG_REQUEST_FILE)
        else:
            generator.createAllRequests(limit, threshold)
            generator.outputRequests(self.CONFIG_REQUEST_FILE)

        for req in generator.reqs:
            req.setStartTime(math.ceil(req.getStartTime() * step_per_time) / step_per_time)
        sender.reqs = generator.reqs

        if sender.reqs:
            time0 = sender.reqs[0].getStartTime()
            sender.setNextRequestTime(time0)
            self.next_request_time = time0
        
        outfile = self.config.OUTPUT_FILE_PACKET
        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "processed_by", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
        
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
            writer.writerow(["sim_time", "step", "num_hot_instances"])
        
            before_instances = -1

            if self.steady_enabled:
                self._startSimulateSteady(writer, before_instances)
            elif limit == Limit.LIMIT_DEFAULT:
                return
            elif limit == Limit.LIMIT_REQUEST:
                while(threshold > self.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
            elif limit == Limit.LIMIT_TIMESTEP:
                while(threshold > self.getStep() or self.countReqs() < self.sender.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
            elif limit == Limit.LIMIT_TIME:
                while(threshold > self.getTime() or self.countReqs() < self.sender.countReqs()):
                    before_instances = self.simulateStepWrapper(writer, before_instances)
            else:
                return

        return

    def _startSimulateSteady(self, writer, before_instances):
        batch_reqs = int(self.config.STEADY_BATCH_REQS)
        batch_min_time = float(self.config.STEADY_BATCH_MIN_TIME)
        max_batches = int(self.config.STEADY_MAX_BATCHES)
        consecutive = int(self.config.STEADY_CONSECUTIVE)
        rel_tol = float(self.config.STEADY_REL_TOL)

        sim_time = self.getTime()
        hot = self.getNumOfHotInstance()
        self.steady_acc = BatchAccumulator(t0=sim_time)
        self.steady_acc.note_instances(sim_time, hot)
        self.steady_batches = []
        self.steady_reached = False

        while True:
            before_instances = self.simulateStepWrapper(writer, before_instances)
            sim_time = self.getTime()
            hot = before_instances
            self.steady_acc.note_instances(sim_time, hot)

            if (
                self.steady_acc.lifetimes.n >= batch_reqs
                and (sim_time - self.steady_acc.t0) >= batch_min_time
            ):
                batch = self.steady_acc.finalize(sim_time, self.steady_z)
                self.steady_batches.append(batch)
                batch_idx = len(self.steady_batches)
                emitted = False
                try:
                    from worker_progress import emit_progress

                    emitted = emit_progress(
                        {
                            "type": "steady_batch",
                            "sim_index": getattr(self.config, "TASK_SIM_INDEX", None),
                            "config_index": getattr(self.config, "TASK_CONFIG_INDEX", None),
                            "batch": batch_idx,
                            "n": int(batch["n"]),
                            "elapsed": float(batch["elapsed"]),
                            "ex_time_total": float(batch["ex_time_total"]),
                            "ex_time_wait": float(batch["ex_time_wait"]),
                            "ave_instances": float(batch["ave_instances"]),
                            "lambda": float(self._lambda),
                            "mu": float(self.mu),
                        }
                    )
                except Exception:
                    emitted = False
                if not emitted:
                    print(
                        f"[steady] batch={batch_idx} n={batch['n']} "
                        f"elapsed={batch['elapsed']:.3f} "
                        f"total={batch['ex_time_total']:.6g} wait={batch['ex_time_wait']:.6g} "
                        f"instances={batch['ave_instances']:.4g}",
                        flush=True,
                    )

                if consecutive_stable(self.steady_batches, consecutive, rel_tol):
                    self.steady_reached = True
                    self.steady_result = merge_batches(
                        self.steady_batches[-consecutive:], self.steady_z
                    )
                    break

                if len(self.steady_batches) >= max_batches:
                    self.steady_reached = False
                    k = min(consecutive, len(self.steady_batches))
                    self.steady_result = merge_batches(self.steady_batches[-k:], self.steady_z)
                    break

                self.steady_acc = BatchAccumulator(t0=sim_time)
                self.steady_acc.note_instances(sim_time, hot)

    def ensureOnlineArrivals(self, until_logical_time=None):
        if not self.steady_enabled:
            return
        generator = self.getGenerator()
        sender = self.getSender()
        if until_logical_time is None:
            until_logical_time = self.getTime() + max(
                float(self.config.STEADY_BATCH_MIN_TIME) * 0.1,
                10.0 / max(self._lambda, 1e-12),
            )

        if sender.reqs and sender.reqs[-1].getStartTime() >= until_logical_time:
            return

        added = generator.extendUntil(self.CONFIG_REQUEST_FILE, until_logical_time)
        for req in added:
            req.setStartTime(
                math.ceil(req.getStartTime() * self.step_per_time) / self.step_per_time
            )
        if sender.reqs is not generator.reqs:
            already_sent = sender.request_ptr
            sender.reqs = generator.reqs
            sender.request_ptr = min(already_sent, len(sender.reqs))

        # Drop already-dispatched arrivals to bound memory (the CSV stays complete).
        if sender.request_ptr > 10000:
            del sender.reqs[:sender.request_ptr]
            sender.request_ptr = 0

    def simulateStepWrapper(self, writer, before_instances):
        if self.steady_enabled:
            self.ensureOnlineArrivals()
        if self.enable_hybrid_skip:
            self.fastForwardIdleSteps()
        self.simulateStep()
        num_instances = self.getNumOfHotInstance()
        step = self.getStep()
        simtime = step / self.getStepPerTime()
        if before_instances != num_instances:
            writer.writerow([str(simtime), str(step), num_instances])
            before_instances = num_instances
        self.incrementStep()
        return num_instances

    def fastForwardIdleSteps(self):
        if self.steady_enabled:
            # Generate far enough for the next hybrid-skip horizon.
            self.ensureOnlineArrivals(self.getTime() + float(self.config.STEADY_BATCH_MIN_TIME))
        step = self.getStep()
        if self.hasImmediateEvent(step):
            return

        next_event_step = self.getNextEventStep(step)
        if next_event_step is None or next_event_step <= step:
            return

        skip_steps = next_event_step - step
        self.advanceBusyWork(skip_steps)
        self.timestep += skip_steps

    def hasImmediateEvent(self, step):
        sender = self.getSender()
        scaler = self.getCluster().getScaler()
        balancer = self.getCluster().getBalancer()

        next_arrival = self.getNextArrivalStep()
        if next_arrival is not None and next_arrival <= step:
            return True

        if balancer.getRequests():
            # Warm-wait may intentionally keep requests queued; only treat as
            # immediate when an assign/cold-start can happen this step.
            if self.mode == Flg.FLG_SERVERLESS_WARM_WAIT:
                if balancer.hasAssignableOrScalableWork():
                    return True
            else:
                return True

        if self.mode == Flg.FLG_CONTAINER and scaler.isTime2Check(step):
            if not self.enable_scale_check_skip or scaler.containerScaleCheckNeeded():
                return True

        serverless_idle_steps = self.config.CONFIG_SERVERLESS_TIMER * self.config.SIM_STEP_PER_TIME
        defer_idle = (
            self.mode == Flg.FLG_SERVERLESS_WARM_WAIT
            and bool(balancer.getRequests())
        )
        for instance in scaler.getRunnableInstances():
            status = instance.getStatus()

            if status == Status.SETUP:
                if isinstance(instance, Serverless):
                    if instance.setuptimer <= 1:
                        return True
                elif instance.setuptimer <= 0:
                    return True

            if status == Status.SHUTDOWN and instance.deactivatetimer <= 0:
                return True

            if status != Status.ACTIVE and status != Status.WORKING:
                continue

            exec_queue = instance.exec_queue
            queue = instance.queue

            if queue and any(slot is None for slot in exec_queue):
                return True

            for req in exec_queue:
                if req is not None and req.workload <= 0:
                    return True

            if Flg.is_serverless(self.mode) and status == Status.ACTIVE and not defer_idle:
                if step - instance.getLastTime() >= serverless_idle_steps:
                    return True

        return False

    def getNextArrivalStep(self):
        sender = self.getSender()
        if sender.request_ptr < sender.countReqs():
            time_start = sender.reqs[sender.request_ptr].getStartTime()
            return int(round(time_start * self.step_per_time))
        if self.steady_enabled:
            generator = self.getGenerator()
            next_t = generator.next_arrival_time
            if next_t is None:
                last = generator.last_start_time
                if last is None:
                    return None
                return int(round(last * self.step_per_time)) + 1
            return int(round(next_t * self.step_per_time))
        return None
    def getNextEventStep(self, step):
        scaler = self.getCluster().getScaler()
        candidates = []

        next_arrival = self.getNextArrivalStep()
        if next_arrival is not None and next_arrival > step:
            candidates.append(next_arrival)

        if self.mode == Flg.FLG_CONTAINER:
            interval = self.config.CONFIG_SCALE_INTERVAL * self.config.SIM_STEP_PER_TIME
            if interval > 0 and (
                not self.enable_scale_check_skip or scaler.containerScaleCheckNeeded()
            ):
                rem = step % interval
                next_check = step + (interval - rem)
                if rem == 0:
                    next_check = step + interval
                candidates.append(next_check)

        serverless_idle_steps = self.config.CONFIG_SERVERLESS_TIMER * self.config.SIM_STEP_PER_TIME
        defer_idle = (
            self.mode == Flg.FLG_SERVERLESS_WARM_WAIT
            and bool(self.getCluster().getBalancer().getRequests())
        )

        for instance in scaler.getRunnableInstances():
            status = instance.getStatus()

            if status == Status.SETUP:
                if isinstance(instance, Serverless):
                    candidate = step + max(1, instance.setuptimer - 1)
                else:
                    candidate = step + max(1, instance.setuptimer)
                candidates.append(candidate)
                continue

            if status == Status.SHUTDOWN:
                candidates.append(step + max(1, instance.deactivatetimer))
                continue

            if status != Status.ACTIVE and status != Status.WORKING:
                continue

            if Flg.is_serverless(self.mode) and status == Status.ACTIVE and not defer_idle:
                deactivate_step = instance.getLastTime() + serverless_idle_steps
                if deactivate_step > step:
                    candidates.append(deactivate_step)

            for req in instance.exec_queue:
                if req is None:
                    continue
                if req.workload <= 0:
                    candidates.append(step)
                    continue
                processing_steps = int(math.ceil(req.workload / instance.processing_capacity))
                candidates.append(step + processing_steps)

        if not candidates:
            return None
        return min(candidates)

    def advanceBusyWork(self, skip_steps):
        if skip_steps <= 0:
            return

        step = self.getStep()
        scaler = self.getCluster().getScaler()
        for instance in scaler.getRunnableInstances():
            status = instance.getStatus()
            if status == Status.SETUP:
                instance.setuptimer -= skip_steps
                continue

            if status == Status.SHUTDOWN:
                instance.deactivatetimer -= skip_steps
                continue

            if status != Status.ACTIVE and status != Status.WORKING:
                continue

            busy_slots = 0
            for req in instance.exec_queue:
                if req is None:
                    continue
                if req.workload > 0:
                    req.workload -= instance.processing_capacity * skip_steps
                    busy_slots += 1

            if busy_slots > 0:
                instance.CpuCtr += busy_slots * skip_steps
                if Flg.is_serverless(self.mode):
                    instance.setLastTime(step + skip_steps - 1)
    
    def getNumOfHotInstance(self):
        scaler = self.getCluster().getScaler()
        num = 0
        for instance in scaler.getRunnableInstances():
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
        for instance in tuple(scaler.getRunnableInstances()):
            reqs = instance.runStep(step)
            self.registerReqs(reqs)
        #     list_length_step.append(length)
        #     list_is_process_step.append(is_process)
        # self.list_length.append(list_length_step)
        # self.list_is_process.append(list_is_process_step)
        
        return
    
    def endSimulate(self, flg):
        import time as wall_time
        print("==SIMULATION FINISHED==")
        print("exec time (sec): %f" % (wall_time.time() - self.sim_timer))
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
        outfile = self.config.OUTPUT_FILE_PACKET

        # Steady mode already streams packet rows during registerReqs.
        if self.steady_enabled and getattr(self, "_packet_streamed", False):
            return total, total_wait

        with open(outfile, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "processed_by", "workload", "start", "end", "time_lifetime", "time_wait", "time_service"])
            for req in self.reqs:
                id, processedBy, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
                writer.writerow([id, processedBy, workload, start, end, time_lifetime, time_wait, time_lifetime - time_wait])
                total += time_lifetime
                total_wait += time_wait
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
        num_reqs = self.countReqs()
        num_steps = self.getStep()
        total_time = self.getTime()

        if self.steady_enabled and self.steady_result is not None:
            sr = self.steady_result
            ex_time_service = sr["ex_time_service"]
            ex_time_wait = sr["ex_time_wait"]
            ex_time_total = sr["ex_time_total"]
            steady_reached = self.steady_reached
            num_batches = len(self.steady_batches)
            steady_batch_index = num_batches
            steady_start = sr["t0"]
            steady_end = sr["t1"]
            ci_total_low = sr["ci_total_low"]
            ci_total_high = sr["ci_total_high"]
            ci_wait_low = sr["ci_wait_low"]
            ci_wait_high = sr["ci_wait_high"]
            ci_service_low = sr["ci_service_low"]
            ci_service_high = sr["ci_service_high"]
            ave_instances_steady = sr["ave_instances"]
            # Report completions that contributed to the adopted steady window.
            reported_reqs = sr["n"]
        else:
            if num_reqs <= 0:
                ex_time_service = float("nan")
                ex_time_wait = float("nan")
                ex_time_total = float("nan")
            else:
                ex_time_service = (total - total_wait) / num_reqs
                ex_time_wait = total_wait / num_reqs
                ex_time_total = total / num_reqs
            steady_reached = False
            num_batches = 0
            steady_batch_index = 0
            steady_start = float("nan")
            steady_end = float("nan")
            ci_total_low = float("nan")
            ci_total_high = float("nan")
            ci_wait_low = float("nan")
            ci_wait_high = float("nan")
            ci_service_low = float("nan")
            ci_service_high = float("nan")
            ave_instances_steady = float("nan")
            reported_reqs = num_reqs

        print("---RESULT---")
        print("TOTAL SIM TIME: %s" % total_time)
        print("TOTAL SIM STEP: %d" % num_steps)
        print("TOTAL REQUEST: %d" % (self.num_reqs if self.steady_enabled else num_reqs))
        if self.steady_enabled:
            print("STEADY REACHED: %s (batches=%d)" % (steady_reached, num_batches))
            print("STEADY WINDOW: [%s, %s]" % (steady_start, steady_end))
            print("STEADY AVE INSTANCES: %s" % (ave_instances_steady,))
        print("SERVICE TIME: (ex) %f" % (ex_time_service))
        print("WAIT TIME: (ex) %f" % (ex_time_wait))
        print("Cluster TIME: (ex) %f" % (ex_time_total))

        result_row = [
            self.step_per_time,
            total_time,
            num_steps,
            reported_reqs if self.steady_enabled else num_reqs,
            ex_time_service,
            ex_time_wait,
            ex_time_total,
            bool(self.steady_enabled),
            bool(steady_reached),
            num_batches,
            steady_batch_index,
            steady_start,
            steady_end,
            ci_total_low,
            ci_total_high,
            ci_wait_low,
            ci_wait_high,
            ci_service_low,
            ci_service_high,
            ave_instances_steady,
        ]

        summary_row = [
            datetime.datetime.now(),
            self.CONFIG_REQUEST_FILE,
            self.config.CONFIG_LAMBDA,
            self.config.CONFIG_MU,
            len(self.cluster.getInstances()),
            self.config.CONFIG_DEFAULT_CAPACITY,
            self.config.CONFIG_DEFAULT_num_CPU,
            self.step_per_time,
            total_time,
            num_steps,
            reported_reqs if self.steady_enabled else num_reqs,
            ex_time_service,
            ex_time_wait,
            ex_time_total,
            bool(self.steady_enabled),
            bool(steady_reached),
            num_batches,
            steady_batch_index,
            steady_start,
            steady_end,
            ci_total_low,
            ci_total_high,
            ci_wait_low,
            ci_wait_high,
            ci_service_low,
            ci_service_high,
            ave_instances_steady,
        ]

        return {
            "result": result_row[1:],  # legacy-ish without step_per_time for older callers
            "result_row": result_row,
            "summary_output_file": self.config.SIM_DEFAULT_OUTPUT_FILE,
            "summary_row": summary_row,
        }
    
    def registerReqs(self, reqs):
        if self.steady_enabled:
            self._packet_streamed = True
            outfile = self.config.OUTPUT_FILE_PACKET
            with open(outfile, 'a', newline='') as f:
                writer = csv.writer(f)
                for req in reqs:
                    id, processedBy, workload, start, end, time_lifetime, time_wait = self.calcResultPacket(req)
                    writer.writerow([
                        id, processedBy, workload, start, end,
                        time_lifetime, time_wait, time_lifetime - time_wait,
                    ])
                    self.num_reqs += 1
                    if self.steady_acc is not None:
                        self.steady_acc.add_completion(
                            time_lifetime, time_wait, time_lifetime - time_wait
                        )
            return

        self.reqs.extend(reqs)
        if self.steady_acc is not None:
            for req in reqs:
                lifetime = req.getLifetime()
                wait = req.getWaitTime()
                self.steady_acc.add_completion(lifetime, wait, lifetime - wait)

    def countReqs(self):
        if self.steady_enabled:
            return int(self.num_reqs)
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
        return self.num_reqs
    
    def createInstance(self, capacity, num_CPU, queue_length, status):
        if self.mode == Flg.FLG_CONTAINER:
            instance = Container(capacity, num_CPU, queue_length, status, self.config)
        elif Flg.is_serverless(self.mode):
            instance = Serverless(capacity, num_CPU, queue_length, status, self.config)
        else:
            raise ValueError("Unsupported instance mode")
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

            default_start_instances = getattr(
                self.config,
                "CONFIG_DEFAULT_START_INSTANCES",
                1 if self.mode == Flg.FLG_CONTAINER else 0,
            )
            default_start_instances = max(0, min(int(default_start_instances), self.config.CONFIG_DEFAULT_NUM))

            # Stagger serverless idle timers across initially ACTIVE instances.
            # last_time is in steps (same unit as timestep). Idle age of the k-th
            # starter (k=0..n-1) is k*τ/n, so last_time = -k*τ_steps/n (may be < 0).
            serverless_timer_steps = (
                self.config.CONFIG_SERVERLESS_TIMER * self.config.SIM_STEP_PER_TIME
                if Flg.is_serverless(self.mode) and default_start_instances > 0
                else None
            )

            for i in range(self.config.CONFIG_DEFAULT_NUM):
                initial_status = Status.ACTIVE if i < default_start_instances else status
                instance = self.createInstance(capacity, num_CPU, queue_length, initial_status)
                instance.setId(i)
                if (
                    serverless_timer_steps is not None
                    and initial_status == Status.ACTIVE
                    and isinstance(instance, Serverless)
                ):
                    instance.setLastTime(-(i * serverless_timer_steps) // default_start_instances)
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