from dash import Dash, html, dcc
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from flask import jsonify,request
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import os
import logging
import dash
import plotly.express as px
from config import CONFIG, logger
from data_service import fetch_map_data_safe, fetch_bidder_summary_safe
from flask_caching import Cache
from redis import Redis
from rq import Queue
import json
from cache_data import refresh_data
import logging
import yaml
import sys
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)



# 💥 Warm-up: refresh cache immediately
try:
    refresh_data()
    logging.info("✅ Initial cache refresh completed successfully.")
except Exception as e:
    logging.error("⚠️ Initial cache refresh failed:", exc_info=e)


# Caching config (file-based, can swap with Redis later)


# Redis setup
# redis_conn = Redis(
#     host=os.getenv("REDIS_HOST", "redis"),
#     port=int(os.getenv("REDIS_PORT", 6379))
# )

# task_queue = Queue('default', connection=redis_conn)

# Load YAML config
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
    client_name=redis_cfg.get("client_name", "g2-auctionStats"),
)

task_queue = Queue("default", connection=redis_conn)

# Load cached data if available
def get_cached_data():
    try:
        with open("cache/auction_data.json") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info("No cached file found. Enqueuing refresh job.")
        task_queue.enqueue("cache_data.refresh_data")
        return {}



app = Dash(__name__, suppress_callback_exceptions=True)
app.title = f"Auction Stats - {CONFIG['ENV_NAME'].upper()}"
server = app.server

cache = Cache(app.server, config={"CACHE_TYPE": "filesystem", "CACHE_DIR": "/tmp/cache"})

# Health check endpoint
@server.route("/healthz")
def healthz():
    return jsonify({
        "status": "healthy",
        "env": CONFIG["ENV_NAME"],
        "version": CONFIG["VERSION"]
    }), 200

GLOSSARY_DATA = {
    # "Gross Value": "Total sale amount including Copart charges.",
    #"Vehicles Sold": "Total number of vehicles sold today.",
    "Transaction Value": "Sale price in auction without Copart Charges.",
    "Unique Bidders": "Count of distinct bidders participating.",
    "Dollars Bid": "Total dollar value of all bids submitted.",
    "Highest Bid Placed": "Top single bid received today.",
    "Bids Received": "Total number of bids placed today.",
    "Auction Events Run": "Number of live auction events conducted today.",
    "Bidder Countries": "Countries of bidders participating today.",
    "Total Dollars Bid": "Total dollar value of all bids placed today."
}


GREEN_BG = "#e6f4ea"
GRAY_BG = "#E9ECF1"

# def get_glossary_term(title):
#     return GLOSSARY_DATA.get(title, "")

def kpi_card(title, value, is_currency=False, size="normal", subtitle=None, icon=None, show_icon=True, borderColor="#cecfd4", bg_color=GRAY_BG,tooltip=None):
    if tooltip is None:
        tooltip = GLOSSARY_DATA.get(title, "")
    display_val = f"${value:,.0f}" if is_currency else f"{value:,.0f}"

    return html.Div([
        html.Div([
                html.Div([html.Img(src=icon) if icon else None ],className="imageWrapper")
            ], className="iconWrapper", style={"borderColor": borderColor}) if show_icon else None,
        html.Div([
            html.Div([
                # if icon else None,
                html.Div(title.upper(), className="tileLabel")
            ], className="d-flex align-items-center justify-content-center"),
            html.Div(display_val, className="tileMetric flash-target")
        ], className="tileValueWrapper"),
    ], className="tileWrapper", title=tooltip, style={
        "backgroundColor": bg_color,
        "borderColor": borderColor
    })


# ------------------------------------------------------------------------
# Shared NAV BAR
def nav_bar():
    return html.Div([
        dcc.Link("Glossary View", href="/glossary", style={"marginRight": "15px"}),
        dcc.Link("Map View", href="/map", style={"marginRight": "15px"}),
        dcc.Link("KPI View", href="/kpi", style={"marginRight": "15px"}),
    ], style={"padding": "10px", "background": "#f1f5f9", "marginBottom": "20px"})

