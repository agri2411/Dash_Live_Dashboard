import os
import logging
from dotenv import load_dotenv


# Load variables from .env file, if it exists
load_dotenv()

os.makedirs("/tmp/logs", exist_ok=True)

env = os.environ.get("APP_ENV", "dev").lower()
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/tmp/logs/app.log"),
        logging.StreamHandler()
    ]
)

logger=logging.getLogger(__name__)

env = os.environ.get("APP_ENV", "dev").lower()

if env == "prod":
    from .prod_config import CONFIG
elif env == "dev":
    from .dev_config import CONFIG
else:
    raise ValueError(f"Unsupported APP_ENV: {env}")