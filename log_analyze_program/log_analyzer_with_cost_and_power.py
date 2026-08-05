import argparse
import math
import os
import re
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError


def parse_cpu_from_prefix(prefix):
    """Extract per-instance CPU count from prefix pattern like '_64CPU_'."""
    match = re.search(r"_(\d+)CPU_", prefix)
    if not match:
        print("警告: prefixからCPU数を抽出できませんでした。CPU=1として計算します。")
        return 1.0
    return float(match.group(1))


def collect_prefixes_from_directory(input_dir):
    """Collect valid prefixes from *_packet.csv files in a directory."""
    if not os.path.isdir(input_dir):
        raise ValueError(f"指定されたフォルダが存在しません: {input_dir}")

    prefixes = []
    for name in sorted(os.listdir(input_dir)):
        if not name.endswith("_packet.csv"):
            continue

        packet_path = os.path.join(input_dir, name)
        prefix = packet_path[: -len("_packet.csv")]
        num_instance_path = f"{prefix}_num_instance.csv"

        if os.path.exists(num_instance_path):
            prefixes.append(prefix)
        else:
            print(f"警告: 対応する num_instance が無いためスキップします: {packet_path}")

    return prefixes


def _parse_instance_ids(processed_by_series):
    """Extract numeric suffix once so we do not regex-match for every timestep."""
    ids = np.full(len(processed_by_series), -1, dtype=np.int64)
    for idx, name in enumerate(processed_by_series.astype(str).to_numpy()):
        match = re.search(r"(\d+)$", name)
        if match:
            ids[idx] = int(match.group(1))
    return ids


def _pick_first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def compact_analysis_rows(analysis_df):
    if analysis_df.empty:
        return analysis_df

    state_cols = [
        "num_instances",
        "num_requests",
        "num_processing_requests",
        "num_processing_instances",
        "num_total_attached_cpus",
        "num_processing_cpus",
        "total_power_w",
    ]

    change_mask = pd.Series(False, index=analysis_df.index)
    for col in state_cols:
        change_mask |= analysis_df[col].ne(analysis_df[col].shift(1))
    change_mask.iloc[0] = True
    group_id = change_mask.cumsum()
    grouped_df = analysis_df.assign(_group_id=group_id)

    compact_df = grouped_df.groupby("_group_id", as_index=False).agg(
        timestep=("timestep", "last"),
        time=("time", "last"),
        num_instances=("num_instances", "last"),
        cpu_per_instance=("cpu_per_instance", "last"),
        container_mem_gb_per_instance=("container_mem_gb_per_instance", "last"),
        lambda_mem_gb_per_instance=("lambda_mem_gb_per_instance", "last"),
        num_requests=("num_requests", "last"),
        num_processing_requests=("num_processing_requests", "last"),
        num_processing_instances=("num_processing_instances", "last"),
        num_total_attached_cpus=("num_total_attached_cpus", "last"),
        num_processing_cpus=("num_processing_cpus", "last"),
        cost_a_step=("cost_a_step", "sum"),
        cost_b_step=("cost_b_step", "sum"),
        total_power_w=("total_power_w", "mean"),
        total_power_wh=("total_power_wh", "sum"),
    )

    compact_df["cum_cost_a"] = compact_df["cost_a_step"].cumsum()
    compact_df["cum_cost_b"] = compact_df["cost_b_step"].cumsum()
    compact_df["total_cost_cum"] = compact_df["cum_cost_a"] + compact_df["cum_cost_b"]
    compact_df["cumulative_power_wh"] = compact_df["total_power_wh"].cumsum()
    return compact_df


def _lambda_compute_cost_with_tiers(gb_rate, dt, total_gb_seconds, tiers):
    """Integrate Lambda compute cost over dt with tier boundaries in GB-seconds."""
    if gb_rate <= 0.0 or dt <= 0.0:
        return 0.0, total_gb_seconds

    remaining_dt = dt
    cur_total = total_gb_seconds
    total_cost = 0.0

    while remaining_dt > 0.0:
        unit_price = tiers[-1][1]
        tier_limit = float("inf")
        for limit, price in tiers:
            if cur_total <= limit:
                unit_price = price
                tier_limit = limit
                break

        if math.isinf(tier_limit):
            gb_in_segment = gb_rate * remaining_dt
            total_cost += gb_in_segment * unit_price
            cur_total += gb_in_segment
            break

        gb_to_limit = max(0.0, tier_limit - cur_total)
        if gb_to_limit <= 0.0:
            # Exactly at tier boundary; move to next tier.
            cur_total = tier_limit + 1e-12
            continue

        dt_to_limit = gb_to_limit / gb_rate
        segment_dt = min(remaining_dt, dt_to_limit)
        gb_in_segment = gb_rate * segment_dt
        total_cost += gb_in_segment * unit_price
        cur_total += gb_in_segment
        remaining_dt -= segment_dt

    return total_cost, cur_total


