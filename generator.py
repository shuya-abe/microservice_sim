import numpy as np
import numpy.random as rd
import math
import os
import fcntl
from contextlib import contextmanager
from config import Config
from request import Request
from limit import Limit
import csv

class Generator:

    def __init__(self, step_per_time, _lambda, mu, config:Config):
        self.config = config
        self.reqs = []
        self.step_per_time = step_per_time
        self._lambda = _lambda
        self.mu = mu
        self.next_arrival_time = None
        self.next_id = 0
        self.max_loaded_id = -1
        self.last_start_time = None
        return

    def seed(self, seed_value):
        rd.seed(int(seed_value))
        return

    @contextmanager
    def _file_lock(self, path):
        """
        Exclusive lock on the request CSV inode (no sidecar .lock files).
        Safe across processes that share the same path.
        """
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        # Open/create the data file itself; flock is on the inode.
        with open(path, "a+b") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    def _sample_batch(self, n, t0):
        """Vectorized interarrival + workload. Starts are t0 + cumsum(floor(Exp)/step)."""
        n = int(n)
        if n <= 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
        intervals = np.floor(rd.exponential(1.0 / self._lambda, size=n) * self.step_per_time)
        intervals = intervals / self.step_per_time
        starts = t0 + np.cumsum(intervals)
        workloads = self.config.CONFIG_DEFAULT_CAPACITY * rd.exponential(1.0 / self.mu, size=n)
        return starts, workloads

    def _generate_arrays(self, limit, threshold):
        if limit == Limit.LIMIT_DEFAULT:
            return np.empty(0, dtype=np.int64), np.empty(0), np.empty(0)

        if limit == Limit.LIMIT_REQUEST:
            n = int(threshold)
            starts, workloads = self._sample_batch(n, 0.0)
            ids = np.arange(n, dtype=np.int64)
            return ids, workloads, starts

        if limit == Limit.LIMIT_TIMESTEP:
            t_end = float(threshold) / float(self.step_per_time)
        elif limit == Limit.LIMIT_TIME:
            t_end = float(threshold)
        else:
            return np.empty(0, dtype=np.int64), np.empty(0), np.empty(0)

        start_chunks = []
        work_chunks = []
        t0 = 0.0
        n_est = max(int(self._lambda * max(t_end, 0.0) * 1.25) + 64, 64)
        while True:
            starts, workloads = self._sample_batch(n_est, t0)
            keep = starts <= t_end
            if np.any(keep):
                start_chunks.append(starts[keep])
                work_chunks.append(workloads[keep])
                t0 = float(starts[keep][-1])
            overshoot = np.where(~keep)[0]
            if overshoot.size:
                self.next_arrival_time = float(starts[overshoot[0]])
                break
            n_est = max(n_est, 64)

        if not start_chunks:
            return np.empty(0, dtype=np.int64), np.empty(0), np.empty(0)
        starts = np.concatenate(start_chunks)
        workloads = np.concatenate(work_chunks)
        ids = np.arange(starts.size, dtype=np.int64)
        return ids, workloads, starts

    def output_arrays(self, outputfile, ids, workloads, starts, append=False):
        directory = os.path.dirname(outputfile) or "."
        os.makedirs(directory, exist_ok=True)
        exists = os.path.isfile(outputfile) and os.path.getsize(outputfile) > 0
        write_header = not (append and exists)
        mode = "ab" if (append and exists) else "wb"
        data = np.column_stack((ids, workloads, starts))
        with open(outputfile, mode) as f:
            if write_header:
                f.write(b"id,workload,start\n")
            if data.size:
                np.savetxt(f, data, delimiter=",", fmt=["%d", "%.17g", "%.17g"])

    def generate_and_write(self, outputfile, limit, threshold):
        ids, workloads, starts = self._generate_arrays(limit, threshold)
        self.output_arrays(outputfile, ids, workloads, starts, append=False)
        if starts.size:
            self.next_id = int(ids[-1]) + 1
            self.max_loaded_id = int(ids[-1])
            self.last_start_time = float(starts[-1])
        return int(starts.size)

    def outputRequests(self, outputfile):
        if not self.reqs:
            directory = os.path.dirname(outputfile) or "."
            os.makedirs(directory, exist_ok=True)
            with open(outputfile, "w", newline="") as f:
                csv.writer(f).writerow(["id", "workload", "start"])
            return
        ids = np.fromiter((r.getId() for r in self.reqs), dtype=np.int64, count=len(self.reqs))
        workloads = np.fromiter((r.getOrgWorkload() for r in self.reqs), dtype=np.float64, count=len(self.reqs))
        starts = np.fromiter((r.getStartTime() for r in self.reqs), dtype=np.float64, count=len(self.reqs))
        self.output_arrays(outputfile, ids, workloads, starts, append=False)

    def appendRequests(self, outputfile, reqs):
        if not reqs:
            return
        ids = np.fromiter((r.getId() for r in reqs), dtype=np.int64, count=len(reqs))
        workloads = np.fromiter((r.getOrgWorkload() for r in reqs), dtype=np.float64, count=len(reqs))
        starts = np.fromiter((r.getStartTime() for r in reqs), dtype=np.float64, count=len(reqs))
        self.output_arrays(outputfile, ids, workloads, starts, append=True)

    def _ingest_row(self, req_id, workload, time):
        if req_id <= self.max_loaded_id:
            return None
        request = self.createRequest(req_id, workload, time)
        self.reqs.append(request)
        self.max_loaded_id = req_id
        self.next_id = max(self.next_id, req_id + 1)
        self.last_start_time = time
        self.next_arrival_time = None
        return request

    def _append_from_arrays(self, ids, workloads, starts):
        added = []
        for req_id, workload, time in zip(ids, workloads, starts):
            request = self.createRequest(int(req_id), float(workload), float(time))
            self.reqs.append(request)
            added.append(request)
        if added:
            last_id = int(ids[-1])
            self.max_loaded_id = max(self.max_loaded_id, last_id)
            self.next_id = max(self.next_id, last_id + 1)
            self.last_start_time = float(starts[-1])
        return added

    def _read_rows_after(self, inputfile, after_id):
        added = []
        if not os.path.isfile(inputfile) or os.path.getsize(inputfile) == 0:
            return added
        try:
            data = np.loadtxt(inputfile, delimiter=",", skiprows=1, ndmin=2)
        except ValueError:
            data = np.empty((0, 3))
        if data.size == 0:
            return added
        ids = data[:, 0].astype(np.int64)
        mask = ids > after_id
        if not np.any(mask):
            return added
        return self._append_from_arrays(ids[mask], data[mask, 1], data[mask, 2])

    def inputRequests(self, inputfile):
        self._read_rows_after(inputfile, self.max_loaded_id)
        return self.reqs

    def createAllRequests(self, limit, threshold):
        ids, workloads, starts = self._generate_arrays(limit, threshold)
        self.reqs = []
        self.max_loaded_id = -1
        self.next_id = 0
        self.last_start_time = None
        if starts.size:
            self._append_from_arrays(ids, workloads, starts)
            if self.next_arrival_time is None:
                self.next_arrival_time = None
        return self.reqs

    def generateNextRequests(self, time):
        req_id = self.getNumRequests()
        workload = self.calculateWorkload4Request(self.step_per_time)
        request = self.createRequest(req_id, workload, time)
        self.reqs.append(request)
        self.max_loaded_id = max(self.max_loaded_id, req_id)
        self.next_id = max(self.next_id, req_id + 1)
        self.last_start_time = time
        time_next = self._sample_next_arrival(time)
        return time_next

    def _sample_next_arrival(self, after_time):
        return self.calculateNextRequest(after_time, self.step_per_time)

    def _ensure_next_arrival_time(self):
        if self.next_arrival_time is None:
            base = 0.0 if self.last_start_time is None else self.last_start_time
            self.next_arrival_time = self._sample_next_arrival(base)
        return self.next_arrival_time

    def generateOneRequest(self):
        """Append one new request at next_arrival_time and advance the clock."""
        time = self._ensure_next_arrival_time()
        workload = self.calculateWorkload4Request(self.step_per_time)
        request = self.createRequest(self.next_id, workload, time)
        self.reqs.append(request)
        self.max_loaded_id = max(self.max_loaded_id, self.next_id)
        self.next_id += 1
        self.last_start_time = time
        self.next_arrival_time = self._sample_next_arrival(time)
        return request

    def _peek_last_row(self, path):
        """Return (last_id, last_start) from CSV without loading the whole file."""
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size <= 0:
                return None
            read_size = min(size, 65536)
            f.seek(size - read_size)
            chunk = f.read().decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            return None
        # Drop a possibly partial first line when we seek mid-file.
        if size > read_size and len(lines) >= 2:
            lines = lines[1:]
        for line in reversed(lines):
            if line.lower().startswith("id,"):
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                return int(float(parts[0])), float(parts[2])
            except ValueError:
                continue
        return None

    def _append_generated_until(self, path, until_time, max_new, keep_in_memory):
        """Generate and append rows with start <= until_time. Caller must hold the lock."""
        remaining = max_new if max_new is not None else 10**12
        created_ids = []
        created_work = []
        created_starts = []
        while remaining > 0:
            first_t = self._ensure_next_arrival_time()
            if first_t > until_time:
                break
            dt = max(until_time - first_t, 0.0)
            n_est = int(self._lambda * dt * 1.25) + 64
            n_est = min(max(n_est, 1), remaining if remaining < 10**12 else n_est)
            n_est = min(n_est, 100000)
            first_w = self.calculateWorkload4Request(self.step_per_time)
            if n_est == 1:
                starts = np.array([first_t], dtype=np.float64)
                workloads = np.array([first_w], dtype=np.float64)
            else:
                rest_s, rest_w = self._sample_batch(n_est - 1, first_t)
                starts = np.concatenate((np.array([first_t], dtype=np.float64), rest_s))
                workloads = np.concatenate((np.array([first_w], dtype=np.float64), rest_w))
            keep = starts <= until_time
            kept = int(np.count_nonzero(keep))
            if kept:
                ids = np.arange(self.next_id, self.next_id + kept, dtype=np.int64)
                created_ids.append(ids)
                created_work.append(workloads[keep])
                created_starts.append(starts[keep])
                remaining -= kept
                self.last_start_time = float(starts[keep][-1])
                self.next_id += kept
            overshoot = np.where(~keep)[0]
            if overshoot.size:
                self.next_arrival_time = float(starts[overshoot[0]])
                break
            self.next_arrival_time = None
            if kept == 0:
                break

        if not created_ids:
            return []
        ids = np.concatenate(created_ids)
        workloads = np.concatenate(created_work)
        starts = np.concatenate(created_starts)
        self.output_arrays(path, ids, workloads, starts, append=True)
        if keep_in_memory:
            return self._append_from_arrays(ids, workloads, starts)
        self.max_loaded_id = max(self.max_loaded_id, int(ids[-1]))
        self.next_id = max(self.next_id, int(ids[-1]) + 1)
        self.last_start_time = float(starts[-1])
        return []

    def ensure_file_until(self, path, until_time, max_new=None):
        """
        Ensure shared request CSV covers start_time <= until_time without loading
        the whole file into memory. Returns number of newly appended rows.
        """
        until_time = float(until_time)
        with self._file_lock(path):
            peek = self._peek_last_row(path)
            if peek is None:
                directory = os.path.dirname(path) or "."
                os.makedirs(directory, exist_ok=True)
                if not (os.path.isfile(path) and os.path.getsize(path) > 0):
                    with open(path, "w", newline="") as f:
                        csv.writer(f).writerow(["id", "workload", "start"])
                self.next_id = 0
                self.max_loaded_id = -1
                self.last_start_time = None
                self.next_arrival_time = None
            else:
                last_id, last_start = peek
                if last_start >= until_time:
                    return 0
                self.next_id = last_id + 1
                self.max_loaded_id = last_id
                self.last_start_time = last_start
                self.next_arrival_time = None

            before_id = self.next_id
            self._append_generated_until(path, until_time, max_new, keep_in_memory=False)
            return max(0, self.next_id - before_id)

    def extendUntil(self, path, until_time, max_new=100000):
        """
        Make sure shared request CSV covers start_time <= until_time.
        Reloads rows another worker may have appended, then generates and
        appends only the remainder. Returns newly added in-memory requests.
        """
        added = []
        with self._file_lock(path):
            from_file = self._read_rows_after(path, self.max_loaded_id)
            added.extend(from_file)
            created = self._append_generated_until(path, until_time, max_new, keep_in_memory=True)
            added.extend(created)
        return added

    def ensureRequestsUntil(self, until_time, max_new=100000):
        """Generate requests with start_time <= until_time (in-memory only)."""
        created = 0
        while self._ensure_next_arrival_time() <= until_time and created < max_new:
            self.generateOneRequest()
            created += 1
        return created

    def countReqs(self):
        return len(self.reqs)

    def createRequest(self, id, workload, time):
        request = Request(id, workload, time)
        return request

    def getNumRequests(self):
        return len(self.reqs)

    def setNextRequestTime(self, time):
        self.next_request_time = time

    def calculateNextRequest(self, time, step_per_time):
        scale = 1./self._lambda
        step = math.floor(rd.exponential(scale) * step_per_time)
        return time + step / step_per_time

    def calculateWorkload4Request(self, step_per_time):
        scale = 1./self.mu
        service_time = rd.exponential(scale)
        workload = self.config.CONFIG_DEFAULT_CAPACITY * service_time
        return workload