# ------------------------------------------------------------------------
# Glossary VIEW
def glossary_view():
    return html.Div([
        html.Div([
            html.H2("KPI Glossary", className="mb-4 text-center fw-bold", style={"color": "#03579d"}),

            html.Div([
                html.Div([
                    html.Div(term, className="glossary-term fw-bold mb-1"),
                    html.Div(defn, className="glossary-definition text-muted")
                ], className="glossary-card col-md-6 rounded shadow-sm bg-white")
                for term, defn in GLOSSARY_DATA.items()
            ],className="row")
        ], className="glossary_view", style={"padding": "20px"})
    ], style={"margin": "20px"})
# ------------------------------------------------------------------------

# MAP VIEW

def map_view():
    return html.Div([
    html.Div([

        # Hidden Animation Trigger
        html.Div(id="animation-trigger", style={"display": "none"}),

        # KPI + Refresh Time Row
        html.Div([
            html.Div([
                html.H2("TODAY'S ACTIVE BIDDERS :",className="map_label"),
                html.Span(id="active-bidder-count", className="flash-target")
            ], className="col-md-8 d-flex align-items-center"),

            html.Div(
                id='refresh-time-map',
                className="col-md-4 text-end text-muted flash-target"
            )
        ], className="row mb-3"),
        # html.Div(id="flash-card-container", className="flash-card-container"),
        # 🗺️ Map + Interval + Info Panel Overlay
        html.Div([
            dcc.Loading(
                id="map-loading",
                type="circle",
                children=dcc.Graph(id='auction-map',
                    config={
                        "scrollZoom": True,
                        "displayModeBar": True,
                        "doubleClick": "reset",
                        "displaylogo": False
                    },
                    style={
                        "width": "100%",
                        "height": "100%",
                        "minHeight": "580px",
                        "marginTop": "-10px"
                    }
                )
            ),

            # 🎯 Info Panel Overlay
            html.Div([
                # Clickable title bar with toggle icon
                html.Div([
                    html.Span("Active Bidders by Country"),
                    html.Span(id="toggle-icon", className="toggle-icon", children="▼")
                ], id="info-title", className="info-title"),
                
                # Content section that will be toggled
                html.Div([
                    html.Div(id="country-info-panel"),
                ], id="info-content", className="country-list")
            ], id="info-panel", className="info-panel"),
            html.Div(id="flash-card-container", style={
                        "position": "absolute",
                        "top": "20px",
                        "left": "20px",
                        "zIndex": 2000,
                        "pointerEvents": "none"
                    }),
        dcc.Interval(
            id="flash-interval",
            interval=21 * 1000,  # Set to 21 seconds to ensure next card appears after animation finishes
            n_intervals=0,
            disabled=False  # Start enabled to show all countries
        )
        ], style={"position": "relative"}),

        # Auto refresh
        dcc.Interval(id="interval-map", interval=CONFIG["REFRESH_INTERVAL_MS"], n_intervals=0)

    ],
    className="data-container shadow rounded-4 mt-4",
    style={
        "backgroundColor": "white",
        "padding": "20px",
        "borderRadius": "12px",
        "boxShadow": "0px 1px 4px rgba(0,0,0,0.5)",
        "height": "750px"
    })
], className="container-fluid mt-3")


# ------------------------------------------------------------------------
# KPI VIEW
def kpi_view():
    return html.Div([
        # nav_bar(),
        
        html.Div([
        html.Div(id='kpi-section', style={
            "padding": "5px",
            "width": "100%",
            "height": "120px",
            "marginTop": "10px"
        }),
        html.Div(
                    id='refresh-time-kpi',
                    className="flash-target",
                    style={ "color": "gray","display":"none"}
                ),
        dcc.Interval(id="interval-refresh", interval=CONFIG["REFRESH_INTERVAL_MS"], n_intervals=0)
    ], style={
                "display": "flex",
                # "gap": "2%"
               })
    ])

# ------------------------------------------------------------------------
# 404 Error VIEW
def not_found_view():
    return html.Div([
        html.H2("404 - Page Not Found", className="text-center text-danger mt-5"),
        html.P("Sorry, the page you requested does not exist.", className="text-center")
    ])