def _build_scaling_state(scaling_df_sorted, scaling_time_col, scaling_num_col, initial_instances, startup_time_sec, shutdown_time_sec):
    """Precompute scaling events and startup/shutdown transition metadata."""
    scaling_events = []
    startup_at = {}
    shutdown_at = {}
    startup_ends = []
    shutdown_ends = []

    prev_num = int(initial_instances)
    for row in scaling_df_sorted.itertuples(index=False):
        row_time = float(getattr(row, scaling_time_col))
        row_num_instances = int(getattr(row, scaling_num_col))
        if not math.isfinite(row_time):
            continue

        new_num = row_num_instances
        scaling_events.append((row_time, new_num))

        if new_num > prev_num:
            for inst_id in range(prev_num, new_num):
                startup_at[inst_id] = row_time
                startup_ends.append((row_time + startup_time_sec, inst_id))

        if new_num < prev_num:
            for inst_id in range(new_num, prev_num):
                shutdown_at[inst_id] = row_time
                shutdown_ends.append((row_time + shutdown_time_sec, inst_id))

        prev_num = new_num

    scaling_events.sort(key=lambda x: x[0])
    startup_ends.sort(key=lambda x: x[0])
    shutdown_ends.sort(key=lambda x: x[0])
    return scaling_events, startup_at, shutdown_at, startup_ends, shutdown_ends


