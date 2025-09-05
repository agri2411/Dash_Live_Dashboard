#!/bin/bash

# Run refresh_cache.py every 5 seconds in background
while true; do
  python /app/refresh_cache.py
  sleep 5
done &

# Run the main app in foreground
python /app/auction_dashboard.py
