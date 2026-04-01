"""
Shared file locking utility for Whitelist Manager.

Provides a cross-platform file locking context manager used by all Phase 3+
modules (approval queue, limits, etc.).

On Unix-like systems: combines thread-level RLock + process-level fcntl.flock.
On Windows: no-op (dev-only platform).
"""

import os
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

# Try to import fcntl for file locking (Unix-like systems)
try:
    import fcntl
except ImportError:
    fcntl = None

__all__ = ["file_lock"]

# Module-level RLock to prevent same-process thread contention
_file_lock_thread_lock = threading.RLock()


@contextmanager
def file_lock(lock_path: str, timeout: float = 10) -> Iterator[bool]:
    """
    Acquire exclusive lock on file with timeout.

    Combines in-process RLock (for thread safety) with cross-process fcntl.flock
    (for process safety on Unix-like systems).

    On Windows, fcntl is unavailable, so only thread-level locking is used.

    Args:
        lock_path: Path to the file to lock
        timeout: Maximum seconds to wait for lock (default 10)

    Yields:
        True if lock acquired on Unix, True on Windows (no-op)

    Raises:
        TimeoutError: If lock not acquired within timeout seconds
        ValueError: If timeout is negative
        OSError: If lock file operations fail
    """
    if timeout < 0:
        raise ValueError("timeout must be non-negative")

    lock_file = None

    try:
        # Acquire thread-level lock first
        if not _file_lock_thread_lock.acquire(timeout=timeout):
            raise TimeoutError(f"Could not acquire thread lock within {timeout} seconds")

        try:
            # On Unix, also acquire process-level file lock
            if fcntl:
                lock_file = open(lock_path, "a", encoding="utf-8")
                retry_count = int(timeout / 0.1)  # 100 attempts per second

                for attempt in range(retry_count):
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        yield True
                        return
                    except (IOError, OSError):
                        if attempt < retry_count - 1:
                            # Retry with small backoff
                            import time
                            time.sleep(0.1)
                        else:
                            raise TimeoutError(f"Could not acquire file lock within {timeout} seconds")

                # Blocking acquire after retries exhausted
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                yield True
            else:
                # Windows: no-op, just yield
                yield True

        finally:
            # Release process-level lock
            if lock_file and fcntl:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass

    finally:
        # Always release thread-level lock
        _file_lock_thread_lock.release()

        # Close lock file if opened
        if lock_file:
            try:
                lock_file.close()
            except (IOError, OSError):
                pass