def analyze_logs(prefix, steps_per_second, compact_output=True, max_timesteps=5_000_000, generate_plots=False):
    request_log_file = f"{prefix}_packet.csv"
    scaling_log_file = f"{prefix}_num_instance.csv"
    output_csv_file = f"{prefix}_analysis.csv"

    output_instances_pdf = f"{prefix}_instances.pdf"
    output_requests_pdf = f"{prefix}_requests.pdf"
    output_costs_pdf = f"{prefix}_costs_cumulative.pdf"
    output_cost_breakdown_pdf = f"{prefix}_cost_breakdown.pdf"
    output_power_pdf = f"{prefix}_power_consumption.pdf"
    output_cumulative_power_pdf = f"{prefix}_cumulative_power.pdf"
    output_cpus_pdf = f"{prefix}_cpus.pdf"

    if not os.path.exists(request_log_file) or not os.path.exists(scaling_log_file):
        print(
            "エラー: 必要なログファイルが見つかりません。"
            f" request={request_log_file}, num_instance={scaling_log_file}"
        )
        return

    # --- Pricing constants ---
    ECS_VCPU_PER_HOUR_USD = 0.04048
    ECS_MEM_GB_PER_HOUR_USD = 0.004445
    LAMBDA_REQ_UNIT_USD = 0.20 / 1_000_000
    LAMBDA_TIERS = [
        (6 * 10**9, 0.0000166667),
        (15 * 10**9, 0.0000150000),
        (float("inf"), 0.0000133334),
    ]

    # --- Power consumption model constants ---
    # P = P_base + N_active * P_active + N_idle * P_idle
    CONTAINER_BASE_POWER_W = 10.0
    SERVERLESS_BASE_POWER_W = 3.0
    CPU_EXEC_POWER_W = 10.0
    CPU_IDLE_POWER_W = CPU_EXEC_POWER_W * 0.1  # Idle CPU consumes 10% of active CPU power
    SERVERLESS_STARTUP_TIME_SEC = 1.0
    SERVERLESS_SHUTDOWN_TIME_SEC = 1.0
    CONTAINER_STARTUP_TIME_SEC = 30.0
    CONTAINER_SHUTDOWN_TIME_SEC = 30.0

    cpu_per_instance = parse_cpu_from_prefix(prefix)
    container_mem_gb_per_instance = cpu_per_instance * 2.0
    lambda_mem_mb_per_instance = cpu_per_instance * 1769.0
    lambda_mem_gb_per_instance = lambda_mem_mb_per_instance / 1024.0

    ecs_vcpu_per_sec_usd = ECS_VCPU_PER_HOUR_USD / 3600.0
    ecs_mem_gb_per_sec_usd = ECS_MEM_GB_PER_HOUR_USD / 3600.0

    try:
        requests_df = pd.read_csv(request_log_file)
    except EmptyDataError:
        print(f"警告: 空のpacketログのためスキップします: {request_log_file}")
        requests_df = pd.DataFrame(columns=["start", "end", "time_wait", "processed_by"])

    try:
        scaling_df = pd.read_csv(scaling_log_file)
    except EmptyDataError:
        print(f"警告: 空のnum_instanceログとして扱います: {scaling_log_file}")
        scaling_df = pd.DataFrame(columns=["sim_time", "step", "num_hot_instances"])

    scaling_time_col = _pick_first_existing_column(scaling_df, ["time", "sim_time"])
    scaling_step_col = _pick_first_existing_column(scaling_df, ["step"])
    scaling_num_col = _pick_first_existing_column(scaling_df, ["num_instances", "num_hot_instances"])
    if scaling_time_col is None or scaling_step_col is None or scaling_num_col is None:
        scaling_df = pd.read_csv(scaling_log_file, header=None, names=["time", "step", "num_instances"])
        scaling_time_col, scaling_step_col, scaling_num_col = "time", "step", "num_instances"

    # Pre-convert once to avoid repeated DataFrame filtering in timestep loop.
    req_start = pd.to_numeric(requests_df["start"], errors="coerce").to_numpy(dtype=float)
    req_end = pd.to_numeric(requests_df["end"], errors="coerce").to_numpy(dtype=float)
    req_wait = pd.to_numeric(requests_df["time_wait"], errors="coerce").to_numpy(dtype=float)
    req_proc_start = req_start + req_wait
    req_processed_col = _pick_first_existing_column(requests_df, ["processedBy", "processed_by"])
    if req_processed_col is None:
        raise ValueError(f"processedBy/processed_by column not found: {request_log_file}")

    req_instance_id = _parse_instance_ids(requests_df[req_processed_col])

    is_container = "container" in prefix.lower()
    initial_instances = 1 if is_container else 0
    base_power_w = CONTAINER_BASE_POWER_W if is_container else SERVERLESS_BASE_POWER_W
    startup_time_sec = CONTAINER_STARTUP_TIME_SEC if is_container else SERVERLESS_STARTUP_TIME_SEC
    shutdown_time_sec = CONTAINER_SHUTDOWN_TIME_SEC if is_container else SERVERLESS_SHUTDOWN_TIME_SEC

    # Event-driven integration:
    # state is treated as constant on each interval [t_i, t_{i+1}), where t_i are
    # request/scaling/power-transition event timestamps.
    scaling_df_sorted = scaling_df.sort_values(by=scaling_time_col)
    scaling_events, instance_startup_times, instance_shutdown_times, startup_ends, shutdown_ends = _build_scaling_state(
        scaling_df_sorted,
        scaling_time_col,
        scaling_num_col,
        initial_instances,
        startup_time_sec,
        shutdown_time_sec,
    )

    finite_req_start = req_start[np.isfinite(req_start)]
    finite_req_end = req_end[np.isfinite(req_end)]
    finite_req_proc_start = req_proc_start[np.isfinite(req_proc_start)]
    scaling_times = np.array([t for t, _ in scaling_events], dtype=float) if scaling_events else np.array([], dtype=float)

    max_request_end = float(np.max(finite_req_end)) if finite_req_end.size > 0 else 0.0
    max_scaling_time = float(np.max(scaling_times)) if scaling_times.size > 0 else 0.0
    simulation_end_time = max(max_request_end, max_scaling_time)
    if simulation_end_time <= 0.0:
        print("警告: シミュレーション長が0です。")
        analysis_df = pd.DataFrame(
            [
                {
                    "timestep": 0,
                    "time": 0.0,
                    "num_instances": initial_instances,
                    "cpu_per_instance": cpu_per_instance,
                    "container_mem_gb_per_instance": container_mem_gb_per_instance,
                    "lambda_mem_gb_per_instance": lambda_mem_gb_per_instance,
                    "num_requests": 0,
                    "num_processing_requests": 0,
                    "num_processing_instances": 0,
                    "num_total_attached_cpus": initial_instances * cpu_per_instance,
                    "num_processing_cpus": 0.0,
                    "cost_a_step": 0.0,
                    "cost_b_step": 0.0,
                    "total_power_w": initial_instances * base_power_w + initial_instances * cpu_per_instance * CPU_IDLE_POWER_W,
                    "total_power_wh": 0.0,
                    "cum_cost_a": 0.0,
                    "cum_cost_b": 0.0,
                    "total_cost_cum": 0.0,
                    "cumulative_power_wh": 0.0,
                }
            ]
        )
    else:
        event_time_parts = [
            np.array([0.0, simulation_end_time], dtype=float),
            finite_req_start,
            finite_req_end,
            finite_req_proc_start,
            scaling_times,
        ]
        if startup_ends:
            event_time_parts.append(np.array([t for t, _ in startup_ends], dtype=float))
        if shutdown_ends:
            event_time_parts.append(np.array([t for t, _ in shutdown_ends], dtype=float))

        event_times = np.unique(np.concatenate(event_time_parts))
        event_times = event_times[np.isfinite(event_times)]
        event_times = event_times[event_times >= 0.0]
        event_times.sort()

        if event_times.size < 2:
            event_times = np.array([0.0, simulation_end_time], dtype=float)

        active_evt_times = np.concatenate([finite_req_start, finite_req_end])
        active_evt_delta = np.concatenate([
            np.ones(finite_req_start.size, dtype=np.int64),
            -np.ones(finite_req_end.size, dtype=np.int64),
        ])
        active_order = np.argsort(active_evt_times)
        active_evt_times = active_evt_times[active_order]
        active_evt_delta = active_evt_delta[active_order]

        proc_evt_times = np.concatenate([finite_req_proc_start, finite_req_end])
        proc_evt_delta = np.concatenate([
            np.ones(finite_req_proc_start.size, dtype=np.int64),
            -np.ones(finite_req_end.size, dtype=np.int64),
        ])
        proc_order = np.argsort(proc_evt_times)
        proc_evt_times = proc_evt_times[proc_order]
        proc_evt_delta = proc_evt_delta[proc_order]

        valid_proc_mask = (req_instance_id >= 0) & np.isfinite(req_proc_start) & np.isfinite(req_end)
        inst_evt_times = np.concatenate([req_proc_start[valid_proc_mask], req_end[valid_proc_mask]])
        inst_evt_ids = np.concatenate([req_instance_id[valid_proc_mask], req_instance_id[valid_proc_mask]])
        inst_evt_delta = np.concatenate([
            np.ones(np.count_nonzero(valid_proc_mask), dtype=np.int64),
            -np.ones(np.count_nonzero(valid_proc_mask), dtype=np.int64),
        ])
        inst_order = np.argsort(inst_evt_times)
        inst_evt_times = inst_evt_times[inst_order]
        inst_evt_ids = inst_evt_ids[inst_order]
        inst_evt_delta = inst_evt_delta[inst_order]

        proc_start_sorted = np.sort(finite_req_proc_start)

        scaling_idx = 0
        active_idx = 0
        proc_idx = 0
        inst_idx = 0
        startup_end_idx = 0
        shutdown_end_idx = 0

        current_num_instances = int(initial_instances)
        current_num_active_requests = 0
        current_num_processing_requests = 0
        proc_req_count_by_instance = {}
        current_num_processing_instances = 0
        current_num_processing_cpus = 0.0
        startup_active_ids = set()
        shutdown_active_ids = set()

        total_gb_seconds = 0.0
        cum_cost_a = 0.0
        cum_cost_b = 0.0
        cumulative_power_wh = 0.0
        rows = []

        for i in range(event_times.size - 1):
            t0 = float(event_times[i])
            t1 = float(event_times[i + 1])
            if t1 <= t0:
                continue

            # Apply scaling changes effective at t0.
            while scaling_idx < len(scaling_events) and scaling_events[scaling_idx][0] == t0:
                current_num_instances = int(scaling_events[scaling_idx][1])
                scaling_idx += 1

            # Apply request activity deltas at t0.
            while active_idx < active_evt_times.size and active_evt_times[active_idx] == t0:
                current_num_active_requests += int(active_evt_delta[active_idx])
                active_idx += 1

            while proc_idx < proc_evt_times.size and proc_evt_times[proc_idx] == t0:
                current_num_processing_requests += int(proc_evt_delta[proc_idx])
                proc_idx += 1

            # Apply per-instance processing deltas at t0.
            while inst_idx < inst_evt_times.size and inst_evt_times[inst_idx] == t0:
                inst_id = int(inst_evt_ids[inst_idx])
                delta = int(inst_evt_delta[inst_idx])
                prev_count = proc_req_count_by_instance.get(inst_id, 0)
                new_count = prev_count + delta
                if new_count < 0:
                    new_count = 0

                prev_cpu = min(prev_count, cpu_per_instance)
                new_cpu = min(new_count, cpu_per_instance)
                current_num_processing_cpus += (new_cpu - prev_cpu)

                if prev_count == 0 and new_count > 0:
                    current_num_processing_instances += 1
                elif prev_count > 0 and new_count == 0:
                    current_num_processing_instances -= 1

                if new_count > 0:
                    proc_req_count_by_instance[inst_id] = new_count
                else:
                    proc_req_count_by_instance.pop(inst_id, None)

                inst_idx += 1

            # Transition windows start/end events for power model.
            while startup_end_idx < len(startup_ends) and startup_ends[startup_end_idx][0] == t0:
                startup_active_ids.discard(startup_ends[startup_end_idx][1])
                startup_end_idx += 1

            while shutdown_end_idx < len(shutdown_ends) and shutdown_ends[shutdown_end_idx][0] == t0:
                shutdown_active_ids.discard(shutdown_ends[shutdown_end_idx][1])
                shutdown_end_idx += 1

            while scaling_idx > 0 and scaling_events[scaling_idx - 1][0] == t0:
                # no-op; scaling metadata already prepared in _build_scaling_state.
                break

            # Add newly started/stopping instance IDs at current t0.
            for inst_id, st in instance_startup_times.items():
                if st == t0:
                    startup_active_ids.add(inst_id)
            for inst_id, st in instance_shutdown_times.items():
                if st == t0:
                    shutdown_active_ids.add(inst_id)

            dt = t1 - t0
            num_inst = max(0, int(current_num_instances))
            num_active = max(0, int(current_num_active_requests))
            num_proc_req = max(0, int(current_num_processing_requests))
            num_proc_inst = max(0, int(current_num_processing_instances))
            num_attached_cpus = num_inst * cpu_per_instance
            num_proc_cpus = max(0.0, float(current_num_processing_cpus))

            # Cost calculation for interval [t0, t1)
            if is_container:
                step_a = num_inst * dt * (ecs_vcpu_per_sec_usd * cpu_per_instance)
                step_b = num_inst * dt * (ecs_mem_gb_per_sec_usd * container_mem_gb_per_instance)
            else:
                gb_rate = num_proc_inst * lambda_mem_gb_per_instance
                step_a, total_gb_seconds = _lambda_compute_cost_with_tiers(gb_rate, dt, total_gb_seconds, LAMBDA_TIERS)
                left = int(np.searchsorted(proc_start_sorted, t0, side="left"))
                right = int(np.searchsorted(proc_start_sorted, t1, side="left"))
                new_req_count = max(0, right - left)
                step_b = new_req_count * LAMBDA_REQ_UNIT_USD

            # Power calculation for interval [t0, t1)
            # P = P_base + N_active * P_active + N_idle * P_idle
            P_base = num_inst * base_power_w
            P_active = num_proc_cpus * CPU_EXEC_POWER_W
            total_cpus = num_inst * cpu_per_instance
            idle_cpus = total_cpus - num_proc_cpus
            P_idle = idle_cpus * CPU_IDLE_POWER_W
            step_total_power_w = P_base + P_active + P_idle

            step_total_power_wh = step_total_power_w * (dt / 3600.0)

            cum_cost_a += step_a
            cum_cost_b += step_b
            cumulative_power_wh += step_total_power_wh

            rows.append(
                {
                    "timestep": len(rows),
                    "time": t1,
                    "num_instances": num_inst,
                    "cpu_per_instance": cpu_per_instance,
                    "container_mem_gb_per_instance": container_mem_gb_per_instance,
                    "lambda_mem_gb_per_instance": lambda_mem_gb_per_instance,
                    "num_requests": num_active,
                    "num_processing_requests": num_proc_req,
                    "num_processing_instances": num_proc_inst,
                    "num_total_attached_cpus": num_attached_cpus,
                    "num_processing_cpus": num_proc_cpus,
                    "cost_a_step": step_a,
                    "cost_b_step": step_b,
                    "total_power_w": step_total_power_w,
                    "total_power_wh": step_total_power_wh,
                    "cum_cost_a": cum_cost_a,
                    "cum_cost_b": cum_cost_b,
                    "total_cost_cum": cum_cost_a + cum_cost_b,
                    "cumulative_power_wh": cumulative_power_wh,
                }
            )

        analysis_df = pd.DataFrame(rows)

    if analysis_df.empty:
        print(f"警告: 出力対象のイベントがありません: {prefix}")

    if compact_output:
        analysis_df = compact_analysis_rows(analysis_df)

    analysis_df.to_csv(output_csv_file, index=False)

    if generate_plots:
        # Graphs
        fig1 = plt.figure(figsize=(10, 6))
        ax1 = fig1.add_subplot(1, 1, 1)
        ax1.plot(analysis_df["time"], analysis_df["num_instances"], label="num of instances", color="blue")
        ax1.plot(
            analysis_df["time"],
            analysis_df["num_processing_instances"],
            label="num of processing instances",
            color="red",
            linestyle="--",
        )
        ax1.set_xlabel("time [s]")
        ax1.set_ylabel("num of instances")
        ax1.legend()
        ax1.grid(True)
        fig1.tight_layout()
        fig1.savefig(output_instances_pdf)
        plt.close(fig1)

        fig2 = plt.figure(figsize=(10, 6))
        ax2 = fig2.add_subplot(1, 1, 1)
        ax2.plot(analysis_df["time"], analysis_df["num_requests"], label="num of requests", color="green")
        ax2.plot(
            analysis_df["time"],
            analysis_df["num_processing_requests"],
            label="num of processing requests",
            color="purple",
            linestyle=":",
        )
        ax2.set_xlabel("time [s]")
        ax2.set_ylabel("num of requests")
        ax2.legend()
        ax2.grid(True)
        fig2.tight_layout()
        fig2.savefig(output_requests_pdf)
        plt.close(fig2)

        fig_cpu, ax_cpu = plt.subplots(figsize=(10, 6))
        ax_cpu.plot(
            analysis_df["time"],
            analysis_df["num_total_attached_cpus"],
            color="navy",
            linewidth=2,
            label="Total attached CPUs (running instances * CPU per instance)",
        )
        ax_cpu.plot(
            analysis_df["time"],
            analysis_df["num_processing_cpus"],
            color="orange",
            linewidth=2,
            linestyle="--",
            label="CPUs processing requests",
        )
        ax_cpu.set_xlabel("Time [s]")
        ax_cpu.set_ylabel("Number of CPUs")
        ax_cpu.set_title("Attached CPUs vs Processing CPUs")
        ax_cpu.grid(True)
        ax_cpu.legend()
        fig_cpu.tight_layout()
        fig_cpu.savefig(output_cpus_pdf)
        plt.close(fig_cpu)

        fig3, ax3 = plt.subplots(figsize=(10, 6))
        ax3.plot(analysis_df["time"], analysis_df["total_cost_cum"], color="black", linewidth=2, label="Total Cost")
        ax3.set_xlabel("Time [s]")
        ax3.set_ylabel("Cost [USD]")
        ax3.set_title(f"Cumulative Cost ({'Container' if is_container else 'Serverless'})")
        ax3.grid(True)
        ax3.legend()
        fig3.savefig(output_costs_pdf)
        plt.close(fig3)

        fig4, ax4 = plt.subplots(figsize=(10, 6))
        label_a = "CPU Cost" if is_container else "Computing Cost"
        label_b = "Memory Cost" if is_container else "Request Cost"
        ax4.stackplot(
            analysis_df["time"],
            analysis_df["cum_cost_a"],
            analysis_df["cum_cost_b"],
            labels=[label_a, label_b],
            alpha=0.7,
        )
        ax4.set_xlabel("Time [s]")
        ax4.set_ylabel("Cost [USD]")
        ax4.set_title("Cost Breakdown")
        ax4.legend(loc="upper left")
        ax4.grid(True)
        fig4.savefig(output_cost_breakdown_pdf)
        plt.close(fig4)

        fig5, ax5 = plt.subplots(figsize=(10, 6))
        ax5.plot(analysis_df["time"], analysis_df["total_power_w"], color="red", linewidth=2)
        ax5.set_xlabel("Time [s]")
        ax5.set_ylabel("Power [W]")
        ax5.set_title(f"Power Consumption ({'Container' if is_container else 'Serverless'})")
        ax5.grid(True)
        fig5.savefig(output_power_pdf)
        plt.close(fig5)

        fig6, ax6 = plt.subplots(figsize=(10, 6))
        ax6.plot(analysis_df["time"], analysis_df["cumulative_power_wh"], color="darkred", linewidth=2)
        ax6.set_xlabel("Time [s]")
        ax6.set_ylabel("Energy [Wh]")
        ax6.set_title("Cumulative Energy")
        ax6.grid(True)
        fig6.savefig(output_cumulative_power_pdf)
        plt.close(fig6)

    print(f"完了: {output_csv_file}")
    print(
        f"CPU={cpu_per_instance}, base_power={base_power_w}W, active_cpu_power={CPU_EXEC_POWER_W}W, idle_cpu_power={CPU_IDLE_POWER_W}W,"
        f" events={len(analysis_df)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze logs with cost and power consumption.")
    parser.add_argument("prefixes", nargs="*", help="解析対象prefix（従来方式）")
    parser.add_argument(
        "--input_dir",
        type=str,
        default=None,
        help="フォルダ内の *_packet.csv と対応する *_num_instance.csv を自動探索して一括実行",
    )
    parser.add_argument("--steps_per_second", type=int, required=True)
    parser.add_argument(
        "--compact_output",
        action="store_true",
        default=True,
        help="変動が無い区間を圧縮して分析CSVとグラフを軽量化します（デフォルト有効）。",
    )
    parser.add_argument(
        "--full_output",
        action="store_true",
        help="圧縮を無効化し、全ステップで出力します。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="並列ワーカー数。1で逐次実行（デフォルト）。2以上でprefixごとに並列化します。",
    )
    parser.add_argument(
        "--generate_plots",
        action="store_true",
        help="指定時のみPDFグラフを生成します（デフォルトは解析CSVのみ出力）。",
    )
    parser.add_argument(
        "--max_timesteps",
        type=int,
        default=5_000_000,
        help="互換オプション（イベント駆動集計では未使用）。",
    )
    args = parser.parse_args()

    target_prefixes = []

    if args.input_dir:
        try:
            target_prefixes.extend(collect_prefixes_from_directory(args.input_dir))
        except ValueError as e:
            parser.error(str(e))

    if args.prefixes:
        target_prefixes.extend(args.prefixes)

    cleaned_prefixes = []
    seen = set()
    for p in target_prefixes:
        cleaned = p.replace("_packet.csv", "").replace("_result.csv", "").replace("_num_instance.csv", "")
        if cleaned not in seen:
            cleaned_prefixes.append(cleaned)
            seen.add(cleaned)

    if not cleaned_prefixes:
        parser.error("解析対象がありません。prefixes か --input_dir を指定してください。")

    validated_prefixes = []
    skipped_prefixes = []
    for cleaned in cleaned_prefixes:
        request_log_file = f"{cleaned}_packet.csv"
        scaling_log_file = f"{cleaned}_num_instance.csv"
        if os.path.exists(request_log_file) and os.path.exists(scaling_log_file):
            validated_prefixes.append(cleaned)
        else:
            skipped_prefixes.append(cleaned)

    if skipped_prefixes:
        print(f"警告: 対応ログ不足のため {len(skipped_prefixes)} 件をスキップします。")
        for s in skipped_prefixes:
            print(f"  - {s}")

    if not validated_prefixes:
        parser.error("有効な解析対象がありません。_packet.csv と _num_instance.csv の両方が必要です。")

    print(f"解析対象件数: {len(validated_prefixes)}")
    compact_output = args.compact_output and (not args.full_output)
    max_timesteps = args.max_timesteps if args.max_timesteps > 0 else 0
    generate_plots = args.generate_plots
    if args.workers > 1 and len(validated_prefixes) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    analyze_logs,
                    cleaned,
                    args.steps_per_second,
                    compact_output,
                    max_timesteps,
                    generate_plots,
                ): cleaned
                for cleaned in validated_prefixes
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"エラー: {target} の解析中に例外が発生しました: {e}")
    else:
        for cleaned in validated_prefixes:
            analyze_logs(cleaned, args.steps_per_second, compact_output, max_timesteps, generate_plots)
