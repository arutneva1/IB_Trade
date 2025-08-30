from __future__ import annotations

import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Tuple

__all__ = ["setup_logging"]

_BASE_RECORD_FACTORY = logging.getLogRecordFactory()
_RUN_ID = ""


class JsonFormatter(logging.Formatter):
    def __init__(self, datefmt: str | None = None) -> None:
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - simple
        data: dict[str, Any] = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", ""),
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(data)


def setup_logging(
    report_dir: Path,
    *,
    level: str = "INFO",
    json_logs: bool = False,
) -> Tuple[Path, str]:
    """Configure global logging.

    Parameters
    ----------
    report_dir:
        Directory where the log file will be written.
    level:
        Logging verbosity.
    json_logs:
        Emit JSON formatted logs when ``True``; otherwise plain text.

    Returns
    -------
    Tuple[Path, str]
        The path to the created log file and the run identifier.
    """

    global _RUN_ID
    _RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / f"run_{_RUN_ID}.log"

    handler = logging.FileHandler(log_path)
    if json_logs:
        formatter: logging.Formatter = JsonFormatter("%Y-%m-%dT%H:%M:%S%z")
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(run_id)s] %(message)s",
            "%Y-%m-%dT%H:%M:%S%z",
        )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = _BASE_RECORD_FACTORY(*args, **kwargs)
        record.run_id = _RUN_ID
        return record

    logging.setLogRecordFactory(record_factory)
    return log_path, _RUN_ID
