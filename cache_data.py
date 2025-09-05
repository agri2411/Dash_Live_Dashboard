from data_service import fetch_kpis,fetch_grid, fetch_map_data, fetch_bidder_summary
import json
import os
from decimal import Decimal
import pandas as pd
from datetime import datetime
import logging
from redis import Redis
import yaml
import sys
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Redis connection
# redis_conn = Redis(host=os.getenv('REDIS_HOST', 'c-redis-dev4.copart.com'), port=int(os.getenv('REDIS_PORT', 6379)),password=os.getenv("REDIS_PASSWORD"))
# redis_url = os.getenv("RQ_REDIS_URL", "redis://c-redis-dev4.copart.com:6379/0")

config_path = os.path.join("config", "redis_config.yml")
try:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    logger.error(f"❌ Config file not found: {config_path}")
    sys.exit(1)
except yaml.YAMLError as e:
    logger.error(f"❌ Failed to parse YAML config: {e}")
    sys.exit(1)

if "redis" not in config:
    logger.error("❌ Missing 'redis' section in config file")
    sys.exit(1)

redis_cfg = config["redis"]

required_keys = ["host", "port", "db", "password", "client_name"]
for key in required_keys:
    if key not in redis_cfg:
        logger.error(f"❌ Missing required key '{key}' in redis config")
        sys.exit(1)

password = os.getenv("REDIS_PASSWORD", redis_cfg.get("password"))

# Redis connection
redis_conn = Redis(
    host=redis_cfg["host"],
    port=redis_cfg["port"],
    db=redis_cfg.get("db", 0),
    password=password,
    socket_timeout=redis_cfg.get("socket_timeout", 5),
    socket_connect_timeout=redis_cfg.get("socket_connect_timeout", 5),
    retry_on_timeout=redis_cfg.get("retry_on_timeout", True),
    client_name=redis_cfg.get("client_name", "cache-data"),
)

def clean_decimals(obj):
    if isinstance(obj, list):
        return [clean_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: clean_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()  # or str(obj)
    return obj

def refresh_data():
    """Refresh data and store in Redis cache"""
    logger.info("🌀 Running refresh_data job")
    try:
        data = {
            "kpis": fetch_kpis(),
            "grid": fetch_grid().to_dict(orient="records"),
            "map": fetch_map_data().to_dict(orient="records"),
            "summary": fetch_bidder_summary(),
            "last_refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S %p")
        }

        # Clean decimals for JSON serialization
        cleaned_data = clean_decimals(data)
        
        # Store in Redis with expiration time (7 minutes to ensure fresh data)
        redis_conn.setex("auction_data", 420, json.dumps(cleaned_data))
        # Also save to file as backup
        os.makedirs("cache", exist_ok=True)

        with open("cache/auction_data.json", "w") as f:
            json.dump(clean_decimals(data), f)
        logger.info(f"✅ Cache refreshed successfully at {data['last_refreshed']}")
        return True
    except Exception as e:
        logger.error(f"❌ Error refreshing data: {str(e)}")
        return False

def get_cached_data():
    """Get data from Redis cache, fallback to file or fresh fetch"""
    try:
        # Try Redis first
        cached_data = redis_conn.get("auction_data")
        if cached_data:
            logger.info("📦 Retrieved data from Redis cache")
            return json.loads(cached_data)
            
        # Fallback to file cache
        if os.path.exists("cache/auction_data.json"):
            logger.info("📁 Retrieved data from file cache")
            with open("cache/auction_data.json", "r") as f:
                return json.load(f)
                
        # Last resort: fetch fresh data
        logger.info("🔄 No cache found, fetching fresh data")
        refresh_data()
        return get_cached_data()
        
    except Exception as e:
        logger.error(f"❌ Error getting cached data: {str(e)}")
        # Return empty structure to prevent app crashes
        return {
            "kpis": {},
            "grid": [],
            "map": [],
            "summary": {},
            "last_refreshed": "Cache Error"
        }
    