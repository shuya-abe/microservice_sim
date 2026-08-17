from queue_simulator import QueueSimulator
from config import Config
from generator import Generator
from limit import Limit
import csv
import time
import os
import tempfile
import argparse
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from queue import Empty
from worker_progress import init_progress_queue


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
    "steady_enabled",
    "steady_reached",
    "num_batches",
    "steady_batch_index",
    "steady_start",
    "steady_end",
    "ci_total_low",
    "ci_total_high",
    "ci_wait_low",
    "ci_wait_high",
    "ci_service_low",
    "ci_service_high",
    "ave_instances_steady",
]


RESULT_HEADER = [
    "step_per_time",
    "total_time",
    "num_steps",
    "num_reqs",
    "ex_time_service",
    "ex_time_wait",
    "ex_time_total",
    "steady_enabled",
    "steady_reached",
    "num_batches",
    "steady_batch_index",
    "steady_start",
    "steady_end",
    "ci_total_low",
    "ci_total_high",
    "ci_wait_low",
    "ci_wait_high",
    "ci_service_low",
    "ci_service_high",
    "ave_instances_steady",
]


# Runtime settings (edit here instead of using environment variables)
SETTINGS = {
    # CSV file containing experiment configurations.
    "config_file": "config_list.csv",
    # Repeat index start (inclusive).
    "sim_count_start": 0,
    # Repeat index end (exclusive).
    "sim_count_end": 1,
    # Enable worker auto-tuning with a small benchmark run.
    "autotune_enabled": True,
    # If True, run only auto-tuning and skip the main experiment.
    "autotune_only": False,
    # Fixed worker count for normal run. Use None to use default policy.
    "max_workers": None,
    # Cores to keep free for host/background tasks.
    "reserved_cores": 4,
    # Host CPU core hint used when running on WSL.
    "host_cores": 12,
    # Number of config rows sampled for auto-tuning benchmark.
    "autotune_configs": 4,
    # Number of repeat rounds sampled for auto-tuning benchmark.
    "autotune_rounds": 2,
    # Candidate worker counts tested by auto-tuning.
    "autotune_candidates": list(range(5, 15)),
    # Logical sim-time cap for each autotune profile task (keeps tiny-λ profiles from running forever).
    "autotune_profile_sim_time": 30.0,
    # Do not sample λ above this in autotune profile (λ=1600 profiles are too slow for worker pick).
    "autotune_profile_max_lambda": 200.0,
    # Cap completed requests per autotune profile run.
    "autotune_profile_max_requests": 5000,
    # If True, only pre-generate shared request CSVs (parallel) and skip simulation.
    "generate_requests_only": False,
    # --- Steady-state detection (online batches) ---
    # When True, run until consecutive batches stabilize (or max_batches).
    "steady_enabled": True,
    # Minimum completed requests per measurement batch.
    "steady_batch_reqs": 1000,
    # Minimum simulated time per batch. None => serverless timer / container heuristic.
    "steady_batch_min_time": 600,
    # Relative tolerance between consecutive batch means.
    "steady_rel_tol": 0.10,
    # Number of consecutive stable batches required.
    "steady_consecutive": 2,
    # Safety cap on number of batches.
    "steady_max_batches": 100000,
    # Confidence level for batch means (normal approx).
    "steady_ci_level": 0.95,
    # Pre-extend shared request CSVs toward an estimated steady horizon (online extend still fills gaps).
    "steady_preextend_enabled": True,
    # Batches worth of arrivals to pre-generate. None => max(3*consecutive, consecutive+10).
    "steady_preextend_batches": None,
    # Multiply estimated horizon by this safety margin.
    "steady_preextend_margin": 1.1,
    # Cap pre-generated rows per request file (remaining arrivals still grow online).
    "steady_preextend_max_rows": 2000000,
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


def build_task_specs(config_rows, sim_count_start, sim_count_end, config_limit=None, round_limit=None, row_indices=None):
    if row_indices is not None:
        selected = [(int(i), config_rows[int(i)]) for i in row_indices]
    elif config_limit is None:
        selected = list(enumerate(config_rows))
    else:
        selected = list(enumerate(config_rows[:config_limit]))

    total_rounds = sim_count_end - sim_count_start
    if round_limit is None:
        effective_rounds = total_rounds
    else:
        effective_rounds = min(total_rounds, round_limit)

    task_specs = []
    for offset in range(effective_rounds):
        sim_index = sim_count_start + offset
        for config_idx, row in selected:
            task_specs.append((sim_index, config_idx, row))
    return task_specs


def select_autotune_profile_indices(config_rows, count):
    """Spread profile samples across λ (capped) so autotune stays fast on any CSV order."""
    n = len(config_rows)
    count = min(int(count), n)
    if count <= 0:
        return []
    if count >= n:
        return list(range(n))

    max_lam = float(SETTINGS.get("autotune_profile_max_lambda", 200.0) or 200.0)
    first_at_lambda = {}
    for i, row in enumerate(config_rows):
        try:
            lam = float(row[5])
        except (IndexError, TypeError, ValueError):
            lam = 0.0
        first_at_lambda.setdefault(lam, i)

    unique_lams = sorted(first_at_lambda)
    eligible_lams = [lam for lam in unique_lams if lam <= max_lam]
    if not eligible_lams:
        eligible_lams = unique_lams[:1]

    picked = []
    used = set()
    span = max(count - 1, 1)
    for j in range(count):
        pos = int(round(j * (len(eligible_lams) - 1) / span))
        idx = first_at_lambda[eligible_lams[pos]]
        if idx not in used:
            picked.append(idx)
            used.add(idx)

    if len(picked) < count:
        for lam in eligible_lams:
            idx = first_at_lambda[lam]
            if idx not in used:
                picked.append(idx)
                used.add(idx)
            if len(picked) >= count:
                break
    return picked


def estimate_profile_request_threshold(config, profile_sim_time):
    """Request-count cap for a short autotune profile (LIMIT_REQUEST stops exactly here)."""
    lam = max(float(config.CONFIG_LAMBDA), 1e-12)
    t = max(float(profile_sim_time), 1.0)
    max_reqs = clamp_int(SETTINGS.get("autotune_profile_max_requests"), 5000, min_value=100)
    estimated = int(lam * t * 1.25) + 64
    return min(max(estimated, 100), max_reqs)


def apply_steady_settings(config: Config):
    """Attach steady-state detection parameters from SETTINGS onto config."""
    from steady_state import resolve_batch_min_time

    if getattr(config, "STEADY_FORCE_DISABLED", False):
        config.STEADY_ENABLED = False
    else:
        config.STEADY_ENABLED = bool(SETTINGS.get("steady_enabled", False))
    config.STEADY_BATCH_REQS = clamp_int(SETTINGS.get("steady_batch_reqs"), 10000, min_value=1)
    config.STEADY_BATCH_MIN_TIME = SETTINGS.get("steady_batch_min_time")
    config.STEADY_REL_TOL = float(SETTINGS.get("steady_rel_tol", 0.05))
    config.STEADY_CONSECUTIVE = clamp_int(SETTINGS.get("steady_consecutive"), 3, min_value=2)
    config.STEADY_MAX_BATCHES = clamp_int(SETTINGS.get("steady_max_batches"), 50, min_value=1)
    config.STEADY_CI_LEVEL = float(SETTINGS.get("steady_ci_level", 0.95))
    # Resolve default min time now that instance mode is known.
    if config.STEADY_BATCH_MIN_TIME is None:
        config.STEADY_BATCH_MIN_TIME = resolve_batch_min_time(config)
    else:
        config.STEADY_BATCH_MIN_TIME = float(config.STEADY_BATCH_MIN_TIME)
    return config


def setup_config(row, sim_index):
    config = Config()
    config.initialSetup(row, sim_index)
    apply_steady_settings(config)
    return config


def estimate_steady_batch_time(config):
    """Expected sim-time length of one steady measurement batch."""
    lam = max(float(config.CONFIG_LAMBDA), 1e-12)
    t_min = float(getattr(config, "STEADY_BATCH_MIN_TIME", 0.0) or 0.0)
    n_min = int(getattr(config, "STEADY_BATCH_REQS", 1) or 1)
    return max(t_min, n_min / lam)


def resolve_preextend_batches(config):
    configured = SETTINGS.get("steady_preextend_batches")
    consecutive = int(getattr(config, "STEADY_CONSECUTIVE", 3) or 3)
    max_batches = int(getattr(config, "STEADY_MAX_BATCHES", consecutive) or consecutive)
    if configured is None:
        batches = max(consecutive * 3, consecutive + 10)
    else:
        batches = clamp_int(configured, consecutive * 3, min_value=consecutive)
    return min(batches, max_batches)


def estimate_steady_preextend_horizon(config):
    """
    Approximate logical time the shared arrival CSV should cover up front.

    Exact end time is unknown (depends on when consecutive batches stabilize),
    so we use:
      horizon ~= preextend_batches * max(batch_min_time, batch_reqs/lambda) * margin
    capped so that expected rows ~= lambda * horizon <= steady_preextend_max_rows.
    Online extendUntil still fills anything beyond this.
    """
    if not bool(getattr(config, "STEADY_ENABLED", False)):
        return None
    batches = resolve_preextend_batches(config)
    margin = float(SETTINGS.get("steady_preextend_margin", 1.1) or 1.1)
    horizon = estimate_steady_batch_time(config) * batches * max(margin, 1.0)
    lam = max(float(config.CONFIG_LAMBDA), 1e-12)
    max_rows = clamp_int(SETTINGS.get("steady_preextend_max_rows"), 2000000, min_value=1000)
    # Leave headroom vs Poisson overshoot.
    horizon_cap = float(max_rows) / lam
    return min(horizon, horizon_cap)


def ensure_request_file_exists(config):
    req_file = config.CONFIG_REQUEST_FILE
    if os.path.isfile(req_file) and os.path.getsize(req_file) > 0:
        return False

    directory = os.path.dirname(req_file) or "."
    os.makedirs(directory, exist_ok=True)
    step_per_time = config.SIM_STEP_PER_TIME
    _lambda = decimal_normalize(config.CONFIG_LAMBDA)
    mu = decimal_normalize(config.CONFIG_MU)
    generator = Generator(step_per_time, _lambda, mu, config)
    generator.generate_and_write(req_file, config.SIM_LIMIT, config.SIM_THRESHOLD)
    return True


def ensure_request_file_preextended(config, preextend=True):
    """Create seed CSV if needed, then optionally extend toward estimated steady horizon."""
    created = ensure_request_file_exists(config)
    appended = 0
    horizon = None
    if preextend and bool(SETTINGS.get("steady_preextend_enabled", True)):
        horizon = estimate_steady_preextend_horizon(config)
        if horizon is not None:
            step_per_time = config.SIM_STEP_PER_TIME
            _lambda = decimal_normalize(config.CONFIG_LAMBDA)
            mu = decimal_normalize(config.CONFIG_MU)
            generator = Generator(step_per_time, _lambda, mu, config)
            max_rows = clamp_int(SETTINGS.get("steady_preextend_max_rows"), 2000000, min_value=1000)
            appended = generator.ensure_file_until(config.CONFIG_REQUEST_FILE, horizon, max_new=max_rows)
    return config.CONFIG_REQUEST_FILE, created, int(appended or 0), horizon


def _generate_request_file_task(payload):
    sim_index, row, preextend = payload
    config = setup_config(row, sim_index)
    path, created, appended, horizon = ensure_request_file_preextended(config, preextend=preextend)
    return path, created, appended, horizon


def collect_unique_request_jobs(task_specs):
    jobs = []
    seen = set()
    for sim_index, _config_idx, row in task_specs:
        config = setup_config(row, sim_index)
        req_file = config.CONFIG_REQUEST_FILE
        if req_file in seen:
            continue
        seen.add(req_file)
        jobs.append((sim_index, row))
    return jobs


def cleanup_stale_request_lock_files(show_progress=True):
    """Remove legacy sidecar *.csv.lock files from older generator versions."""
    requests_dir = os.path.join(".", "requests")
    if not os.path.isdir(requests_dir):
        return 0
    removed = 0
    for name in os.listdir(requests_dir):
        if not name.endswith(".lock"):
            continue
        path = os.path.join(requests_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    if show_progress and removed:
        print(f"removed stale request lock files: {removed}")
    return removed


def precreate_request_files(task_specs, max_workers=1, show_progress=True, preextend=True):
    cleanup_stale_request_lock_files(show_progress=show_progress)
    jobs = collect_unique_request_jobs(task_specs)
    if not jobs:
        return 0, 0

    workers = max(1, min(int(max_workers or 1), len(jobs)))
    created = 0
    reused = 0
    extended = 0
    if show_progress:
        print(
            f"precreate request files: unique={len(jobs)}, workers={workers}, "
            f"preextend={bool(preextend and SETTINGS.get('steady_preextend_enabled', True))}"
        )

    payloads = [(sim_index, row, bool(preextend)) for sim_index, row in jobs]
    if workers == 1:
        results = [_generate_request_file_task(payload) for payload in payloads]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_generate_request_file_task, payload) for payload in payloads]
            pending = set(futures)
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    results.append(future.result())

    for _path, was_created, appended, _horizon in results:
        if was_created:
            created += 1
        else:
            reused += 1
        if appended:
            extended += 1

    if show_progress:
        print(
            f"precreate done: created={created}, reused={reused}, "
            f"extended={extended}/{len(results)}"
        )
    return created, reused


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


