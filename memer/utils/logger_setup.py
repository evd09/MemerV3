"""Logging helper utilities.

This module provides :func:`setup_logger` which configures both a rotating
file handler and a stream handler.  The original implementation assumed the
process always had permission to write to ``./logs`` which is not true when
the bot is executed in certain containers or restricted environments.  In
those cases ``RotatingFileHandler`` would raise a ``PermissionError`` and the
entire bot would fail to start.  To make logging more robust we now fall back
to a temporary directory (or to stdout only) when the requested log location
is not writable.
"""

import os
import logging
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_file: str, level: int = logging.INFO) -> logging.Logger:
    """Create or retrieve a logger configured with rotation.

    Parameters
    ----------
    name:
        Name of the logger.
    log_file:
        Desired log file path.  If only a file name is given the file will be
        placed inside ``./logs``.  When this location is not writable we fall
        back to a temporary directory so that the bot does not crash during
        start-up.
    level:
        Logging level.
    """

    logger = logging.getLogger(name)
    if logger.handlers:
        # Logger already configured
        return logger

    logger.setLevel(level)

    # Determine target log directory
    dirpath = os.path.dirname(log_file)
    if not dirpath:
        dirpath = "logs"
    filename = os.path.basename(log_file)
    log_path = Path(dirpath) / filename

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = None
    try:
        os.makedirs(log_path.parent, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
    except OSError:
        # Fall back to a writable temp directory
        try:
            tmp_dir = Path(tempfile.gettempdir()) / "memer_logs"
            tmp_dir.mkdir(exist_ok=True)
            fallback_path = tmp_dir / filename
            file_handler = RotatingFileHandler(
                fallback_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
            )
            logger.warning("Log path %s not writable, using %s instead", log_path, fallback_path)
        except OSError:
            # As a last resort, just log to stdout
            file_handler = None

    if file_handler is not None:
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    # Always log to stdout
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    return logger