# ------------------------------------------------------------------------
# Layout with Routing
app.layout = html.Div([
    html.Meta(name="viewport", content="width=device-width, initial-scale=1.0"),
    html.Div([
        html.Div(id="animation-trigger", style={"display": "none"}),
        html.Div([
            # html.Div("Copart: The Source To Buy & Sell Worldwide", className="col-md-6 h1 text-white m-0"),
              html.Img(
                src="/assets/img/head.png", className="img-banner"
                )
        ], className="align-items-center")
    ], className="header-bar"),
    html.Audio(id='refresh-alert-sound',
               src='/assets/audio/refresh_alert_subtle.mp3',  # or base64 string
               autoPlay=False,
               controls=False,
               style={'display': 'none'}),
    # dcc.Interval(id="interval-time", interval=CONFIG["REFRESH_INTERVAL_MS"], n_intervals=0),
    dcc.Location(id='url', refresh=False),
    dcc.Store(id="country-flash-store", data=[], storage_type="memory"),
    dcc.Store(id="info-content-visibility", data=True, storage_type="memory"),
    html.Div(id='page-content'),
    html.Div(id='page-glossary', children=glossary_view(), style={"display": "none"}),
    html.Div(id='page-map', children=map_view(), style={"display": "none"}),
    html.Div(id='page-kpi', children=kpi_view(), style={"display": "none"}),
    html.Div(id='page-not-found', children=not_found_view(), style={"display": "none"}),
])

# Callback for toggling the info panel content
@app.callback(
    Output("info-content", "style"),
    Output("toggle-icon", "children"),
    Output("info-content-visibility", "data"),
    Input("info-title", "n_clicks"),
    State("info-content-visibility", "data")
)
def toggle_info_content(n_clicks, is_visible):
    if n_clicks is None:
        # Initial load, show the content
        return {}, "▼", True
    
    # Toggle visibility
    if is_visible:
        # Hide the content
        return {"display": "none"}, "▶", False
    else:
        # Show the content
        return {}, "▼", True

@app.callback(
    Output("page-map", "style"),
    Output("page-kpi", "style"),
    Output("page-glossary", "style"),
    Output("page-not-found", "style"),
    Input("url", "pathname")
)
def toggle_pages(pathname):
    user_ip = request.remote_addr or "unknown"
    user_agent = request.headers.get("User-Agent", "unknown")
    # timestamp = datetime.utcnow().isoformat()
    logger.info(f"User viewed {pathname} | IP: {user_ip} | Agent: {user_agent}")

    return (
        {"display": "block"} if pathname == "/map" else {"display": "none"},
        {"display": "block"} if pathname in ["/","/kpi"] else {"display": "none"},
        {"display": "block"} if pathname == "/glossary" else {"display": "none"},
        {"display": "block"} if pathname not in ["/map", "/", "/kpi", "/glossary"] else {"display": "none"},
    )
# ------------------------------------------------------------------------
# DataTable content callback (only applies when on /table)

app.clientside_callback(
    """
     function(bidderCount, n_map, refreshTime) {
        // Play alert sound first
        var audio = document.getElementById('refresh-alert-sound');
        if (audio) {
            audio.currentTime = 0;
            audio.play().catch(err => {
                console.warn('Audio play failed:', err);
            });
        }

        // Function to add split-flap sound effect (optional)
        function playFlipSound() {
            // You can add a subtle click sound here if desired
            // var flipAudio = document.getElementById('flip-sound');
            // if (flipAudio) flipAudio.play();
        }

        // Enhanced animation function with random digit effect
        function animateWithRandomDigits(element) {
            const originalText = element.textContent;
            const isNumber = /[\d,.$]/.test(originalText);
            
            if (!isNumber) {
                // For non-numeric content, use regular flash animation
                element.classList.add('flash-update');
                return;
            }

            // Store original text
            element.setAttribute('data-original', originalText);
            
            // Create random intermediate values for more realistic effect
            const steps = 3;
            let currentStep = 0;
            
            function randomizeStep() {
                if (currentStep >= steps) {
                    // Final step: restore original text with animation
                    element.textContent = element.getAttribute('data-original');
                    element.classList.add('flash-update');
                    return;
                }
                
                // Generate random version of the text
                const randomText = originalText.replace(/\d/g, () => 
                    Math.floor(Math.random() * 10).toString()
                );
                
                element.textContent = randomText;
                element.classList.add('flash-update');
                
                // Remove class after animation, then continue
                setTimeout(() => {
                    element.classList.remove('flash-update');
                    currentStep++;
                    setTimeout(randomizeStep, 100);
                }, 300);
            }
            
            randomizeStep();
        }

        // Get all elements
        const kpiElements = document.querySelectorAll('.tileMetric.flash-target');
        const otherElements = document.querySelectorAll('.flash-target:not(.tileMetric)');
        
        // Update non-KPI elements immediately
        otherElements.forEach(el => {
            el.classList.remove('flash-update');
            void el.offsetWidth;
            el.classList.add('flash-update');
        });
        
        // Remove existing animations from KPI elements
        kpiElements.forEach(el => {
            el.classList.remove('flash-update');
        });

        // Force reflow
        void document.body.offsetWidth;

        // Sequential animation function
        function animateSequentially(elementArray, index = 0) {
            if (index >= elementArray.length) {
                return;
            }

            // Play flip sound effect
            playFlipSound();
            
            // Animate current element with random digit effect
            animateWithRandomDigits(elementArray[index]);
            
            // Schedule next element
            setTimeout(() => {
                animateSequentially(elementArray, index + 1);
            }, 1000);
        }

        // Start sequential animation
        if (kpiElements.length > 0) {
            animateSequentially(Array.from(kpiElements));
        }

        return window.dash_clientside.no_update;
    }
    """,
    Output("animation-trigger", "children"),
    Input("active-bidder-count", "children"),  
    Input("interval-map", "n_intervals"),
)

