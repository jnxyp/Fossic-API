import json
import logging
import datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(
            record.created, tz=datetime.timezone.utc
        ).isoformat(timespec='milliseconds')
        doc: dict[str, object] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc, ensure_ascii=False)


_configured = False

def _configure_root() -> None:
    global _configured
    if _configured:
        return
    # skip if already configured externally (e.g. by uvicorn --log-config)
    if logging.root.handlers:
        _configured = True
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)


# backwards compat
def setup_custom_logger(name: str) -> logging.Logger:
    return get_logger(name)
