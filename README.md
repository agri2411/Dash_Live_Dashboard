# LiveAuctionStats
Show real time stats of Auction attributes like Lots Auctioned, Total Bidders and Bids related info to be displayed on large TV Screens.  

## Overview

This is a Python-based dashboard application for displaying real-time auction statistics. The application is built using the Dash framework, with data sourced from Google BigQuery.

**Main Components:**

1. **Dashboard Application**: A Dash web application (`auction_dashboard.py`) that displays auction KPIs and visualizations in multiple views.

2. **Data Integration**: The application connects to Google BigQuery (`data_service.py`) to fetch auction statistics data.

3. **Caching Mechanism**: Implements both Redis and file-based caching (`cache_data.py`) to optimize performance and reduce API calls.

4. **Docker Deployment**: Includes Docker configuration for containerized deployment.

5. **Multiple Views**:
   - KPI View: Shows key metrics like bids received, unique bidders, transaction values
   - Map View: Displays a global map showing bidder locations and activity
   - Glossary View: Explains the meaning of different metrics

**Data Flow:**
- Data is fetched from BigQuery tables in the `cprtpr-dataplatform-sp1.usmart` dataset
- The application periodically refreshes data through a caching mechanism
- Real-time updates are displayed through Dash callbacks and animations

**Technical Stack:**
- Python with Dash/Plotly for the web UI
- Google BigQuery for data storage
- Redis for caching
- Docker for containerization

## How to Run

### Local
```
# .env has APP_ENV=dev
python auction_dashboard.py
```

### Docker
```
docker build -t auction-app .
docker run -p 8050:8050 -e APP_ENV=prod auction-app
```