@app.callback(
    Output("refresh-time-map", "children"),
    Output("auction-map", "figure"),
    Output("active-bidder-count", "children"),
    Output("country-info-panel", "children"), 
    Output("country-flash-store", "data"),
    Input("interval-map", "n_intervals"),
    Input("url", "pathname"),
    State("country-flash-store", "data")
    # prevent_initial_call=True
)
def update_map(n,pathname,prev_store):
    if pathname != "/map":
        raise dash.exceptions.PreventUpdate
    
    logger.info("Refreshing map view")
    summary = fetch_bidder_summary_safe()
    
    bidders_val = summary.get("bidders")
    active_bidders = f"{int(bidders_val):,}" if bidders_val else "-"    
    
    updated = (
        pd.to_datetime(summary['last_up_date'])
        .tz_localize('UTC')
        .astimezone(ZoneInfo("America/Chicago"))
        .strftime("Last Updated: %b %d, %Y %I:%M %p") if summary.get("last_up_date") else "Last Updated: -"
    )


    logger.info(f"Last updated timestamp Map: {summary.get('last_up_date')}")

    dataMap = get_cached_data()
    dfMap = pd.DataFrame(dataMap.get("map", []))

    logger.debug(f"Fetched {len(dfMap)} rows for map")

    if dfMap.empty or "lat" not in dfMap.columns or "long" not in dfMap.columns:
        fig = px.scatter_mapbox(
            pd.DataFrame(columns=["lat", "long"]),
            lat="lat", lon="long",
            zoom=2, mapbox_style="carto-positron"
        )
        empty_panel = html.Div("No country data available", className="text-muted")
        # Return an empty list for country-flash-store
        return updated, fig, bidders_val, empty_panel, []


    if "country_long_name" in dfMap.columns and "unique_bidders" in dfMap.columns:
        # Sort by unique_bidders descending
        df_sorted = dfMap.sort_values("unique_bidders", ascending=False)

        country_panel = [
	        html.Div([
	            html.Span(row["country_long_name"]),
	            html.Span(f"{int(row['unique_bidders']):,}", className="bidder-count")
	        ], className="country-item")
	        for _, row in df_sorted.iterrows()
	    ]
    else:
        country_panel = html.Div("No country data available", className="info-title text-muted")

    prev_map = {item["country"]: item["count"] for item in (prev_store or [])}
    
    # Create new store with all countries, marking which ones have changed
    new_store = []
    for _, r in df_sorted.iterrows():
        country_name = r["country_long_name"]
        count = int(r["unique_bidders"]) if r["unique_bidders"] else 0
        # Mark as not displayed if the count changed or it's a new country
        is_changed = prev_map.get(country_name) != count
        new_store.append({
            "country": country_name,
            "count": count,
            "displayed": not is_changed,  # Only mark as not displayed if changed
            "changed": is_changed
        })
    
    # For initial display, show the first flash card
    flash_card = None
    for item in new_store:
        if not item["displayed"]:
            flash_card = html.Div([
                html.Div(item["country"], className="flash-country"),
                html.Div(f"{item['count']:,} Bidders", className="flash-count"),
                html.Div(html.Div(className="flash-progress-inner"), className="flash-progress")
            ], className="flash-card")
            # Don't mark as displayed yet - let the interval callback handle it
            break

    # Clean and ensure numeric types
    dfMap = dfMap.dropna(subset=["lat", "long", "bid_counts"])  # Drop rows with missing required values
    dfMap["lat"] = pd.to_numeric(dfMap["lat"], errors="coerce")
    dfMap["long"] = pd.to_numeric(dfMap["long"], errors="coerce")
    dfMap["bid_counts"] = pd.to_numeric(dfMap["bid_counts"], errors="coerce")
    dfMap["unique_bidders"] = pd.to_numeric(dfMap["unique_bidders"], errors="coerce")
    dfMap["dollars_bid"] = pd.to_numeric(dfMap["dollars_bid"], errors="coerce")
    dfMap["highest_bid_placed"] = pd.to_numeric(dfMap["highest_bid_placed"], errors="coerce")

    # Drop any rows with null lat/lon
    dfMap = dfMap.dropna(subset=["lat", "long"])

    # Format values
    dfMap['lat'] = dfMap['lat'].round(2)
    dfMap['long'] = dfMap['long'].round(2)
    # dfMap["marker_size"] = dfMap["bid_counts"].clip(lower=20)

    min_size = 2
    max_size = 25

    min_bid = dfMap["unique_bidders"].min()
    max_bid = dfMap["unique_bidders"].max()

    # Avoid divide-by-zero
    if min_bid == max_bid:
        dfMap["marker_size"] = min_size
    else:
        dfMap["marker_size"] = min_size + (dfMap["unique_bidders"] - min_bid) * (max_size - min_size) / (max_bid - min_bid)

    # Add realtime flag using last_5_minutes estimation:
    dfMap["is_live"] = dfMap["unique_bidders"] > 0  # you can customize this condition

    # Use different marker color or size for live participants:
    dfMap["marker_color"] = dfMap["is_live"].map(lambda x: "#00b050" if x else  "#00ff00")

    fig = px.scatter_mapbox(
        dfMap,
        lat="lat",
        lon="long",
        # text="country_long_name",
        size="marker_size",           # Pre-scaled column
        size_max=max_size, 
        # size_min=15,
        hover_name="country_long_name",
        hover_data={
            "country_long_name": False,
            "bid_counts": True,
            "unique_bidders": True,
            "dollars_bid": True,
            "highest_bid_placed": True,
            "lat": False,
            "long": False,
            "marker_size":False
        },
        zoom=1.5,
        mapbox_style="carto-positron"
        # color_discrete_sequence=dfMap["marker_color"]
    )
    fig.update_layout(
        hovermode="closest",
        autosize=True,
        uirevision='static',
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        paper_bgcolor="#ffffff",
        font={"color": "#111827"},
        coloraxis_showscale=False
    )
    fig.update_traces(
        marker=dict( color=dfMap["marker_color"],sizemode="area",  opacity=0.8), 
        customdata=dfMap[[
                "country_long_name",
                "bid_counts",
                "unique_bidders",
                "dollars_bid",
                "highest_bid_placed"
            ]],
        hovertemplate="<b>%{customdata[0]}</b><br>" +
                  "Bids: %{customdata[1]:,}<br>" +
                  "Bidders: %{customdata[2]:,}<br>" 
                #   "Dollars Bid: $%{customdata[3]:,}<br>" +
                #   "Highest Bid: $%{customdata[4]:,}<extra></extra>"

    )
    # Initialize all countries to be shown in flash cards
    # Add index for tracking order and set all to not displayed
    for i, item in enumerate(new_store):
        item["index"] = i
        # Always set displayed to False to show all countries every time
        item["displayed"] = False
    
    # Return data without flash card
    return updated, fig, active_bidders, country_panel, new_store

