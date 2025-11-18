from queue_simulator import QueueSimulator
from config import Config
import csv
import time
from concurrent.futures import ProcessPoolExecutor

def main():
    config_file = "config_list.csv"
    sim_count_start = 5
    sim_count_end = 10
    
    sim_timer = time.time()
    
    with open(config_file, 'r', newline='') as f:
        next(csv.reader(f))
        reader = csv.reader(f)
        with ProcessPoolExecutor(max_workers=5) as executor:
            for row in reader:
                if(not str(row[0]).startswith("#")):
                    for i in range(sim_count_start, sim_count_end): 
                        config = Config()
                        config.initialSetup(row, i)
                        executor.submit(simulate, config)
        
        # for row in reader:
        #     if(not str(row[0]).startswith("#")):
        #         config = Config()
        #         config.initialSetup(row)
        #         simulate(config)
    
    print("========total time========")
    print(time.time() - sim_timer)
        
    return

# def setupConfig(config_file):
#     config = Config(config_file)
#     config.initialSetup()
#     return config
    

def simulate(config:Config):
    # results = []
    step_per_time = config.SIM_STEP_PER_TIME
    _lambda = decimal_normalize(config.CONFIG_LAMBDA)
    mu = decimal_normalize(config.CONFIG_MU)
    # outfile = getOutfile(threshold, limit, _lambda, mu)
    outfile = config.OUTPUT_FILE
    sim = QueueSimulator(config.SIM_THRESHOLD, config.SIM_LIMIT, step_per_time, _lambda, mu, config)
    with open(outfile, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", " ex_time_service", " ex_time_wait", " ex_time_total"])
        # writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", " ideal_rho", " ex_rho", " ideal_time_service", " ex_time_service", " ideal_time_wait", " ex_time_wait", " ideal_time_total", " ex_time_total"])


        sim.startSimulate()
        result = sim.endSimulate(config.CONFIG_DEFAULT_FLG)
        sim = None
        line = []
        line.append(step_per_time)
        line.extend(result)
        writer.writerow(line)
        f.flush()

# def getOutfile(threshold, limit, _lambda, mu):
#     date = datetime.datetime.now().strftime('%Y%m%d_%H%M_')
#     str_limit = ""
#     if limit == Limit.LIMIT_TIME:
#         str_limit = "sec"
#     elif limit == Limit.LIMIT_TIMESTEP:
#         str_limit = "step"
#     elif limit == Limit.LIMIT_REQUEST:
#         str_limit = "reqs"
    
#     if Config.CONFIG_DEFAULT_FLG:
#         # outfile = "./result/" + str(date) + str(Config.CONFIG_DEFAULT_NUM) + "srv_" + str(Config.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(threshold) + str_limit + "_lambda" + str(_lambda) + "_mu" + str(mu) + "_results"
#         outfile = Config.SIM_DEFAULT_SERVER_OUTPUT_FILE + "_results"
#     else:
#         # outfile = "./result/" + str(date) + str(len(Config.CONFIG_INSTANCES)) + "srv_" + str(Config.CONFIG_DEFAULT_num_CPU) + "CPU_" + str(threshold) + str_limit + "_lambda" + str(_lambda) + "_mu" + str(mu) + "_results"
#         outfile =  Config.SIM_OUTPUT_FILE + "_results"
#     return outfile

def decimal_normalize(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


if __name__ == "__main__":
    now = time.time()
    main()
    print(time.time() - now)

