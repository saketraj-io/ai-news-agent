"""
utils/logger.py
───────────────
Centralised logging setup using Loguru.
- Console output with colour and level filtering
- Rotating file output (10 MB max, 7-day retention)
- Single call to `setup_logger()` at app startup
"""

import sys
from pathlib import Path
from loguru import logger

from config.settings import settings, ROOT_DIR

# ── Log file location ─────────────────────────────────────────────────
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "news_agent.log"


def setup_logger() -> None:
    """
    Configure Loguru sinks.
    Call once at the top of app.py.
    """
    # Remove default Loguru handler
    logger.remove()

    # ── Console sink ──────────────────────────────────────────────────
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # ── File sink (rotating) ──────────────────────────────────────────
    logger.add(
        str(LOG_FILE),
        level="DEBUG",           # always capture everything to file
        rotation="10 MB",        # new file after 10 MB
        retention="7 days",      # keep last 7 days of logs
        compression="zip",       # compress old logs
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} — {message}"
        ),
        enqueue=True,            # thread-safe async writes
    )

    logger.info(
        "Logger initialised | level={} | file={}",
        settings.log_level,
        LOG_FILE,
    )


# Expose logger directly so callers can do:
#   from utils.logger import log
#   log.info("...")
log = logger
