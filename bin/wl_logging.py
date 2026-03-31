"""
Logging configuration for Whitelist Manager.

Provides get_audit_logger() to initialize a rotating file handler
for audit events. This is a Layer 1 module (depends only on constants).
"""

import logging
import logging.handlers
import os

__all__ = ["get_audit_logger"]


def get_audit_logger() -> logging.Logger:
    """
    Get or create the audit logger with rotating file handler.

    Returns a logger configured with:
    - RotatingFileHandler writing to $SPLUNK_HOME/var/log/splunk/wl_manager_audit.log
    - Max 100 MB per file, keeping 10 backup files
    - Format: ISO timestamp, logger name, level, message

    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger("wl_audit")

    # Avoid duplicate handlers on reload
    if logger.handlers:
        return logger

    # Determine log file path
    splunk_home = os.environ.get("SPLUNK_HOME", "/opt/splunk")
    log_dir = os.path.join(splunk_home, "var", "log", "splunk")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "wl_manager_audit.log")

    # Configure handler
    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=100 * 1024 * 1024,  # 100 MB
        backupCount=10,
    )

    # Configure formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    # Attach to logger
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    return logger
