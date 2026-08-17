"""Cross-process progress reporting for ProcessPoolExecutor workers."""

_PROGRESS_QUEUE = None


def init_progress_queue(queue):
    global _PROGRESS_QUEUE
    _PROGRESS_QUEUE = queue


def has_progress_queue():
    return _PROGRESS_QUEUE is not None


def emit_progress(payload):
    q = _PROGRESS_QUEUE
    if q is None:
        return False
    try:
        q.put(payload)
        return True
    except Exception:
        return False