# Callback for flash card display
@app.callback(
    Output("flash-card-container", "children"),
    Input("country-flash-store", "data"),
    Input("flash-interval", "n_intervals"),
    Input("url", "pathname"),
    prevent_initial_call=False
)
def show_flash_card(store_data, n_intervals, pathname):
    """Show a flash card for the current country being displayed"""
    global current_flash_index
    
    # Only proceed on map page with valid data
    if pathname != "/map" or not store_data or len(store_data) == 0:
        return None
    
    # Debug info
    logger.info(f"Flash interval triggered: n_intervals={n_intervals}")
    
    # Count displayed vs total countries
    total_countries = len(store_data)
    displayed_countries = sum(1 for item in store_data if item.get("displayed", True))
    undisplayed_countries = total_countries - displayed_countries
    
    logger.info(f"Countries - Total: {total_countries}, Displayed: {displayed_countries}, Undisplayed: {undisplayed_countries}")
    
    # Find the first undisplayed country
    current_country = None
    for item in store_data:
        if not item.get("displayed", True):
            current_country = item
            break
    
    # If we have a country to display, create the flash card
    if current_country:
        logger.info(f"Showing flash card for country: {current_country['country']} with {current_country['count']} bidders")
        
        # Get a color gradient based on the country's region
        country_name = current_country["country"]
        background_gradient = None
        region_name = "Other"
        
        # Check which region the country belongs to
        for region, data in REGION_COLORS.items():
            if country_name in data["countries"]:
                background_gradient = data["gradient"]
                region_name = region
                logger.info(f"Using {region} color scheme for {country_name}")
                break
        
        # If no region found, use a random gradient
        if not background_gradient:
            # Use the country name as a seed for consistent colors per country
            import hashlib
            country_hash = int(hashlib.md5(country_name.encode()).hexdigest(), 16)
            random_index = country_hash % len(RANDOM_GRADIENTS)
            background_gradient = RANDOM_GRADIENTS[random_index]
            logger.info(f"Using random color scheme for {country_name} (index {random_index})")
        
        # Create a custom style for the flash card with the selected gradient
        custom_style = {
            "position": "relative",
            "background": background_gradient,
            "color": "white",
            "borderRadius": "12px",
            "padding": "16px",
            "minWidth": "240px",
            "fontFamily": "'Segoe UI', sans-serif",
            "boxShadow": "0 4px 14px rgba(0,0,0,0.2)",
            "animation": "none",  # Override the CSS animation to prevent fading out
            "zIndex": 2000
        }
        
        # Create a flash card with a unique key to force re-render
        flash_card = html.Div([
            # Country name
            html.Div(current_country["country"], className="flash-country"),
            
            # Bid count
            html.Div(f"{current_country['count']:,} bidders", className="flash-count"),
            
            # Progress bar
            html.Div(html.Div(className="flash-progress-inner"), className="flash-progress")
        ], 
        className="flash-card", 
        key=f"flash-{n_intervals}-{current_country['country']}",
        style=custom_style)
        
        return flash_card
    
    # No countries to display
    logger.info("No more countries to display")
    return None

