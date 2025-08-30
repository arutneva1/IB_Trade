import json
import logging
from datetime import datetime, timezone

from ibkr_etf_rebalancer.logging_utils import setup_logging


def test_setup_logging_creates_json_log(tmp_path):
    as_of = datetime(2023, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    root = logging.getLogger()
    prev_handlers = root.handlers[:]
    prev_level = root.level
    prev_factory = logging.getLogRecordFactory()
    try:
        log_path, run_id = setup_logging(tmp_path, json_logs=True, as_of=as_of)
        assert log_path.exists()
        assert run_id in log_path.name

        logger = logging.getLogger(__name__)
        logger.info("hello world")

        lines = log_path.read_text().strip().splitlines()
        assert lines, "log file should contain lines"
        data = json.loads(lines[0])
        assert data["run_id"] == run_id
        assert data["message"] == "hello world"
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        for h in prev_handlers:
            root.addHandler(h)
        root.setLevel(prev_level)
        logging.setLogRecordFactory(prev_factory)
