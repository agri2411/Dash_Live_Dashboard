import os
import time
import logging
from datetime import datetime
from cache_data import refresh_data

logging.basicConfig(level=logging.INFO)

INTERVAL_SECONDS = 300  # 5 minutes

if __name__ == "__main__":
    logging.info("⏱ Starting custom scheduler...")

    while True:
        try:
            logging.info(f"🔁 Refreshing Redis cache at {datetime.utcnow().isoformat()} UTC")
            refresh_data()
            logging.info("✅ Cache refreshed successfully.")
        except Exception as e:
            logging.exception("❌ Error refreshing cache")

        logging.info(f"🕒 Sleeping for {INTERVAL_SECONDS} seconds...")
        time.sleep(INTERVAL_SECONDS)