# Separate callback for managing the flash interval
@app.callback(
    Output("flash-interval", "disabled"),
    Input("country-flash-store", "data"),
    Input("url", "pathname"),
    prevent_initial_call=False
)
def manage_flash_interval(store_data, pathname):
    """Control whether the flash interval is enabled based on undisplayed countries"""
    # Only proceed on map page with valid data
    if pathname != "/map" or not store_data or len(store_data) == 0:
        return True
    
    # Check if we have any undisplayed countries
    has_undisplayed = any(not item.get("displayed", True) for item in store_data)
    
    # Disable interval if no undisplayed countries
    return not has_undisplayed

# Shared state for tracking the current flash card
current_flash_index = 0

# Define color schemes for different geographical regions
REGION_COLORS = {
    # North and South America (blues)
    "North America": {
        "countries": ["United States", "Canada", "Mexico"],
        "gradient": "linear-gradient(90deg, #1e88e5, #64b5f6)"
    },
    "South America": {
        "countries": ["Brazil", "Argentina", "Chile", "Colombia", "Peru", "Venezuela", "Ecuador", "Bolivia", "Paraguay", "Uruguay"],
        "gradient": "linear-gradient(90deg, #0d47a1, #42a5f5)"
    },
    # Europe (greens)
    "Europe": {
        "countries": ["United Kingdom", "France", "Germany", "Italy", "Spain", "Netherlands", "Belgium", 
                     "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Ireland", "Poland", 
                     "Portugal", "Greece", "Czech Republic", "Romania", "Hungary"],
        "gradient": "linear-gradient(90deg, #2e7d32, #66bb6a)"
    },
    # Asia and Oceania (purples/pinks)
    "Asia": {
        "countries": ["China", "Japan", "India", "South Korea", "Indonesia", "Malaysia", "Singapore", 
                     "Thailand", "Vietnam", "Philippines", "Saudi Arabia", "United Arab Emirates", 
                     "Israel", "Turkey", "Russia", "Pakistan", "Bangladesh", "Hong Kong"],
        "gradient": "linear-gradient(90deg, #7b1fa2, #ba68c8)"
    },
    "Oceania": {
        "countries": ["Australia", "New Zealand", "Papua New Guinea", "Fiji"],
        "gradient": "linear-gradient(90deg, #c2185b, #f06292)"
    },
    # Africa (oranges/yellows)
    "Africa": {
        "countries": ["South Africa", "Nigeria", "Egypt", "Morocco", "Kenya", "Ghana", "Ethiopia", 
                     "Tanzania", "Uganda", "Algeria", "Tunisia", "Cameroon", "Ivory Coast", "Angola", "Senegal"],
        "gradient": "linear-gradient(90deg, #e65100, #ffb74d)"
    }
}

