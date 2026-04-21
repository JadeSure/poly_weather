import json
import logging
import logging.config

from src.common.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    config_path = settings.logging_path
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as file:
            logging.config.dictConfig(json.load(file))
        return

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


logger = logging.getLogger("weatheredge")

