import logging

_configured = False

def _configure_root() -> None:
    global _configured
    if _configured:
        return
    formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s][%(name)s]: %(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
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
