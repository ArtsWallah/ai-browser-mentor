"""
Lightweight memory diagnostic helper for AI Browser Mentor.

Measures process RSS, peak RSS, host system memory, and container-level cgroup
metrics (cgroup v2 and v1) without third-party dependencies.

Safe for production:
- Disabled by default (configurable via ENABLE_MEMORY_DIAGNOSTICS).
- Never logs sensitive data, page content, model weights, or API keys.
- Handles missing or restricted /proc and /sys/fs/cgroup files gracefully.
- Never divides by zero or crashes on invalid/unlimited limits.
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.memory_diagnostics")

ENV_ENABLE_MEMORY_DIAGNOSTICS = "ENABLE_MEMORY_DIAGNOSTICS"
ENV_PROC_ROOT = "PROC_ROOT"
ENV_CGROUP_ROOT = "CGROUP_ROOT"
DEFAULT_CGROUP_ROOT = "/sys/fs/cgroup"

# Cgroup v1 kernel PAGE_COUNTER_MAX threshold (~9.22 Exabytes)
# Limits at or above this threshold represent unlimited container memory
CGROUP_UNLIMITED_THRESHOLD_BYTES = 1 << 60

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def is_memory_diagnostics_enabled() -> bool:
    """Check whether memory diagnostics logging is enabled via environment."""
    val = os.getenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, "").strip().lower()
    return val in _TRUTHY_VALUES


def _safe_is_file(path: Path) -> bool:
    """Safely check if path is a file without raising permissions or OS errors."""
    try:
        return path.is_file()
    except (OSError, PermissionError):
        return False


def _read_cgroup_file(path: Path) -> str | None:
    """Read a cgroup sysfs file safely, returning stripped string or None."""
    try:
        if _safe_is_file(path):
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, PermissionError):
        pass
    return None


def _parse_cgroup_bytes(val_str: str | None) -> int | None:
    """
    Parse a cgroup byte value string into an integer.
    Returns None if val_str is None, empty, 'max', non-numeric, negative,
    or represents unlimited kernel values (>= CGROUP_UNLIMITED_THRESHOLD_BYTES).
    """
    if not val_str:
        return None
    cleaned = val_str.strip().lower()
    if cleaned == "max":
        return None
    try:
        val = int(cleaned)
        if val < 0 or val >= CGROUP_UNLIMITED_THRESHOLD_BYTES:
            return None
        return val
    except ValueError:
        return None


def read_cgroup_memory_stats(cgroup_root: str | Path | None = None) -> dict[str, Any]:
    """
    Read container-level memory metrics from cgroup v2 or cgroup v1 interfaces.

    Returns dict with keys:
        - container_memory_used_mb: float | None
        - container_memory_limit_mb: float | None
        - container_memory_peak_mb: float | None
        - container_memory_percent: float | None
    """
    result: dict[str, Any] = {
        "container_memory_used_mb": None,
        "container_memory_limit_mb": None,
        "container_memory_peak_mb": None,
        "container_memory_percent": None,
    }

    root = Path(cgroup_root or os.getenv(ENV_CGROUP_ROOT, DEFAULT_CGROUP_ROOT))

    used_bytes: int | None = None
    limit_bytes: int | None = None
    peak_bytes: int | None = None
    has_limit_defined: bool = False

    # 1. Check Cgroup v2 (/sys/fs/cgroup/memory.*)
    v2_current_file = root / "memory.current"
    v2_max_file = root / "memory.max"
    v2_peak_file = root / "memory.peak"

    if _safe_is_file(v2_current_file) or _safe_is_file(v2_max_file):
        curr_str = _read_cgroup_file(v2_current_file)
        max_str = _read_cgroup_file(v2_max_file)
        peak_str = _read_cgroup_file(v2_peak_file)

        used_bytes = _parse_cgroup_bytes(curr_str)
        if max_str is not None:
            has_limit_defined = True
            # Explicitly check for "max" or non-numeric
            if max_str.strip().lower() == "max":
                limit_bytes = None
            else:
                try:
                    raw_val = int(max_str.strip())
                    if raw_val >= 0:
                        limit_bytes = _parse_cgroup_bytes(max_str)
                        if raw_val == 0:
                            limit_bytes = 0
                except ValueError:
                    limit_bytes = None

        peak_bytes = _parse_cgroup_bytes(peak_str)

    else:
        # 2. Check Cgroup v1 (/sys/fs/cgroup/memory/memory.* or root/memory.*)
        v1_dirs = [
            root / "memory",
            root,
        ]
        for candidate_dir in v1_dirs:
            v1_usage_file = candidate_dir / "memory.usage_in_bytes"
            v1_limit_file = candidate_dir / "memory.limit_in_bytes"
            v1_peak_file = candidate_dir / "memory.max_usage_in_bytes"

            if _safe_is_file(v1_usage_file) or _safe_is_file(v1_limit_file):
                usage_str = _read_cgroup_file(v1_usage_file)
                limit_str = _read_cgroup_file(v1_limit_file)
                peak_str = _read_cgroup_file(v1_peak_file)

                used_bytes = _parse_cgroup_bytes(usage_str)
                if limit_str is not None:
                    has_limit_defined = True
                    try:
                        raw_val = int(limit_str.strip())
                        if raw_val >= 0:
                            limit_bytes = _parse_cgroup_bytes(limit_str)
                            if raw_val == 0:
                                limit_bytes = 0
                    except ValueError:
                        limit_bytes = None

                peak_bytes = _parse_cgroup_bytes(peak_str)
                break

    # Convert bytes to MB
    if used_bytes is not None and used_bytes >= 0:
        result["container_memory_used_mb"] = round(used_bytes / (1024.0 * 1024.0), 2)

    if limit_bytes is not None and limit_bytes >= 0:
        result["container_memory_limit_mb"] = round(limit_bytes / (1024.0 * 1024.0), 2)
    elif has_limit_defined:
        # Limit was explicitly defined as "max" or >= unlimited threshold
        result["container_memory_limit_mb"] = None

    if peak_bytes is not None and peak_bytes >= 0:
        result["container_memory_peak_mb"] = round(peak_bytes / (1024.0 * 1024.0), 2)

    # Calculate percentage safely (never divide by zero)
    if (
        used_bytes is not None
        and limit_bytes is not None
        and limit_bytes > 0
        and used_bytes >= 0
    ):
        result["container_memory_percent"] = round((used_bytes / limit_bytes) * 100.0, 2)

    return result


def _parse_proc_status_content(content: str) -> dict[str, int]:
    """Parse /proc/self/status content into metric dictionary in kB."""
    metrics: dict[str, int] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        parts = val.strip().split()
        if parts:
            first = parts[0]
            if first.isdigit():
                metrics[key] = int(first)
    return metrics


def _parse_proc_meminfo_content(content: str) -> dict[str, int]:
    """Parse /proc/meminfo content into metric dictionary in kB."""
    metrics: dict[str, int] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        parts = val.strip().split()
        if parts:
            first = parts[0]
            if first.isdigit():
                metrics[key] = int(first)
    return metrics


def read_proc_status(proc_root: str | Path | None = None) -> dict[str, int]:
    """
    Read and parse process status from /proc/self/status (or configured proc_root).
    Returns a dict with metric names as keys and values in kB.
    Returns empty dict if /proc is not available or readable.
    """
    root = Path(proc_root or os.getenv(ENV_PROC_ROOT, "/proc"))
    candidate_paths = [
        root / "self" / "status",
        root / "status",
    ]
    for p in candidate_paths:
        try:
            if _safe_is_file(p):
                content = p.read_text(encoding="utf-8", errors="replace")
                return _parse_proc_status_content(content)
        except (OSError, PermissionError):
            continue
    return {}


def read_proc_meminfo(proc_root: str | Path | None = None) -> dict[str, int]:
    """
    Read and parse system memory info from /proc/meminfo (or configured proc_root).
    Returns a dict with metric names as keys and values in kB.
    Returns empty dict if /proc/meminfo is not available or readable.
    """
    root = Path(proc_root or os.getenv(ENV_PROC_ROOT, "/proc"))
    candidate_path = root / "meminfo"
    try:
        if _safe_is_file(candidate_path):
            content = candidate_path.read_text(encoding="utf-8", errors="replace")
            return _parse_proc_meminfo_content(content)
    except (OSError, PermissionError):
        pass
    return {}


def get_memory_stats(
    proc_root: str | Path | None = None,
    cgroup_root: str | Path | None = None,
) -> dict[str, Any]:
    """
    Collect memory diagnostic metrics for the current process, host system,
    and container cgroups (v2 / v1).

    Returns:
        dict with keys:
            - pid: int (process ID)
            - rss_mb: float | None (current Resident Set Size in MB)
            - peak_rss_mb: float | None (peak Resident Set Size in MB)
            - sys_available_mb: float | None (available host memory in MB)
            - sys_total_mb: float | None (total host memory in MB)
            - container_memory_used_mb: float | None (container used memory in MB)
            - container_memory_limit_mb: float | None (container memory limit in MB)
            - container_memory_peak_mb: float | None (container peak memory in MB)
            - container_memory_percent: float | None (container memory used % of limit)
    """
    stats: dict[str, Any] = {
        "pid": os.getpid(),
        "rss_mb": None,
        "peak_rss_mb": None,
        "sys_available_mb": None,
        "sys_total_mb": None,
        "container_memory_used_mb": None,
        "container_memory_limit_mb": None,
        "container_memory_peak_mb": None,
        "container_memory_percent": None,
    }

    try:
        proc_status = read_proc_status(proc_root)
        if proc_status:
            if "VmRSS" in proc_status:
                stats["rss_mb"] = round(proc_status["VmRSS"] / 1024.0, 2)
            if "VmHWM" in proc_status:
                stats["peak_rss_mb"] = round(proc_status["VmHWM"] / 1024.0, 2)
            elif "VmRSS" in proc_status:
                stats["peak_rss_mb"] = round(proc_status["VmRSS"] / 1024.0, 2)

        # Standard library resource fallback for peak RSS if available and not yet set
        if stats["peak_rss_mb"] is None:
            try:
                import resource
                usage = resource.getrusage(resource.RUSAGE_SELF)
                if usage.ru_maxrss > 0:
                    stats["peak_rss_mb"] = round(usage.ru_maxrss / 1024.0, 2)
            except (ImportError, AttributeError, Exception):
                pass

        proc_meminfo = read_proc_meminfo(proc_root)
        if proc_meminfo:
            if "MemAvailable" in proc_meminfo:
                stats["sys_available_mb"] = round(proc_meminfo["MemAvailable"] / 1024.0, 2)
            elif "MemFree" in proc_meminfo:
                stats["sys_available_mb"] = round(proc_meminfo["MemFree"] / 1024.0, 2)

            if "MemTotal" in proc_meminfo:
                stats["sys_total_mb"] = round(proc_meminfo["MemTotal"] / 1024.0, 2)

        # Container-level memory metrics
        cgroup_stats = read_cgroup_memory_stats(cgroup_root)
        stats.update(cgroup_stats)

    except Exception:
        # Guarantee diagnostic collection never crashes the host application
        pass

    return stats


def format_memory_diagnostic(checkpoint: str, stats: dict[str, Any]) -> str:
    """
    Format memory statistics into a standardized log string.
    Never includes payload content or secrets.
    """
    pid = stats.get("pid", os.getpid())
    rss = f"{stats['rss_mb']:.2f}" if stats.get("rss_mb") is not None else "N/A"
    peak = f"{stats['peak_rss_mb']:.2f}" if stats.get("peak_rss_mb") is not None else "N/A"
    avail = f"{stats['sys_available_mb']:.2f}" if stats.get("sys_available_mb") is not None else "N/A"

    cont_used = (
        f"{stats['container_memory_used_mb']:.2f}"
        if stats.get("container_memory_used_mb") is not None
        else "N/A"
    )
    cont_limit = (
        f"{stats['container_memory_limit_mb']:.2f}"
        if stats.get("container_memory_limit_mb") is not None
        else "N/A"
    )
    cont_peak = (
        f"{stats['container_memory_peak_mb']:.2f}"
        if stats.get("container_memory_peak_mb") is not None
        else "N/A"
    )
    cont_pct = (
        f"{stats['container_memory_percent']:.2f}%"
        if stats.get("container_memory_percent") is not None
        else "N/A"
    )

    return (
        f"[MEMORY-DIAGNOSTIC] pid={pid} checkpoint='{checkpoint}' "
        f"rss_mb={rss} peak_rss_mb={peak} sys_available_mb={avail} "
        f"container_memory_used_mb={cont_used} container_memory_limit_mb={cont_limit} "
        f"container_memory_peak_mb={cont_peak} container_memory_percent={cont_pct}"
    )


def log_memory_checkpoint(
    checkpoint: str,
    proc_root: str | Path | None = None,
    cgroup_root: str | Path | None = None,
    custom_logger: logging.Logger | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """
    Conditionally log a memory diagnostic checkpoint.

    Returns the collected stats dict if logged, or None if disabled or on error.
    """
    if not force and not is_memory_diagnostics_enabled():
        return None

    try:
        stats = get_memory_stats(proc_root=proc_root, cgroup_root=cgroup_root)
        message = format_memory_diagnostic(checkpoint, stats)
        target_logger = custom_logger or logger
        target_logger.info(message)
        # Flush to stdout to ensure capture by container log collectors (Render)
        print(message, flush=True)
        return stats
    except Exception:
        return None
