"""Online batch statistics and steady-state detection for QueueSimulator."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _z_from_ci_level(ci_level: float) -> float:
    # Common levels; default 95%.
    table = {
        0.90: 1.6448536269514722,
        0.95: 1.959963984540054,
        0.99: 2.5758293035489004,
    }
    return table.get(float(ci_level), 1.959963984540054)


@dataclass
class RunningMoments:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def merge_from(self, other: "RunningMoments") -> None:
        if other.n == 0:
            return
        if self.n == 0:
            self.n = other.n
            self.mean = other.mean
            self.m2 = other.m2
            return
        n = self.n + other.n
        delta = other.mean - self.mean
        self.mean = (self.n * self.mean + other.n * other.mean) / n
        self.m2 = self.m2 + other.m2 + delta * delta * self.n * other.n / n
        self.n = n

    def variance(self) -> float:
        if self.n < 2:
            return 0.0
        return self.m2 / (self.n - 1)

    def stddev(self) -> float:
        return math.sqrt(self.variance())

    def ci(self, z: float) -> tuple[float, float]:
        if self.n <= 0:
            return (float("nan"), float("nan"))
        if self.n == 1:
            return (self.mean, self.mean)
        half = z * self.stddev() / math.sqrt(self.n)
        return (self.mean - half, self.mean + half)


@dataclass
class BatchAccumulator:
    t0: float
    lifetimes: RunningMoments = field(default_factory=RunningMoments)
    waits: RunningMoments = field(default_factory=RunningMoments)
    services: RunningMoments = field(default_factory=RunningMoments)
    instance_time_integral: float = 0.0
    last_integral_time: float = 0.0
    last_hot_instances: int = 0

    def __post_init__(self):
        self.last_integral_time = self.t0

    def note_instances(self, sim_time: float, hot_instances: int) -> None:
        if sim_time < self.last_integral_time:
            return
        dt = sim_time - self.last_integral_time
        if dt > 0:
            self.instance_time_integral += self.last_hot_instances * dt
        self.last_integral_time = sim_time
        self.last_hot_instances = hot_instances

    def add_completion(self, lifetime: float, wait: float, service: float) -> None:
        self.lifetimes.add(lifetime)
        self.waits.add(wait)
        self.services.add(service)

    def finalize(self, sim_time: float, z: float) -> dict:
        self.note_instances(sim_time, self.last_hot_instances)
        elapsed = max(sim_time - self.t0, 0.0)
        ave_instances = (
            self.instance_time_integral / elapsed if elapsed > 0 else float(self.last_hot_instances)
        )
        life_ci = self.lifetimes.ci(z)
        wait_ci = self.waits.ci(z)
        svc_ci = self.services.ci(z)
        return {
            "t0": self.t0,
            "t1": sim_time,
            "elapsed": elapsed,
            "n": self.lifetimes.n,
            "ex_time_total": self.lifetimes.mean,
            "ex_time_wait": self.waits.mean,
            "ex_time_service": self.services.mean,
            "ci_total_low": life_ci[0],
            "ci_total_high": life_ci[1],
            "ci_wait_low": wait_ci[0],
            "ci_wait_high": wait_ci[1],
            "ci_service_low": svc_ci[0],
            "ci_service_high": svc_ci[1],
            "ave_instances": ave_instances,
            "_life": self.lifetimes,
            "_wait": self.waits,
            "_service": self.services,
            "_instance_integral": self.instance_time_integral,
        }


def metrics_stable(prev: dict, curr: dict, rel_tol: float, eps: float = 1e-12) -> bool:
    """True if relative change is small OR 95%-style CIs overlap, for all tracked metrics."""

    def rel_ok(a, b) -> bool:
        return abs(a - b) / max(abs(b), eps) <= rel_tol

    def ci_overlap(lo_a, hi_a, lo_b, hi_b) -> bool:
        if any(map(lambda x: x != x, (lo_a, hi_a, lo_b, hi_b))):  # NaN check
            return False
        return not (hi_a < lo_b or hi_b < lo_a)

    pairs = [
        ("ex_time_total", "ci_total_low", "ci_total_high"),
        ("ex_time_wait", "ci_wait_low", "ci_wait_high"),
    ]
    for mean_key, lo_key, hi_key in pairs:
        a = float(prev[mean_key])
        b = float(curr[mean_key])
        if not (
            rel_ok(a, b)
            or ci_overlap(prev[lo_key], prev[hi_key], curr[lo_key], curr[hi_key])
        ):
            return False

    # Instance count: relative change only (no per-request CI).
    ia = float(prev["ave_instances"])
    ib = float(curr["ave_instances"])
    if not rel_ok(ia, ib):
        return False
    return True


def consecutive_stable(batches: list[dict], k: int, rel_tol: float) -> bool:
    if k < 2 or len(batches) < k:
        return False
    window = batches[-k:]
    for i in range(1, len(window)):
        if not metrics_stable(window[i - 1], window[i], rel_tol):
            return False
    return True


def merge_batches(batches: list[dict], z: float) -> dict:
    """Combine K batches into one adopted steady-state summary."""
    if not batches:
        raise ValueError("merge_batches requires at least one batch")

    life = RunningMoments()
    wait = RunningMoments()
    service = RunningMoments()
    integral = 0.0
    t0 = batches[0]["t0"]
    t1 = batches[-1]["t1"]
    for b in batches:
        life.merge_from(b["_life"])
        wait.merge_from(b["_wait"])
        service.merge_from(b["_service"])
        integral += b["_instance_integral"]

    elapsed = max(t1 - t0, 0.0)
    ave_instances = integral / elapsed if elapsed > 0 else batches[-1]["ave_instances"]
    life_ci = life.ci(z)
    wait_ci = wait.ci(z)
    svc_ci = service.ci(z)
    return {
        "t0": t0,
        "t1": t1,
        "elapsed": elapsed,
        "n": life.n,
        "ex_time_total": life.mean,
        "ex_time_wait": wait.mean,
        "ex_time_service": service.mean,
        "ci_total_low": life_ci[0],
        "ci_total_high": life_ci[1],
        "ci_wait_low": wait_ci[0],
        "ci_wait_high": wait_ci[1],
        "ci_service_low": svc_ci[0],
        "ci_service_high": svc_ci[1],
        "ave_instances": ave_instances,
        "num_merged_batches": len(batches),
    }


def resolve_batch_min_time(config) -> float:
    explicit = getattr(config, "STEADY_BATCH_MIN_TIME", None)
    if explicit is not None and float(explicit) > 0:
        return float(explicit)
    from sim_flg import Flg

    if Flg.is_serverless(config.CONFIG_INSTANCE_FLG):
        return float(config.CONFIG_SERVERLESS_TIMER)
    # Container: a few scale intervals as a default dwell window.
    return float(max(config.CONFIG_SCALE_INTERVAL * 4, 1))
