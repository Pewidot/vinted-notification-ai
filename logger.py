import logging
import os
import sys
import threading
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

_context = threading.local()


def set_log_context(platform=None, query_id=None, worker=None):
    """Bind context to the current long-lived worker thread/process."""
    _context.value = {
        "platform": platform or "",
        "query_id": "" if query_id is None else str(query_id),
        "worker": worker or "",
    }


@contextmanager
def log_context(platform=None, query_id=None, worker=None):
    """Attach worker metadata to every log record emitted by this thread."""
    previous = getattr(_context, "value", None)
    set_log_context(platform, query_id, worker)
    try:
        yield
    finally:
        _context.value = previous


class WorkerContextFilter(logging.Filter):
    def filter(self, record):
        value = getattr(_context, "value", None) or {}
        fields = []
        if value.get("platform"):
            fields.append(f"platform={value['platform']}")
        if value.get("query_id"):
            fields.append(f"query={value['query_id']}")
        if value.get("worker"):
            fields.append(f"worker={value['worker']}")
        record.worker_context = f"[{' '.join(fields)}] " if fields else ""
        return True


# Custom filter to exclude specific log messages
class ExcludeFilter(logging.Filter):
    def filter(self, record):
        # Filter out APScheduler executor logs about running jobs
        if record.name == "apscheduler.executors.default" and (
            "Running job" in record.getMessage()
            or "executed successfully" in record.getMessage()
        ):
            return False

        # Filter out APScheduler scheduler logs about job management
        if record.name == "apscheduler.scheduler" and (
            "Added job" in record.getMessage()
            or "Adding job tentatively" in record.getMessage()
            or "Removed job" in record.getMessage()
            or "Scheduler started" in record.getMessage()
            or "skipped: maximum number of running instances reached"
            in record.getMessage()
        ):
            return False

        # Filter out httpx HTTP request logs
        if record.name == "httpx" and "HTTP Request:" in record.getMessage():
            return False

        # Filter out log refresh requests from the web UI
        if record.name == "werkzeug" and "GET /api/logs" in record.getMessage():
            return False

        return True


# Configure the root logger
def configure_root_logger():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(worker_context)s%(message)s"
    )
    console_handler.setFormatter(console_formatter)

    # File handler for all logs
    file_handler = RotatingFileHandler(
        "logs/vinted.log", maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(worker_context)s%(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # Create and add the exclude filter to both handlers
    exclude_filter = ExcludeFilter()
    context_filter = WorkerContextFilter()
    console_handler.addFilter(exclude_filter)
    console_handler.addFilter(context_filter)
    file_handler.addFilter(exclude_filter)
    file_handler.addFilter(context_filter)

    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


# Get a logger for a specific module
def get_logger(name):
    if not logging.getLogger().handlers:
        configure_root_logger()
    return logging.getLogger(name)
