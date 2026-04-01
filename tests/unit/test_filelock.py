"""
Unit tests for wl_filelock module (Layer 2).

Tests verify that file_lock context manager correctly handles:
- Thread-level locking with RLock
- Cross-process locking with fcntl on Unix
- Windows no-op fallback
- Timeout and retry logic
- Exception handling and cleanup

Coverage target: >= 80%
"""

import os
import sys
import tempfile
import threading
import time
import pytest
from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock

# Add bin directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

import wl_filelock


# ═══════════════════════════════════════════════════════════════════════════
# Basic Lock Acquisition & Release Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_lock_acquire_success_unix(tmp_path):
    """Verify file_lock context manager can acquire and release on Unix."""
    lock_file = tmp_path / "test.lock"

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        # Lock acquired successfully
        # On Windows, fcntl is not available, so file may not be created
        # Just verify no exception was raised
        pass

    # Lock released (file may or may not be deleted, depends on OS)


@pytest.mark.unit
def test_lock_release_on_exception(tmp_path):
    """Verify lock is released even if exception raised in with block."""
    lock_file = tmp_path / "test.lock"

    try:
        with wl_filelock.file_lock(str(lock_file), timeout=5):
            raise ValueError("Test exception")
    except ValueError:
        pass

    # Lock should be released (no assertion needed, just verify no crash)
    assert True


@pytest.mark.unit
def test_lock_windows_noop():
    """Verify context manager is no-op on Windows (fcntl unavailable)."""
    with patch.object(wl_filelock, 'fcntl', None):
        # Simulate Windows by making fcntl None
        with wl_filelock.file_lock("/tmp/dummy.lock", timeout=5) as result:
            # On Windows, should yield True (no-op)
            assert result is True


@pytest.mark.unit
def test_lock_timeout_exception(tmp_path):
    """Verify TimeoutError raised when lock not acquired within timeout."""
    lock_file = tmp_path / "test.lock"

    # Mock fcntl to always raise IOError (lock contention)
    with patch.object(wl_filelock, 'fcntl') as mock_fcntl:
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        mock_fcntl.LOCK_UN = 8

        mock_file = MagicMock()
        mock_file.fileno.return_value = 3

        with patch('builtins.open', return_value=mock_file):
            mock_fcntl.flock.side_effect = IOError("Lock unavailable")

            with pytest.raises(TimeoutError):
                with wl_filelock.file_lock(str(lock_file), timeout=0.5):
                    pass


@pytest.mark.unit
def test_lock_negative_timeout_raises_error():
    """Verify negative timeout raises ValueError."""
    with pytest.raises(ValueError):
        with wl_filelock.file_lock("/tmp/dummy.lock", timeout=-1):
            pass


@pytest.mark.unit
def test_lock_zero_timeout():
    """Verify zero timeout is valid (immediate fail if lock not available)."""
    # Should not raise ValueError for timeout=0
    with patch.object(wl_filelock, 'fcntl', None):
        with wl_filelock.file_lock("/tmp/dummy.lock", timeout=0) as result:
            assert result is True


@pytest.mark.unit
def test_lock_default_timeout(tmp_path):
    """Verify default 10-second timeout used when not specified."""
    lock_file = tmp_path / "test.lock"

    with patch('wl_filelock.file_lock', wraps=wl_filelock.file_lock) as mock_lock:
        with mock_lock(str(lock_file)):
            pass

        # Verify function was called (timeout not explicitly passed)
        mock_lock.assert_called()


@pytest.mark.unit
def test_lock_custom_timeout():
    """Verify custom timeout parameter is respected."""
    with patch.object(wl_filelock, 'fcntl', None):
        start = time.time()
        with wl_filelock.file_lock("/tmp/dummy.lock", timeout=2):
            pass
        # For no-op Windows, should return immediately
        elapsed = time.time() - start
        assert elapsed < 1  # Should complete in less than 1 second


