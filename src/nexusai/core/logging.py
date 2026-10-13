import json
import logging


class SafeJSONFormatter(logging.Formatter):
    """Allowlisted operational fields only; never format exception text or request content."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "event": getattr(record, "event", "application_event"),
                "request_id": getattr(record, "request_id", None),
                "status_code": getattr(record, "status_code", None),
                "duration_ms": getattr(record, "duration_ms", None),
            }
        )


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("nexusai")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
