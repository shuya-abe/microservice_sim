from queue_simulator import QueueSimulator
from config import Config
from generator import Generator
import csv
import time
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed


SUMMARY_HEADER = [
    "timestamp",
    "request_file",
    "lambda",
    "mu",
    "num_instances",
    "default_capacity",
    "default_num_cpu",
    "step_per_time",
    "total_time",
    "num_steps",
    "num_reqs",
    "ex_time_service",
    "ex_time_wait",
    "ex_time_total",
]


# Runtime settings (edit here instead of using environment variables)
SETTINGS = {
    # CSV file containing experiment configurations.
    "config_file": "config_list.csv",
    # Repeat index start (inclusive).
    "sim_count_start": 0,
    # Repeat index end (exclusive).
    "sim_count_end": 10,
    # Enable worker auto-tuning with a small benchmark run.
    "autotune_enabled": True,
    # If True, run only auto-tuning and skip the main experiment.
    "autotune_only": False,
    # Fixed worker count for normal run. Use None to use default policy.
    "max_workers": None,
    # Cores to keep free for host/background tasks.
    "reserved_cores": 4,
    # Host CPU core hint used when running on WSL.
    "host_cores": 20,
    # Number of config rows sampled for auto-tuning benchmark.
    "autotune_configs": 4,
    # Number of repeat rounds sampled for auto-tuning benchmark.
    "autotune_rounds": 2,
    # Candidate worker counts tested by auto-tuning.
    "autotune_candidates": list(range(5, 15)),
    # Enable/disable hybrid event-driven skip logic.
    "enable_hybrid_skip": True,
}


def clamp_int(value, default_value, min_value=None, max_value=None):
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default_value

    if min_value is not None:
        out = max(min_value, out)
    if max_value is not None:
        out = min(max_value, out)
    return out


