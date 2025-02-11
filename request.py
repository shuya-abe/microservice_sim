from status import Status

class Request:
    # id = -1
    # org_workload = -1
    # workload = -1
    # time_start = -1
    # time_start_process = -1
    # time_end = -1
    # status = Status.DEFAULT

    def __init__(self, id, workload, time):
        self.clearAll()
        self.setId(id)
        self.org_workload = workload
        self.setWorkload(workload)
        self.setStartTime(time)
        self.setStartProcessTime(-1)
        self.setEndTime(-1)
        self.setStatus(Status.GENERATED)
        self.processedBy = ""

    def clearAll(self):
        id = -1
        org_workload = -1
        workload = -1
        time_start = -1
        time_start_process = -1
        time_end = -1
        status = Status.DEFAULT
        return

    def setId(self, id):
        self.id = id

    def getId(self):
        return self.id
    
    def setStartTime(self, time):
        self.time_start = time

    def getStartTime(self):
        return self.time_start
    
    def setProcessedBy(self, instance):
        self.processedBy = instance

    def getProcessedBy(self):
        return self.processedBy

    def setStartProcessTime(self, time):
        self.time_start_process = time

    def getStartProcessTime(self):
        return self.time_start_process
    
    def setEndTime(self, time):
        self.time_end = time

    def getEndTime(self):
        return self.time_end
    
    def getLifetime(self):
        return self.time_end - self.time_start
    
    def getWaitTime(self):
        return self.time_start_process - self.time_start

    def setStatus(self, status):
        self.status = status

    def getStatus(self):
        return self.status
    
    def setWorkload(self, workload):
        self.workload = workload

    def getWorkload(self):
        return self.workload
    
    def getOrgWorkload(self):
        return self.org_workload
