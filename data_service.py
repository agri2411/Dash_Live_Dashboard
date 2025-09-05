from google.cloud import bigquery
from google.oauth2 import service_account
import os
import pandas as pd
from config import logger, CONFIG
import json
from decimal import Decimal

key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not key_path:
    raise EnvironmentError("GOOGLE_APPLICATION_CREDENTIALS is not set in environment variables.")

credentials = service_account.Credentials.from_service_account_file(key_path)
bq_client = bigquery.Client(credentials=credentials, project=credentials.project_id)

# Function to fetch KPIs from BigQuery
# This function retrieves key performance indicators (KPIs) related to auctions from a BigQuery database


METRIC_MAP = {
    "LOTS SOLD": "lots_sold",
    "AUCTION EVENTS RUN": "auction_events_run",
    "BIDDER COUNTRIES": "bidder_countries",
    "GROSS VALUE SOLD": "gross_value_sold",
    "NET VALUE SOLD": "net_value_sold",
    "UNIQUE BIDDERS": "unique_bidders",
    "BIDS RECEIVED": "bids_received",
    "HIGHEST BID PLACED": "highest_bid_placed",
    "DOLLARS BID": "dollars_bid"
}

def fetch_kpis():
    try:
        query = """
            SELECT metric, value_today, value_ly
            FROM `cprtpr-dataplatform-sp1.usmart.auction_stats`
        """
        df = bq_client.query(query).to_dataframe()
        
        result = {}
        for _, row in df.iterrows():
            key = METRIC_MAP.get(row["metric"])
            if key:
                result[key] = {
                    "today": float(row["value_today"] or 0),
                    "ly": float(row["value_ly"] or 0)
                }

        return result
    except Exception as e:
        logger.error("fetch_kpis failed: %s", str(e))
        return {}


def fetch_grid():
    try:
        query = """
          select metric,value_today, value_ly from cprtpr-dataplatform-sp1.usmart.auction_stats
        
        """
        df = bq_client.query(query).to_dataframe()
        return df
    except Exception as e:
        logger.error("fetch_map_data failed: %s", str(e))
        return pd.DataFrame()

def fetch_bidder_summary():
    try:
       query = """
        SELECT
            SUM(value_today) AS bidders,
            FORMAT_TIMESTAMP('%Y-%b-%d %H:%M:%S', MAX(last_updated_dt)) as last_up_date
        FROM
            cprtpr-dataplatform-sp1.usmart.auction_stats
        WHERE
            metric = "UNIQUE BIDDERS"
        
       """
       df = bq_client.query(query).to_dataframe()
       return {
        "bidders": int(df["bidders"].iloc[0]),
        "last_up_date": df["last_up_date"].iloc[0]
       }
    except Exception as e:
        logger.error("fetch_bidder_summary failed: %s", str(e))
        return {"bidders": 0,
                 "last_up_date": "N/A"}

def fetch_map_data():
   try:
    query = """
        select * from cprtpr-dataplatform-sp1.usmart.auction_stats_cntry
        where country_long_name not in ('-','Afghanistan','Pakistan','Russian Federation','Iraq','Palestine, State of','Iran','China','North Korea','Saudi Arabia','Myanmar','Syria','Yemen','Somalia','Libya','Myanmar','Belarus','Venezuela','Cuba','Mali','Eritrea')
     """
    df = bq_client.query(query).to_dataframe()
    return df
   except Exception as e:
       logger.error("fetch_map_data failed: %s", str(e))
       return pd.DataFrame()


# Safe wrappers for dashboard use
def fetch_grid_safe():
    try:
        df = fetch_grid()
        if df.empty:
            raise ValueError("Empty DataFrame from fetch_grid")
        return df
    except Exception as e:
        logger.error("fetch_grid_safe fallback: %s", str(e))
        return pd.DataFrame()

def fetch_map_data_safe():
    try:
        df = fetch_map_data()
        if df.empty:
            raise ValueError("Empty map data")
        return df
    except Exception as e:
        logger.error("fetch_map_data_safe fallback: %s", str(e))
        return pd.DataFrame()

def fetch_bidder_summary_safe():
    try:
        summary = fetch_bidder_summary()
        if not summary or "bidders" not in summary:
            raise ValueError("Empty bidder summary")
        return summary
    except Exception as e:
        logger.error("fetch_bidder_summary_safe fallback: %s", str(e))
        return {"bidders": 0, "last_up_date": "N/A"}  # Default values for safety

# def refresh_data():
#     data = {
#         "grid": fetch_grid(),
#         "map": fetch_map_data(),
#         "summary": fetch_bidder_summary()
#     }
#     with open("cache/auction_data.json", "w") as f:
#         json.dump({k: v.to_dict() if hasattr(v, 'to_dict') else v for k, v in data.items()}, f)