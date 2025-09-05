from rq_scheduler import Scheduler
from redis import Redis
from datetime import datetime
from cache_data import refresh_data
import os
import yaml
import sys
from dotenv import load_dotenv
load_dotenv()

print("⏱ Setting up RQ scheduler with proper configuration...")

# Connect to Redis
# redis_conn = Redis(host=os.getenv('REDIS_HOST', 'c-redis-dev4.copart.com'), port=int(os.getenv('REDIS_PORT', 6379)),password=os.getenv("REDIS_PASSWORD"))
# redis_url = os.getenv("RQ_REDIS_URL", "redis://c-redis-dev4.copart.com:6379/0")
# redis_conn = from_url(redis_url)

config_path = os.path.join("config", "redis_config.yml")
try:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    print(f"❌ Config file not found: {config_path}")
    sys.exit(1)
except yaml.YAMLError as e:
    print(f"❌ Failed to parse YAML config: {e}")
    sys.exit(1)

# Validate Redis section
if "redis" not in config:
    print("❌ Missing 'redis' section in config file")
    sys.exit(1)

redis_cfg = config["redis"]

# Required keys
required_keys = ["host", "port", "db", "password", "client_name"]
for key in required_keys:
    if key not in redis_cfg:
        print(f"❌ Missing required key '{key}' in redis config")
        sys.exit(1)

password = os.getenv("REDIS_PASSWORD", redis_cfg.get("password"))

redis_conn = Redis(
    host=redis_cfg["host"],
    port=redis_cfg["port"],
    db=redis_cfg.get("db", 0),
    password=password,
    socket_timeout=redis_cfg.get("socket_timeout", 5),
    socket_connect_timeout=redis_cfg.get("socket_connect_timeout", 5),
    retry_on_timeout=redis_cfg.get("retry_on_timeout", True),
    client_name=redis_cfg.get("client_name", "g2-auctionStats")
)


scheduler = Scheduler(connection=redis_conn)

for job in scheduler.get_jobs():
    if "refresh_data" in job.func_name:
        scheduler.cancel(job)
        print(f"🗑 Cancelling existing job: {job.id}")

# Schedule the job to run every 5 minutes
job = scheduler.schedule(
    scheduled_time=datetime.utcnow(),
    func=refresh_data,  # Pass the function directly, not as string
    interval=300,  # 5 minutes in seconds
    repeat=None,  # Repeat indefinitely
    result_ttl=-1
)

print(f"✅ Scheduled refresh_data job: {job.id}")
print("📅 Job will run every 5 minutes with result_ttl=-1")

# Run once immediately
refresh_data()
print("✅ Initial refresh completed")
# Start the RQ scheduler (blocking)