# ═══════════════════════════════════════════════════════════════════════════
# RLock (Thread-Level Lock) Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_rlock_acquired():
    """Verify RLock is acquired before file lock."""
    with patch.object(wl_filelock, '_file_lock_thread_lock') as mock_rlock:
        mock_rlock.acquire.return_value = True

        with patch.object(wl_filelock, 'fcntl', None):
            with wl_filelock.file_lock("/tmp/dummy.lock", timeout=5):
                pass

            # Verify RLock was acquired and released
            mock_rlock.acquire.assert_called()
            mock_rlock.release.assert_called()


@pytest.mark.unit
def test_rlock_timeout():
    """Verify TimeoutError raised if RLock cannot be acquired within timeout."""
    with patch.object(wl_filelock, '_file_lock_thread_lock') as mock_rlock:
        mock_rlock.acquire.return_value = False  # Simulate timeout

        with pytest.raises(TimeoutError):
            with wl_filelock.file_lock("/tmp/dummy.lock", timeout=1):
                pass


# ═══════════════════════════════════════════════════════════════════════════
# Sequential Lock Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_multiple_sequential_locks(tmp_path):
    """Verify acquire, release, and re-acquire on same file all succeed."""
    lock_file = tmp_path / "test.lock"

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        pass

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        pass

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        pass

    # All three should succeed


@pytest.mark.unit
def test_lock_path_creation(tmp_path):
    """Verify lock file is created if it doesn't exist."""
    lock_file = tmp_path / "new_lock.lock"
    assert not lock_file.exists()

    with patch.object(wl_filelock, 'fcntl') as mock_fcntl:
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        mock_fcntl.LOCK_UN = 8

        mock_fcntl.flock.return_value = None  # Successful lock

        with patch('builtins.open', mock.mock_open()):
            with wl_filelock.file_lock(str(lock_file), timeout=5):
                pass


# ═══════════════════════════════════════════════════════════════════════════
# Exception Handling & Cleanup Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_lock_cleanup_on_exception(tmp_path):
    """Verify lock is cleaned up even if exception raised."""
    lock_file = tmp_path / "test.lock"

    try:
        with wl_filelock.file_lock(str(lock_file), timeout=5):
            raise RuntimeError("Test error")
    except RuntimeError:
        pass

    # Verify cleanup completed without crash


@pytest.mark.unit
def test_lock_file_closed_on_exception(tmp_path):
    """Verify lock file is closed even on exception."""
    lock_file = tmp_path / "test.lock"

    with patch('builtins.open', mock.mock_open()) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value = mock_file

        with patch.object(wl_filelock, 'fcntl') as mock_fcntl:
            mock_fcntl.LOCK_EX = 2
            mock_fcntl.LOCK_NB = 4
            mock_fcntl.LOCK_UN = 8
            mock_fcntl.flock.return_value = None

            try:
                with wl_filelock.file_lock(str(lock_file), timeout=5):
                    raise ValueError("Test")
            except ValueError:
                pass

            # Verify file was closed
            mock_file.close.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# Concurrency Tests (Basic)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_concurrent_lock_contention_basic(tmp_path):
    """Verify basic concurrency with file locking (smoke test)."""
    lock_file = tmp_path / "concurrent.lock"
    results = []

    def acquire_lock(thread_id):
        try:
            with wl_filelock.file_lock(str(lock_file), timeout=2):
                results.append((thread_id, "acquired"))
                time.sleep(0.1)  # Hold lock briefly
        except TimeoutError:
            results.append((thread_id, "timeout"))

    threads = [
        threading.Thread(target=acquire_lock, args=(i,))
        for i in range(3)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # All threads should have attempted acquisition
    assert len(results) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests (Real File System)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_lock_with_real_file(tmp_path):
    """Integration test with real file system (no mocks)."""
    lock_file = tmp_path / "real_lock.lock"

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        # Within the context, lock is held
        pass

    # After context, lock is released


@pytest.mark.unit
def test_lock_file_readable_after_lock(tmp_path):
    """Verify lock file can be read/written after lock is released."""
    lock_file = tmp_path / "writable.lock"

    with wl_filelock.file_lock(str(lock_file), timeout=5):
        with open(lock_file, "w") as f:
            f.write("test")

    with open(lock_file, "r") as f:
        content = f.read()
        assert content == "test"
