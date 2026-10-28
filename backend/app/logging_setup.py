import logging

from app.config import get_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx registra URLs completas em INFO; mantemos em WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)
