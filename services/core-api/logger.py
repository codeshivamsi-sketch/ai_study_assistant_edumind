import structlog
import logging

def setup_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory()
    )
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

setup_logging()
log = structlog.get_logger()