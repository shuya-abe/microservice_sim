# Container / Serverless Queue Simulator

Discrete-time queueing simulator for comparing **container autoscaling** and **serverless (cold-start)** execution models.

It advances request arrivals, load balancing, processing, and scale-in/out over simulation steps, then writes latency and capacity metrics to CSV.

> Japanese documentation (detailed): [README_JP.md](README_JP.md)

---

## Features

- Two instance modes: **container** (periodic CPU-based autoscaling) and **serverless** (cold start + idle timeout)
- Poisson arrivals and exponential service times
- Multi-process experiment runner with optional worker auto-tuning
- Resume support: skips tasks whose result CSV already exists
- Hybrid event-driven step skipping for faster long runs
- CSV inputs/outputs for reproducible experiments

---

## Requirements

- Python 3.8+
- [NumPy](https://numpy.org/)

```bash
pip install numpy
```

---

## Quick Start

1. Edit experiment rows in [`config_list.csv`](config_list.csv).
2. Adjust runtime options in `SETTINGS` at the top of [`simulate.py`](simulate.py) (not environment variables).
3. Run:

```bash
python simulate.py
```

Request traces are generated under `requests/` on first use (or reused if already present). Results are written under `result/`.

### Useful `SETTINGS`

| Key | Description | Example |
|---|---|---|
| `config_file` | Experiment config CSV | `config_list.csv` |
| `sim_count_start` / `sim_count_end` | Repeat index range `[start, end)` | `0` … `10` |
| `autotune_enabled` | Benchmark and pick worker count | `True` |
| `max_workers` | Fixed worker count (`None` = policy/autotune) | `None` |
| `enable_hybrid_skip` | Skip idle steps until the next event | `True` |

---

## Architecture

```
simulate.py
  └─ Config (one row from config_list.csv)
  └─ QueueSimulator
        ├─ Generator / Sender   … request generation & timed injection
        └─ Cluster
              ├─ Balancer       … assign requests to instances
              ├─ Scaler         … scale-out/in or idle shutdown
              └─ Instance       … Container | Serverless
```

**Per simulation step:** Sender → Balancer → Scaler → each runnable Instance.

| Mode | Scale-out | Scale-in | Routing |
|---|---|---|---|
| Container | Periodic CPU utilization vs target | Periodic (keep ≥ 1 hot) | Prefer ACTIVE/WORKING with empty queue |
| Serverless | Cold start on demand | Idle timer | Hottest warm instance, else cold start |

For algorithms, state machines, and timing models, see [README_JP.md](README_JP.md).

---

## Configuration (`config_list.csv`)

One row = one experiment. Lines starting with `#` are ignored.

| Column | Meaning |
|---|---|
| `experiment_id` | Experiment ID (used in output paths) |
| `threshold` | Stop criterion value |
| `step_per_time` | Steps per unit of logical time |
| `limit` | `req` / `time` / `step` |
| `cluster_cpu` | Cluster CPU capacity limit |
| `lambda` / `mu` | Arrival rate λ / service rate μ |
| `instance_flg` | `container` or `serverless` |
| `default_instance_num` | Instance pool size |
| `default_start_instances` | Initially ACTIVE instances |
| `scale_*` / `serverless_timer` | Autoscaling / idle parameters |
| `sim_default_output_file` | Shared summary CSV path |

A legacy column layout (without `experiment_id`) is still accepted for test configs.

### Request traces (`requests/*.csv`)

| Column | Description |
|---|---|
| `id` | Request ID |
| `workload` | Initial workload |
| `start` | Arrival time (logical) |

Created automatically when missing; shared across modes for the same `(threshold, λ, μ, repeat index)`.

---

## Outputs

Each task writes three files under `result/`, and the runner appends one summary row.

| File | When written | Contents |
|---|---|---|
| `*_result.csv` | End of each task (overwrite) | Aggregate means (service / wait / total time) |
| `*_packet.csv` | End of simulation (full rewrite) | Per-request timeline |
| `*_num_instance.csv` | During the run (on change only) | Hot instance count over time |
| Summary CSV (`sim_default_output_file`) | After each completed worker | One row per finished task |

### `*_result.csv`

`step_per_time`, `total_time`, `num_steps`, `num_reqs`, `ex_time_service`, `ex_time_wait`, `ex_time_total`

### `*_packet.csv`

`id`, `processed_by`, `workload`, `start`, `end`, `time_lifetime`, `time_wait`, `time_service`

### `*_num_instance.csv`

`sim_time`, `step`, `num_hot_instances`

---

## Repository Layout

| Path | Role |
|---|---|
| `simulate.py` | Entry point, parallel runner, autotune |
| `queue_simulator.py` | Simulation engine |
| `config.py` | Config parsing & path generation |
| `generator.py` / `sender.py` | Request generation & injection |
| `cluster.py` / `balancer.py` / `scaler.py` | Cluster control plane |
| `instance.py` / `container.py` / `serverless.py` | Instance models |
| `config_list.csv` | Experiment definitions |
| `requests/` | Request traces (generated or reused) |
| `result/` | Simulation outputs |
| `program/` | Post-processing / analysis scripts (optional) |

---

## License

No license file is included yet. Add one before publishing if you intend to open-source the project.
