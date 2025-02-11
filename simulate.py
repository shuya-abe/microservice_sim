from queue_simulator import QueueSimulator
from config import Config
import csv

def main():
    threshold = Config.SIM_THRESHOLD
    limit = Config.SIM_LIMIT
    output_flg = Config.SIM_FLG
    # results = []
    if Config.CONFIG_DEFAULT_FLG:
        outfile = Config.SIM_DEFAULT_SERVER_OUTPUT_FILE + "_container_results.csv"
    else:
        outfile = Config.SIM_OUTPUT_FILE + "_container_results.csv"
    with open(outfile, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", " ex_rho", " ex_time_service", " ex_time_wait", " ex_time_total"])
        # writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", " ideal_rho", " ex_rho", " ideal_time_service", " ex_time_service", " ideal_time_wait", " ex_time_wait", " ideal_time_total", " ex_time_total"])
        for i in range(1):
            step_per_time = Config.SIM_STEP_PER_TIME * (10 ** i)
            for j in range(1):
                sim = QueueSimulator(threshold, limit, step_per_time)
                sim.startSimulate()
                # results.append(sim.endSimulate(output_flg))
                result = sim.endSimulate(output_flg)
                sim = None
                line = []
                line.append(step_per_time)
                line.extend(result)
                writer.writerow(line)
                f.flush()
    return

if __name__ == "__main__":
    main()