def _drain_progress_queue(progress_queue, show_progress):
    if progress_queue is None or not show_progress:
        return
    while True:
        try:
            msg = progress_queue.get_nowait()
        except Empty:
            break
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "steady_batch":
            continue
        print(
            f"[steady] repeat={msg.get('sim_index')} config_index={msg.get('config_index')} "
            f"lambda={msg.get('lambda')} mu={msg.get('mu')} "
            f"batch={msg.get('batch')} n={msg.get('n')} "
            f"elapsed={msg.get('elapsed'):.3f} "
            f"total={msg.get('ex_time_total'):.6g} wait={msg.get('ex_time_wait'):.6g} "
            f"instances={msg.get('ave_instances'):.4g}",
            flush=True,
        )


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
    manager = None
    progress_queue = None
    try:
        # Avoid concurrent request-file creation races in worker processes.
        precreate_request_files(
            pending_task_specs,
            max_workers=max_workers,
            show_progress=show_progress,
            preextend=(output_root is None),
        )

        manager = mp.Manager()
        progress_queue = manager.Queue()

        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=init_progress_queue,
            initargs=(progress_queue,),
        ) as executor:
            for order_idx, (sim_index, config_idx, row) in enumerate(pending_task_specs):
                config = setup_config(row, sim_index)
                config.TASK_SIM_INDEX = sim_index
                config.TASK_CONFIG_INDEX = config_idx
                if output_root is not None:
                    task_label = f"task{order_idx}_rep{sim_index}_cfg{config_idx}"
                    config = retarget_output_files_for_benchmark(config, output_root, task_label)
                    # Autotune/profile: steady off, stop after N completions (not LIMIT_TIME:
                    # that mode also drains the whole preloaded 10k-request CSV).
                    config.STEADY_FORCE_DISABLED = True
                    profile_sim_time = float(SETTINGS.get("autotune_profile_sim_time", 30.0) or 30.0)
                    config.SIM_LIMIT = Limit.LIMIT_REQUEST
                    config.SIM_THRESHOLD = estimate_profile_request_threshold(config, profile_sim_time)
                    apply_steady_settings(config)
                future = executor.submit(simulate, config)
                futures.append(future)
                future_meta[future] = (sim_index, config_idx)

            completed = 0
            pending = set(futures)
            while pending:
                _drain_progress_queue(progress_queue, show_progress)
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
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
                        print(
                            f"[{completed}/{total_tasks}] finished repeat={sim_index} "
                            f"config_index={config_idx}",
                            flush=True,
                        )

                    worker_elapsed = summary.get("worker_elapsed_sec")
                    if worker_elapsed is not None:
                        sim_index, config_idx = future_meta[future]
                        task_elapsed_records.append((sim_index, config_idx, float(worker_elapsed)))
            _drain_progress_queue(progress_queue, show_progress)
    finally:
        for handle in summary_handles.values():
            handle.close()
        if manager is not None:
            manager.shutdown()

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

    profile_indices = select_autotune_profile_indices(config_rows, config_count)
    profile_tasks = build_task_specs(
        config_rows,
        sim_count_start,
        sim_count_end,
        round_limit=profile_round_limit,
        row_indices=profile_indices,
    )
    full_tasks = build_task_specs(config_rows, sim_count_start, sim_count_end)

    candidates = parse_candidate_workers(cpu_budget, SETTINGS.get("autotune_candidates"))
    profile_sim_time = float(SETTINGS.get("autotune_profile_sim_time", 30.0) or 30.0)
    print("=== AUTOTUNE START ===")
    print(
        f"profile_configs={len(profile_indices)}, profile_indices={profile_indices}, "
        f"profile_rounds={profile_round_limit}, profile_sim_time={profile_sim_time}, "
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
            show_progress=True,
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

def parse_args():
    parser = argparse.ArgumentParser(description="Run microservice_sim experiments.")
    parser.add_argument(
        "--generate-requests-only",
        action="store_true",
        help="Pre-generate shared request CSVs in parallel and exit (ignores SETTINGS['generate_requests_only']).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
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

    generate_requests_only = bool(args.generate_requests_only) or bool(
        SETTINGS.get("generate_requests_only", False)
    )
    autotune_enabled = bool(SETTINGS.get("autotune_enabled", False))
    autotune_only = bool(SETTINGS.get("autotune_only", False))

    if generate_requests_only:
        max_workers = resolve_max_workers(
            default_workers=min(5, cpu_budget),
            max_cap=cpu_budget,
            configured_workers=SETTINGS.get("max_workers"),
        )
        task_specs = build_task_specs(config_rows, sim_count_start, sim_count_end)
        print(
            f"generate_requests_only=True: unique streams from {len(config_rows)} configs "
            f"x {sim_count_end - sim_count_start} repeats, workers={max_workers}"
        )
        timer = time.time()
        precreate_request_files(task_specs, max_workers=max_workers, show_progress=True)
        print(f"request generation elapsed={time.time() - timer:.3f}s")
        return

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
    setattr(config, "SIM_ENABLE_SCALE_CHECK_SKIP", bool(SETTINGS.get("enable_scale_check_skip", True)))
    apply_steady_settings(config)
    step_per_time = config.SIM_STEP_PER_TIME
    _lambda = decimal_normalize(config.CONFIG_LAMBDA)
    mu = decimal_normalize(config.CONFIG_MU)
    # outfile = getOutfile(threshold, limit, _lambda, mu)
    outfile = config.OUTPUT_FILE
    sim = QueueSimulator(config.SIM_THRESHOLD, config.SIM_LIMIT, step_per_time, _lambda, mu, config)
    with open(outfile, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(RESULT_HEADER)

        sim.startSimulate()
        summary = sim.endSimulate(config.CONFIG_DEFAULT_FLG)
        sim = None
        writer.writerow(summary["result_row"])
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

