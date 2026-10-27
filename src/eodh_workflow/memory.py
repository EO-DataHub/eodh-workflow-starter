"""
Memory available to the workflow, and memory logging to diagnose out-of-memory failures in ADES.

In a Kubernetes pod, `psutil.virtual_memory()` reports the node's free memory, not the pod's limit.
Size work from `available_memory_mb()`, which also reads the container's cgroup limit.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import psutil

logger = logging.getLogger(__name__)


def get_memory_usage() -> float:
    """Get current memory usage in MB."""
    process = psutil.Process()
    memory_info = process.memory_info()
    return memory_info.rss / 1024 / 1024  # Convert to MB


def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):  # missing file, or "max" meaning no limit
        return None


def _cgroup_available_bytes(cgroup_root: Path) -> Optional[int]:
    """
    Memory left under the container's cgroup limit, or None if there is no limit.

    In a Kubernetes pod, psutil reports the node's free memory, not the pod's limit
    (the CWL ResourceRequirement `ramMax`).
    """
    for limit_file, usage_file in (
        ("memory.max", "memory.current"),  # cgroup v2
        ("memory/memory.limit_in_bytes", "memory/memory.usage_in_bytes"),  # cgroup v1
    ):
        limit = _read_int(cgroup_root / limit_file)
        usage = _read_int(cgroup_root / usage_file)
        # cgroup v1 reports "no limit" as a very large number.
        if limit is not None and usage is not None and limit < 2**60:
            return max(limit - usage, 0)
    return None


def available_memory_mb(cgroup_root: Path = Path("/sys/fs/cgroup")) -> float:
    """Memory available to this process in MB: the lower of system free memory and the cgroup headroom."""
    available = psutil.virtual_memory().available
    cgroup_available = _cgroup_available_bytes(cgroup_root)
    if cgroup_available is not None:
        available = min(available, cgroup_available)
    return available / 1024 / 1024


def log_memory_usage(stage: str = "") -> None:
    """Log current memory usage."""
    memory_mb = get_memory_usage()
    logger.info(f"Memory usage {stage}: {memory_mb:.1f} MB")


def monitor_memory_usage(interval: int = 5):
    """
    Monitor memory usage at regular intervals.

    Args:
        interval: Monitoring interval in seconds
    """

    def monitor():
        while True:
            try:
                memory_mb = get_memory_usage()
                logger.info(f"Memory monitoring: {memory_mb:.1f} MB")
                time.sleep(interval)
            except Exception as e:  # pragma: no cover - defensive logging
                logger.warning(f"Memory monitoring error: {e}")
                break

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    return monitor_thread
