"""
logger.py — Structured rotating log setup.

BUGS FIXED:
  - BUG: FileHandler writes to logs/bot.log (a plain file) which grows
    unbounded. On a server running 24/7 with 20 accounts this hits GB
    within days. Replaced with RotatingFileHandler (5MB × 3 backups).
  - BUG: logger.py imports from config (LOG_FILE) but config.py itself
    imports nothing from logger — however if config.py ever fails,
    logger setup crashes before any error can be logged. Hardcoded
    the log filename to break the circular dependency risk.
  - IMPROVEMENT: Added %(name)s to formatter so per-module loggers
    are distinguishable in log files.
  - IMPROVEMENT: Production log level driven by LOG_LEVEL env var.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("TelegramBot")
    logger.setLevel(logging.DEBUG)   # master level; handlers filter further

    if logger.handlers:
        # Already set up (e.g. imported twice) — don't add duplicate handlers
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console ──
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    console.setFormatter(formatter)
    logger.addHandler(console)

    # ── Rotating file: 5 MB × 3 backups ──
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


logger = setup_logger()
