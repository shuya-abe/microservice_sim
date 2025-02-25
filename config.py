from limit import Limit
from sim_flg import Flg
from status import Status
import datetime

class Config:
    date = datetime.datetime.now().strftime('%Y%m%d_%H%M_')

    ### SIMULATOR ###
    SIM_THRESHOLD = 10000
    SIM_STEP_PER_TIME = 10
    # SIM_LIMIT = Limit.LIMIT_REQUEST
    SIM_LIMIT = Limit.LIMIT_TIME

    ### CLUSTER ###
    CONFIG_CLUSTER_CPU = 100

    ### GENERATOR & SENDER ###
    CONFIG_LAMBDA = 1
    CONFIG_MU = 1 / 10

    CONFIG_REQUEST_FLG = Flg.FLG_INPUT

    if (SIM_LIMIT == Limit.LIMIT_TIME):
        CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "sec" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    elif (SIM_LIMIT == Limit.LIMIT_TIMESTEP):
        CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "step" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    elif (SIM_LIMIT == Limit.LIMIT_REQUEST):
        CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "reqs" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"
    else:
        CONFIG_REQUEST_FILE = "./requests/" + str(SIM_THRESHOLD) + "sec" + "_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + ".csv"

    ### SCALER ###
    CONFIG_SCALE_SENSITIVE = 0.1
    CONFIG_SCALE_INTERVAL = 60
    CONFIG_SCALE_TARGET = 0.6
    CONFIG_SERVERLESS_TIMER = 10
    
    ### INSTANCE ###
    CONFIG_INSTANCE_FLG = Flg.FLG_SERVERLESS
    
    CONFIG_DEFAULT_FLG = True
    CONFIG_DEFAULT_NUM = 1000
    CONFIG_DEFAULT_SETUPTIME = 1
    CONFIG_DEFAULT_SHUTDOWNTIME = 1
    
    CONFIG_DEFAULT_CAPACITY = 100
    CONFIG_DEFAULT_num_CPU = 1
    CONFIG_DEFAULT_QUEUE_LENGTH = -1
    CONFIG_DEFAULT_STATUS = Status.INACTIVE

    CONFIG_INSTANCES = [
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.ACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE),
        (CONFIG_DEFAULT_CAPACITY, CONFIG_DEFAULT_num_CPU, CONFIG_DEFAULT_QUEUE_LENGTH, Status.INACTIVE)
    ]
    
    ### OUTPUT ###
    # SIM_FLG = Flg.FLG_DEFAULT
    SIM_FLG = Flg.FLG_VERBOSE

    SIM_DEFAULT_OUTPUT_FILE = "./result/result.csv"
    SIM_DEFAULT_SERVER_OUTPUT_FILE = "./result/" + str(date) + str(CONFIG_DEFAULT_NUM) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_" + str(date)
    SIM_OUTPUT_FILE = "./result/" + str(date) + str(len(CONFIG_INSTANCES)) + "srv_" + str(CONFIG_DEFAULT_num_CPU) + "CPU_" + str(SIM_THRESHOLD) + "step_lambda" + str(CONFIG_LAMBDA) + "_mu" + str(CONFIG_MU) + "_" + str(date)

    def __init__(self):
        return