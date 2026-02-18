"""
Sasoo - Centralized Logging Configuration
Sets up rotating file logs + console output for the entire backend.

Log files are stored in:
  - Development: backend/logs/
  - Production:  %APPDATA%/Sasoo/logs/ (Windows)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from models.database import APP_DATA_ROOT

# Log directory
LOG_DIR = APP_DATA_ROOT / "logs"

# Format
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Rotating file config: 5MB per file, keep 5 backups = 25MB max
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger with:
    1. Console handler (stdout)
    2. Rotating file handler (sasoo.log)
    3. Separate error file handler (sasoo-error.log)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid adding duplicate handlers on reload
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Main log file (all levels)
    main_handler = RotatingFileHandler(
        str(LOG_DIR / "sasoo.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    main_handler.setLevel(level)
    main_handler.setFormatter(formatter)
    root.addHandler(main_handler)

    # Error-only log file
    error_handler = RotatingFileHandler(
        str(LOG_DIR / "sasoo-error.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.info("Logging initialized. Log dir: %s", LOG_DIR)
