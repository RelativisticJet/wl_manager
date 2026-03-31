"""
Unit tests for wl_logging module.

Tests the logger initialization and configuration.
"""

import pytest
import logging
import os
import sys
import tempfile
from unittest import mock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))


@pytest.mark.unit
class TestGetAuditLogger:
    """Test get_audit_logger function."""

    def test_get_audit_logger_returns_logger(self):
        """Verify get_audit_logger returns a logging.Logger instance."""
        from wl_logging import get_audit_logger

        logger = get_audit_logger()
        assert isinstance(logger, logging.Logger)

    def test_get_audit_logger_configures_handler(self):
        """Verify get_audit_logger sets up a RotatingFileHandler."""
        from wl_logging import get_audit_logger

        # Reset logger state for this test
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        from wl_logging import get_audit_logger
        logger = get_audit_logger()

        # Check that a handler was attached
        assert len(logger.handlers) > 0

        # Check that it's a RotatingFileHandler
        has_rotating_handler = any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            for h in logger.handlers
        )
        assert has_rotating_handler

    def test_get_audit_logger_idempotent(self):
        """Verify get_audit_logger is idempotent (no duplicate handlers)."""
        from wl_logging import get_audit_logger

        # Reset logger state
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Call twice
        logger1 = get_audit_logger()
        handler_count_1 = len(logger1.handlers)

        logger2 = get_audit_logger()
        handler_count_2 = len(logger2.handlers)

        # Should return the same instance with same handler count
        assert logger1 is logger2
        assert handler_count_1 == handler_count_2
        assert handler_count_1 == 1

    def test_get_audit_logger_creates_log_directory(self, monkeypatch):
        """Verify get_audit_logger creates the log directory if missing."""
        from wl_logging import get_audit_logger

        # Reset logger
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Create temporary directory for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock SPLUNK_HOME
            monkeypatch.setenv("SPLUNK_HOME", tmpdir)

            # Call get_audit_logger
            logger = get_audit_logger()

            # Check that the log directory was created
            log_dir = os.path.join(tmpdir, "var", "log", "splunk")
            assert os.path.isdir(log_dir)

            # Clean up handlers to allow temp directory deletion
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def test_get_audit_logger_uses_env_var(self, monkeypatch):
        """Verify get_audit_logger respects SPLUNK_HOME environment variable."""
        from wl_logging import get_audit_logger

        # Reset logger
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Create temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock SPLUNK_HOME
            monkeypatch.setenv("SPLUNK_HOME", tmpdir)

            # Call get_audit_logger
            logger = get_audit_logger()

            # Get the handler's file path
            handler = logger.handlers[0]
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                log_file = handler.baseFilename
                # Verify the log file is in the mocked SPLUNK_HOME
                assert tmpdir in log_file
                assert "var" in log_file
                assert "log" in log_file
                assert "splunk" in log_file

            # Clean up handlers to allow temp directory deletion
            for h in logger.handlers[:]:
                h.close()
                logger.removeHandler(h)

    def test_get_audit_logger_sets_level(self):
        """Verify get_audit_logger sets the logger level to INFO."""
        from wl_logging import get_audit_logger

        # Reset logger
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        logger = get_audit_logger()
        assert logger.level == logging.INFO

    def test_get_audit_logger_has_formatter(self):
        """Verify the handler has a formatter configured."""
        from wl_logging import get_audit_logger

        # Reset logger
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        logger = get_audit_logger()

        # Check formatter exists
        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        assert handler.formatter is not None

    def test_get_audit_logger_rotating_handler_config(self):
        """Verify RotatingFileHandler has correct maxBytes and backupCount."""
        from wl_logging import get_audit_logger

        # Reset logger
        logger = logging.getLogger("wl_audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        logger = get_audit_logger()

        # Find the RotatingFileHandler
        for handler in logger.handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                # Check maxBytes (100 MB)
                assert handler.maxBytes == 100 * 1024 * 1024
                # Check backupCount (10 backups)
                assert handler.backupCount == 10
                break
