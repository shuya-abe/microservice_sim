from limit import Limit
from sim_flg import Flg
from status import Status
import datetime

class Config:
    
    # date = datetime.datetime.now().strftime('%Y%m%d_%H%M_')

    # ### SIMULATOR ###
    # SIM_THRESHOLD = 10000
    # SIM_STEP_PER_TIME = 10
    # SIM_LIMIT = Limit.LIMIT_REQUEST
    # # SIM_LIMIT = Limit.LIMIT_TIME

    # ### CLUSTER ###
    # CONFIG_CLUSTER_CPU = 1000

    # ### GENERATOR & SENDER ###
    # CONFIG_LAMBDA = 1 / 10
    # CONFIG_MU = 1 / 100

    # CONFIG_REQUEST_FLG = Flg.FLG_INPUT

    # if (SIM_LIMIT == Limit.LIMIT_TIME):
    #     CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "sec" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    # elif (SIM_LIMIT == Limit.LIMIT_TIMESTEP):
    #     CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "step" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    # elif (SIM_LIMIT == Limit.LIMIT_REQUEST):
    #     CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "reqs" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    # else:
    #     CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "sec" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"

    # ### SCALER ###
    # CONFIG_SCALE_SENSITIVE = 0.1
    # CONFIG_SCALE_INTERVAL = 15
    # CONFIG_SCALE_TARGET = 0.6
    # CONFIG_SERVERLESS_TIMER = 600
    
    # ### INSTANCE ###
    # CONFIG_INSTANCE_FLG = Flg.FLG_SERVERLESS
    
    # CONFIG_DEFAULT_FLG = True
    # CONFIG_DEFAULT_NUM = 1000
    # # CONFIG_DEFAULT_SETUPTIME = 30
    # # CONFIG_DEFAULT_SHUTDOWNTIME = 30
    # CONFIG_DEFAULT_SETUPTIME = 1
    # CONFIG_DEFAULT_SHUTDOWNTIME = 1
    
    # CONFIG_DEFAULT_CAPACITY = 100
    # CONFIG_DEFAULT_num_CPU = 1
    # CONFIG_DEFAULT_QUEUE_LENGTH = -1
    # CONFIG_DEFAULT_STATUS = Status.INACTIVE

    # CONFIG_INSTANCES = [
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.ACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
    #     (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE)
    # ]
    
    # ### OUTPUT ###
    # # SIM_FLG = Flg.FLG_DEFAULT
    # SIM_FLG = Flg.FLG_VERBOSE

    # SIM_DEFAULT_OUTPUT_FILE = "./result/result.csv"
    
    # if CONFIG_INSTANCE_FLG == Flg.FLG_CONTAINER:
    #     SIM_DEFAULT_SERVER_OUTPUT_FILE = "./result/" + str(date) + str(CONFIG_DEFAULT_NUM) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_container"
    #     OUTPUT_FILE = "./result/" + str(date) + str(len(CONFIG_INSTANCES)) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_container"
    # elif CONFIG_INSTANCE_FLG == Flg.FLG_SERVERLESS:
    #     SIM_DEFAULT_SERVER_OUTPUT_FILE = "./result/" + str(date) + str(CONFIG_DEFAULT_NUM) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_serverless"
    #     OUTPUT_FILE = "./result/" + str(date) + str(len(CONFIG_INSTANCES)) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_serverless"

    def __init__(self):
        return
    
    def initialSetup(self, config, sim_index):
        self.SIM_THRESHOLD = int(config[0])
        self.SIM_STEP_PER_TIME = int(config[1])
        limit = config[2]
        if limit == "req":
            self.SIM_LIMIT = Limit.LIMIT_REQUEST
        elif limit == "time":
            self.SIM_LIMIT = Limit.LIMIT_TIME
        elif limit == "step":
            self.SIM_LIMIT = Limit.LIMIT_TIMESTEP
        else:
            exit()
        self.CONFIG_CLUSTER_CPU = int(config[3])
        self.CONFIG_LAMBDA = float(config[4])
        self.CONFIG_MU = float(config[5])
        req_flg = config[6]
        if req_flg == "input":
            self.CONFIG_REQUEST_FLG = Flg.FLG_INPUT
        else:
            self.CONFIG_REQUEST_FLG = Flg.FLG_OUTPUT
        self.CONFIG_SCALE_SENSITIVE = float(config[7])
        self.CONFIG_SCALE_INTERVAL = int(config[8])
        self.CONFIG_SCALE_TARGET = float(config[9])
        self.CONFIG_SERVERLESS_TIMER = int(config[10])
        instance_flg = config[11]
        if instance_flg == "container":
            self.CONFIG_INSTANCE_FLG = Flg.FLG_CONTAINER
        elif instance_flg == "serverless":
            self.CONFIG_INSTANCE_FLG = Flg.FLG_SERVERLESS
        else:
            exit()
        self.CONFIG_DEFAULT_FLG = bool(config[12])
        self.CONFIG_DEFAULT_NUM = int(config[13])
        self.CONFIG_DEFAULT_SETUPTIME = int(config[14])
        self.CONFIG_DEFAULT_SHUTDOWNTIME = int(config[15])
        self.CONFIG_DEFAULT_CAPACITY = int(config[16])
        self.CONFIG_DEFAULT_num_CPU = int(config[17])
        self.CONFIG_DEFAULT_QUEUE_LENGTH = int(config[18])
        
        default_status = config[19]
        if default_status == "inactive":
            self.CONFIG_DEFAULT_STATUS = Status.INACTIVE
        elif default_status == "active":
            self.CONFIG_DEFAULT_STATUS = Status.ACTIVE
        else:
            exit()
        
        sim_flg = config[20]
        if sim_flg == "verbose":
            self.SIM_FLG = Flg.FLG_VERBOSE
        elif sim_flg == "simple":
            self.SIM_FLG = Flg.FLG_DEFAULT
        
        self.SIM_DEFAULT_OUTPUT_FILE = config[21]
        
        if not self.CONFIG_DEFAULT_FLG:
            self.CONFIG_INSTANCES = [
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.ACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
                (self.CONFIG_DEFAULT_CAPACITY, self.CONFIG_DEFAULT_num_CPU, self.CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE)
            ]
        
        self.SIM_INDEX = sim_index
        
        self.date = datetime.datetime.now().strftime('%Y%m%d_%H%M_')
        
        if (self.SIM_LIMIT == Limit.LIMIT_TIME):
            self.CONFIG_REQUEST_FILE = "./requests/" + str(self.SIM_THRESHOLD) + "sec" + "_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_" + str(self.SIM_INDEX) + ".csv"
        elif (self.SIM_LIMIT == Limit.LIMIT_TIMESTEP):
            self.CONFIG_REQUEST_FILE = "./requests/" + str(self.SIM_THRESHOLD) + "step" + "_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_" + str(self.SIM_INDEX) + ".csv"
        elif (self.SIM_LIMIT == Limit.LIMIT_REQUEST):
            self.CONFIG_REQUEST_FILE = "./requests/" + str(self.SIM_THRESHOLD) + "reqs" + "_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_" + str(self.SIM_INDEX) + ".csv"
        else:
            self.CONFIG_REQUEST_FILE = "./requests/" + str(self.SIM_THRESHOLD) + "sec" + "_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_" + str(self.SIM_INDEX) + ".csv"
            
        self.OUTPUT_FILE = ""
        if self.CONFIG_INSTANCE_FLG == Flg.FLG_CONTAINER:
            if self.CONFIG_DEFAULT_FLG:
                if (self.SIM_LIMIT == Limit.LIMIT_TIME):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "time_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"
                elif (self.SIM_LIMIT == Limit.LIMIT_TIMESTEP):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"
                elif (self.SIM_LIMIT == Limit.LIMIT_REQUEST):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "req_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"
                else:
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"
            else:
                if (self.SIM_LIMIT == Limit.LIMIT_TIME):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "time_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"            
                elif (self.SIM_LIMIT == Limit.LIMIT_TIMESTEP):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"            
                elif (self.SIM_LIMIT == Limit.LIMIT_REQUEST):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "req_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"            
                else:
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_container"            
        elif self.CONFIG_INSTANCE_FLG == Flg.FLG_SERVERLESS:
            if self.CONFIG_DEFAULT_FLG:
                if (self.SIM_LIMIT == Limit.LIMIT_TIME):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "time_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                elif (self.SIM_LIMIT == Limit.LIMIT_TIMESTEP):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                elif (self.SIM_LIMIT == Limit.LIMIT_REQUEST):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "req_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                else:
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(self.CONFIG_DEFAULT_NUM) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
            else:
                if (self.SIM_LIMIT == Limit.LIMIT_TIME):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "time_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                elif (self.SIM_LIMIT == Limit.LIMIT_TIMESTEP):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                elif (self.SIM_LIMIT == Limit.LIMIT_REQUEST):
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "req_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
                else:
                    self.OUTPUT_FILE = "./result/" + str(self.date) + str(len(self.CONFIG_INSTANCES)) + "srv_" + str(self.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(self.SIM_THRESHOLD) + "step_lambda" + str(self.CONFIG_LAMBDA) + "_mu" + str(self.CONFIG_MU) + "_serverless"
        self.OUTPUT_FILE_PACKET = self.OUTPUT_FILE + "_" + str(self.SIM_INDEX) + "_packet.csv"
        self.OUTPUT_FILE_NUM_INSTANCE = self.OUTPUT_FILE + "_" + str(self.SIM_INDEX) + "_num_instance.csv"
        self.OUTPUT_FILE = self.OUTPUT_FILE + "_" + str(self.SIM_INDEX) + "_result.csv"




        return