# Random color gradients for countries not in any defined region
RANDOM_GRADIENTS = [
    "linear-gradient(90deg, #d32f2f, #ef5350)",  # Red
    "linear-gradient(90deg, #00796b, #4db6ac)",  # Teal
    "linear-gradient(90deg, #303f9f, #7986cb)",  # Indigo
    "linear-gradient(90deg, #00695c, #4db6ac)",  # Dark Teal
    "linear-gradient(90deg, #0097a7, #4dd0e1)",  # Cyan
    "linear-gradient(90deg, #388e3c, #81c784)",  # Light Green
    "linear-gradient(90deg, #5d4037, #a1887f)",  # Brown
    "linear-gradient(90deg, #616161, #bdbdbd)",  # Grey
]

# Callback to mark countries as displayed when the interval triggers
@app.callback(
    Output("country-flash-store", "data", allow_duplicate=True),
    Input("flash-interval", "n_intervals"),
    State("country-flash-store", "data"),
    State("url", "pathname"),
    prevent_initial_call=True
)
def mark_country_displayed(n_intervals, store_data, pathname):
    """Mark the current country as displayed when the interval triggers"""
    global current_flash_index
    
    # Only proceed on map page with valid data
    if pathname != "/map" or not store_data or len(store_data) == 0:
        raise dash.exceptions.PreventUpdate
    
    # Create a copy of the store
    updated_store = store_data.copy()
    
    # Get a list of undisplayed countries
    undisplayed = [i for i, item in enumerate(updated_store) if not item.get("displayed", True)]
    
    if not undisplayed:
        # All countries have been displayed
        raise dash.exceptions.PreventUpdate
    
    # Mark the next country as displayed
    index_to_mark = undisplayed[0]
    updated_store[index_to_mark]["displayed"] = True
    
    # Log the update
    country_name = updated_store[index_to_mark]["country"]
    logger.info(f"Marking country as displayed: {country_name} (index {index_to_mark})")
    
    # Increment the current flash index
    current_flash_index += 1
    
    return updated_store