def is_wsl_environment():
    if os.getenv("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            version = f.read().lower()
        return "microsoft" in version or "wsl" in version
    except OSError:
        return False


def resolve_effective_cores():
    detected_cores = os.cpu_count() or 1
    if is_wsl_environment():
        host_cores = clamp_int(SETTINGS.get("host_cores"), 20, min_value=1)
        return min(detected_cores, host_cores), detected_cores
    return detected_cores, detected_cores


def resolve_reserved_cores(total_cores):
    # Keep some CPU headroom for the host while running on WSL2.
    default_reserved = 4 if total_cores >= 12 else 1
    max_reserved = max(0, total_cores - 1)
    return clamp_int(SETTINGS.get("reserved_cores"), default_reserved, min_value=0, max_value=max_reserved)


def resolve_max_workers(default_workers=5, max_cap=None, configured_workers=None):
    workers = clamp_int(configured_workers, default_workers, min_value=1)
    workers = max(1, workers)
    if max_cap is not None:
        workers = min(workers, max_cap)
    return workers


def parse_candidate_workers(cpu_budget, configured_candidates=None):
    if configured_candidates is None:
        if cpu_budget <= 8:
            candidates = list(range(1, cpu_budget + 1))
        elif cpu_budget <= 16:
            candidates = [2, 4, 6, 8, 10, 12, 14, cpu_budget]
        else:
            candidates = [2, 4, 6, 8, 10, 12, 14, 16, 18, cpu_budget]
    else:
        candidates = list(configured_candidates)

    cleaned = sorted({w for w in candidates if 1 <= w <= cpu_budget})
    if not cleaned:
        cleaned = [min(5, cpu_budget)]
    return cleaned


def build_task_specs(config_rows, sim_count_start, sim_count_end, config_limit=None, round_limit=None):
    if config_limit is None:
        selected_rows = config_rows
    try:
        selected_rows = config_rows[:config_limit]
    except TypeError:
        selected_rows = config_rows

    total_rounds = sim_count_end - sim_count_start
    if round_limit is None:
        effective_rounds = total_rounds
    else:
        effective_rounds = min(total_rounds, round_limit)

    task_specs = []
    for offset in range(effective_rounds):
        sim_index = sim_count_start + offset
        for config_idx, row in enumerate(selected_rows):
            task_specs.append((sim_index, config_idx, row))
    return task_specs


def setup_config(row, sim_index):
    config = Config()
    config.initialSetup(row, sim_index)
    return config


def ensure_request_file_exists(config):
    req_file = config.CONFIG_REQUEST_FILE
    if os.path.isfile(req_file):
        return

    step_per_time = config.SIM_STEP_PER_TIME
    _lambda = decimal_normalize(config.CONFIG_LAMBDA)
    mu = decimal_normalize(config.CONFIG_MU)
    generator = Generator(step_per_time, _lambda, mu, config)
    generator.createAllRequests(config.SIM_LIMIT, config.SIM_THRESHOLD)
    generator.outputRequests(req_file)


def precreate_request_files(task_specs):
    prepared_files = set()
    for sim_index, _config_idx, row in task_specs:
        config = setup_config(row, sim_index)
        req_file = config.CONFIG_REQUEST_FILE
        if req_file in prepared_files:
            continue
        ensure_request_file_exists(config)
        prepared_files.add(req_file)


def retarget_output_files_for_benchmark(config, output_root, task_label):
    os.makedirs(output_root, exist_ok=True)
    base = os.path.join(output_root, task_label)
    config.OUTPUT_FILE_PACKET = base + "_packet.csv"
    config.OUTPUT_FILE_NUM_INSTANCE = base + "_num_instance.csv"
    config.OUTPUT_FILE = base + "_result.csv"
    config.SIM_DEFAULT_OUTPUT_FILE = os.path.join(output_root, "summary.csv")
    return config


def load_config_rows(config_file):
    rows = []
    with open(config_file, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not str(row[0]).startswith("#"):
                rows.append(row)
    return rows


def run_task_specs(task_specs, max_workers, write_summary, show_progress, output_root=None):
    futures = []
    future_meta = {}
    summary_handles = {}
    summary_writers = {}
    pending_task_specs = []
    skipped_tasks = 0
    task_elapsed_records = []

    for sim_index, config_idx, row in task_specs:
        config = setup_config(row, sim_index)
        if output_root is None and os.path.isfile(config.OUTPUT_FILE) and os.path.getsize(config.OUTPUT_FILE) > 0:
            skipped_tasks += 1
            if show_progress:
                print(f"[skip] repeat={sim_index} config_index={config_idx} result_exists={config.OUTPUT_FILE}")
            continue
        pending_task_specs.append((sim_index, config_idx, row))

    total_tasks = len(pending_task_specs)
    if skipped_tasks > 0:
        print(f"resume: skipped_existing={skipped_tasks}, pending={total_tasks}")
    if total_tasks == 0:
        return 0.0, []

    timer = time.time()
    try:
        # Avoid concurrent request-file creation races in worker processes.
        precreate_request_files(pending_task_specs)

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for order_idx, (sim_index, config_idx, row) in enumerate(pending_task_specs):
                config = setup_config(row, sim_index)
                if output_root is not None:
                    task_label = f"task{order_idx}_rep{sim_index}_cfg{config_idx}"
                    config = retarget_output_files_for_benchmark(config, output_root, task_label)
                future = executor.submit(simulate, config)
                futures.append(future)
                future_meta[future] = (sim_index, config_idx)

            completed = 0
            for future in as_completed(futures):
                summary = future.result()
                if write_summary:
                    output_file = summary["summary_output_file"]
                    if output_file not in summary_writers:
                        needs_header = (not os.path.isfile(output_file)) or os.path.getsize(output_file) == 0
                        handle = open(output_file, 'a', newline='')
                        summary_handles[output_file] = handle
                        writer = csv.writer(handle)
                        if needs_header:
                            writer.writerow(SUMMARY_HEADER)
                        summary_writers[output_file] = writer
                    summary_writers[output_file].writerow(summary["summary_row"])
                    summary_handles[output_file].flush()

                completed += 1
                if show_progress:
                    sim_index, config_idx = future_meta[future]
                    print(f"[{completed}/{total_tasks}] finished repeat={sim_index} config_index={config_idx}")

                worker_elapsed = summary.get("worker_elapsed_sec")
                if worker_elapsed is not None:
                    sim_index, config_idx = future_meta[future]
                    task_elapsed_records.append((sim_index, config_idx, float(worker_elapsed)))
    finally:
        for handle in summary_handles.values():
            handle.close()

    return time.time() - timer, task_elapsed_records


def estimate_makespan_lpt(task_durations, workers):
    if workers <= 0:
        return float("inf")
    if not task_durations:
        return 0.0

    loads = [0.0] * workers
    for duration in sorted(task_durations, reverse=True):
        idx = min(range(workers), key=lambda i: loads[i])
        loads[idx] += duration
    return max(loads)


def autotune_max_workers(config_rows, sim_count_start, sim_count_end, cpu_budget):
    total_rounds = sim_count_end - sim_count_start
    config_count = clamp_int(
        SETTINGS.get("autotune_configs"),
        min(4, len(config_rows)),
        min_value=1,
        max_value=len(config_rows),
    )
    profile_round_limit = clamp_int(
        SETTINGS.get("autotune_rounds"),
        min(1, total_rounds),
        min_value=1,
        max_value=total_rounds,
    )

    profile_tasks = build_task_specs(
        config_rows,
        sim_count_start,
        sim_count_end,
        config_limit=config_count,
        round_limit=profile_round_limit,
    )
    full_tasks = build_task_specs(config_rows, sim_count_start, sim_count_end)

    candidates = parse_candidate_workers(cpu_budget, SETTINGS.get("autotune_candidates"))
    print("=== AUTOTUNE START ===")
    print(
        f"profile_configs={config_count}, profile_rounds={profile_round_limit}, "
        f"profile_tasks={len(profile_tasks)}, total_tasks={len(full_tasks)}"
    )
    print(f"candidates={candidates}")

    profile_workers = resolve_max_workers(
        default_workers=min(4, cpu_budget),
        max_cap=cpu_budget,
        configured_workers=None,
    )

    duration_by_config = {}
    all_profile_durations = []
    with tempfile.TemporaryDirectory(prefix="simulate_autotune_") as temp_root:
        run_root = os.path.join(temp_root, "profile")
        profile_elapsed, profile_records = run_task_specs(
            profile_tasks,
            max_workers=profile_workers,
            write_summary=False,
            show_progress=False,
            output_root=run_root,
        )
        print(f"profile_run workers={profile_workers}: elapsed={profile_elapsed:.3f}s, records={len(profile_records)}")

    tmp_duration = {}
    for _sim_index, config_idx, elapsed in profile_records:
        tmp_duration.setdefault(config_idx, []).append(elapsed)
        all_profile_durations.append(elapsed)

    if not all_profile_durations:
        fallback_workers = candidates[0]
        print(f"autotune warning: no profile durations found. fallback max_workers={fallback_workers}")
        return fallback_workers, [(fallback_workers, 0.0, 0.0)]

    for config_idx, values in tmp_duration.items():
        values_sorted = sorted(values)
        mid = len(values_sorted) // 2
        if len(values_sorted) % 2 == 1:
            duration_by_config[config_idx] = values_sorted[mid]
        else:
            duration_by_config[config_idx] = (values_sorted[mid - 1] + values_sorted[mid]) / 2.0

    global_median = sorted(all_profile_durations)[len(all_profile_durations) // 2]

    predicted_rows = []
    for workers in candidates:
        predicted_task_durations = [duration_by_config.get(config_idx, global_median) for _sim_index, config_idx, _row in full_tasks]
        predicted_makespan = estimate_makespan_lpt(predicted_task_durations, workers)
        predicted_throughput = len(full_tasks) / predicted_makespan if predicted_makespan > 0 else 0.0
        predicted_rows.append((workers, predicted_makespan, predicted_throughput))
        print(
            f"autotune workers={workers}: predicted_makespan={predicted_makespan:.3f}s, "
            f"predicted_throughput={predicted_throughput:.6f} tasks/s"
        )

    predicted_rows.sort(key=lambda item: item[1])
    best_workers = predicted_rows[0][0]
    print(f"=== AUTOTUNE DONE: selected max_workers={best_workers} ===")
    return best_workers, predicted_rows

def main():
    config_file = SETTINGS.get("config_file", "config_list.csv")
    sim_count_start = clamp_int(SETTINGS.get("sim_count_start"), 0, min_value=0)
    sim_count_end = clamp_int(SETTINGS.get("sim_count_end"), 1, min_value=sim_count_start + 1)
    config_rows = load_config_rows(config_file)
    if len(config_rows) == 0:
        print("No config rows were found.")
        return

    total_cores, detected_cores = resolve_effective_cores()
    reserved_cores = resolve_reserved_cores(total_cores)
    cpu_budget = max(1, total_cores - reserved_cores)

    autotune_enabled = bool(SETTINGS.get("autotune_enabled", False))
    autotune_only = bool(SETTINGS.get("autotune_only", False))

    if autotune_enabled:
        max_workers, _bench_results = autotune_max_workers(
            config_rows,
            sim_count_start,
            sim_count_end,
            cpu_budget,
        )
        if autotune_only:
            print("autotune_only=True: skip main experiment run.")
            return
    else:
        max_workers = resolve_max_workers(
            default_workers=min(5, cpu_budget),
            max_cap=cpu_budget,
            configured_workers=SETTINGS.get("max_workers"),
        )

    sim_timer = time.time()
    total_rounds = sim_count_end - sim_count_start
    total_tasks = len(config_rows) * total_rounds
    print(
        f"cores={total_cores}, detected_cores={detected_cores}, reserved={reserved_cores}, cpu_budget={cpu_budget}, "
        f"configs={len(config_rows)}, rounds={total_rounds}, tasks={total_tasks}, max_workers={max_workers}"
    )

    task_specs = build_task_specs(config_rows, sim_count_start, sim_count_end)
    run_task_specs(
        task_specs,
        max_workers=max_workers,
        write_summary=True,
        show_progress=True,
        output_root=None,
    )
        
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
    worker_timer = time.time()
    setattr(config, "SIM_ENABLE_HYBRID_SKIP", bool(SETTINGS.get("enable_hybrid_skip", True)))
    step_per_time = config.SIM_STEP_PER_TIME
    _lambda = decimal_normalize(config.CONFIG_LAMBDA)
    mu = decimal_normalize(config.CONFIG_MU)
    # outfile = getOutfile(threshold, limit, _lambda, mu)
    outfile = config.OUTPUT_FILE
    sim = QueueSimulator(config.SIM_THRESHOLD, config.SIM_LIMIT, step_per_time, _lambda, mu, config)
    with open(outfile, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", "ex_time_service", "ex_time_wait", "ex_time_total"])
        # writer.writerow(["step_per_time", "total_time", "num_steps", "num_reqs", " ideal_rho", " ex_rho", " ideal_time_service", " ex_time_service", " ideal_time_wait", " ex_time_wait", " ideal_time_total", " ex_time_total"])


        sim.startSimulate()
        summary = sim.endSimulate(config.CONFIG_DEFAULT_FLG)
        sim = None
        line = []
        line.append(step_per_time)
        line.extend(summary["result"])
        writer.writerow(line)
        f.flush()

    summary["worker_elapsed_sec"] = time.time() - worker_timer
    return summary

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