@app.callback(
    Output('refresh-time-kpi', 'children'),
    Output('kpi-section', 'children'),
    Input('interval-refresh', 'n_intervals'),
    Input("url", "pathname"),
    prevent_initial_call=True
)
def update_kpi(n,pathname):
    if pathname not in ["/",'/kpi']:
        raise dash.exceptions.PreventUpdate
    
    kpi_data = get_cached_data()
    data = kpi_data.get("kpis", {})
    logger.info("Refreshing KPI view")
    
    summary = kpi_data.get("summary", {})
    raw_ts = summary.get("last_up_date")    

    if raw_ts:
        try:
            parsed_dt  = (
                pd.to_datetime(raw_ts, utc=True)
                # .tz_localize('UTC')
                .astimezone(ZoneInfo("America/Chicago"))
            )
            now_date = parsed_dt.strftime("%b %d, %Y")
            now_time = parsed_dt.strftime("%I:%M %p")
        except Exception:
            now_date = ""
            now_time = ""
    else:
        now_date = ""
        now_time = ""

    refresh_label = f"Last Updated: {now_date} | {now_time} "

    
    return refresh_label, html.Div([

    html.Div([
        html.Div([  # Row wrapper
            # LEFT COLUMN: Today's KPIs (2-wide cards)
            html.Div([
                html.Div(f"SINCE 12:00:00 AM TODAY, {now_date}", style={"backgroundColor":"#005a99","marginBottom":"15px"}, className="text-white text-center fw-bold p-2 metricHeader rounded-top"),
                html.Div([
                    # kpi_card("Vehicles Sold", data["lots_sold"]["today"], show_icon=True, icon="/assets/img/vehiclessold.png"),
                    kpi_card("Bids Received", data["bids_received"]["today"], show_icon=True, icon="/assets/img/bidsreceived.png",
                            #  tooltip="Bids Received Today"
                             ),
                    kpi_card("Bidder Countries", data["bidder_countries"]["today"], show_icon=True,icon="/assets/img/biddercountries.png",
                            #  tooltip="Bidder Countries"
                             ),
                    kpi_card("Unique Bidders", data["unique_bidders"]["today"], show_icon=True, icon="/assets/img/uniquebidders.png",
                            #  tooltip="Unique Bidders"
                             ),
                    kpi_card("Auction Events Run", data["auction_events_run"]["today"], show_icon=True, icon="/assets/img/auctionevents.png",
                            #  tooltip="Auction Events Run"
                             ),
                    kpi_card("Highest Bid Placed", data["highest_bid_placed"]["today"], show_icon=True, is_currency=True,bg_color=GREEN_BG, borderColor="#aed5b8", 
                            icon="/assets/img/highestbid.png", 
                            # tooltip="Highest Bid Placed"
                            ),
                    # kpi_card("Gross Value", data["gross_value_sold"]["today"], show_icon=True, is_currency=True,bg_color=GREEN_BG, borderColor="#aed5b8"
                    #          ,icon="/assets/img/grossvalue.png",
                    #            ),
                    kpi_card("Transaction Value", data["net_value_sold"]["today"], show_icon=True, is_currency=True,bg_color=GREEN_BG, borderColor="#aed5b8"
                             , icon="/assets/img/netvalue.png", 
                             ),
                     html.Div(kpi_card("Total Dollars Bid", data["dollars_bid"]["today"], show_icon=True, is_currency=True,bg_color=GREEN_BG, borderColor="#aed5b8"
                             ,icon="/assets/img/totaldollars.png",
                            #    tooltip="Total Dollars Bid"
                               ),style={"width": "97.5%","padding": "0","margin": "0"})
                    # html.Div(kpi_card("Total Dollars Bid", data["dollars_bid"]["today"], show_icon=True, is_currency=True,bg_color=GREEN_BG, borderColor="#aed5b8",icon="/assets/img/totaldollars.png"),
                    #           style={"width": "97.5%","padding": "0","margin": "0"})
                ], className="row row-cols-1 row-cols-md-2 g-3")
            ], className="col-md-8 currentKPI"),

            # RIGHT COLUMN: Last Year KPIs
            html.Div([
                html.Div("LAST 12 MONTHS", style={"backgroundColor":"#005a99"}, className="text-white text-center fw-bold p-2 metricHeader rounded-top"),
                html.Div([
                    # kpi_card("Vehicles Sold", data["lots_sold"]["ly"], show_icon=False),
                    kpi_card("Unique Bidders", data["unique_bidders"]["ly"], show_icon=False,
                            #   tooltip="Unique Bidders"
                              ),
                    kpi_card("Total Bids", data["bids_received"]["ly"], show_icon=False,
                            #   tooltip="Total Bids"
                              ),
                    kpi_card("Transaction Value", data["net_value_sold"]["ly"], show_icon=False, is_currency=True,bg_color=GREEN_BG, 
                             ),
                    kpi_card("Dollars Bid", data["dollars_bid"]["ly"], show_icon=False, is_currency=True,bg_color=GREEN_BG)
                    
                ], className="lastYearMetricWrapper"),
                html.Div([
                    html.Div([
                         html.Span("Today's live data: US and Canada combined", className="text-success updateInfo"),
                    ], style={"marginLeft": "10%"}),
                    html.Div([
                        html.Span(f" Last Updated: {now_date} | {now_time}", className="text-muted ms-2")
                    ], style={"marginLeft": "9%"}),
                ], className="mt-3 check-icon")
            ], className="col-md-4 lastYearKPI")
            
        ], className="row")
    ]),

], className="container-fluid p-4")

# ------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(
        debug=CONFIG["DEBUG"],
        port=CONFIG["PORT"],
        host="0.0.0.0"
    )
