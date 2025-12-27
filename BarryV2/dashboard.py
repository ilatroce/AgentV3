import streamlit as st
import pandas as pd
import time
import sys
import os
import re

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_utils

# --- 🎨 CONFIGURATION ---
st.set_page_config(
    page_title="Happy Harbor | Live Feed",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- ✨ ELEGANT CSS (White & Green) ---
st.markdown("""
<style>
    /* 1. Force White Background */
    .stApp {
        background-color: #ffffff;
        color: #1a202c;
        font-family: 'Helvetica Neue', sans-serif;
    }
    
    /* 2. Green Shaded Sections (Cards) */
    .green-card {
        background-color: #f0fff4; /* Mint Green */
        border-left: 5px solid #48bb78; /* Strong Green Line */
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 25px;
    }
    
    /* 3. Typography */
    h1, h2, h3 {
        color: #2f855a; /* Dark Green Text */
        font-weight: 700;
    }
    p, span, div {
        color: #2d3748;
    }
    
    /* 4. Streamlit Metric Overrides */
    div[data-testid="stMetricValue"] {
        color: #22543d !important; /* Dark Green Numbers */
    }
    
    /* 5. Hide Streamlit Elements for Cleanliness */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- 🔄 FAST REFRESH (Every 5s for "Live" feel) ---
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 10:
    st.session_state.last_refresh = time.time()
    st.rerun()

# --- ⚓ HEADER ---
st.title("⚓ Happy Harbor Live Feed")
st.caption(f"Connected to Hyperliquid | Last Update: {pd.Timestamp.now().strftime('%H:%M:%S')}")

# --- 🕸️ SECTION 1: MARKET RADAR (Grid Scanner) ---
st.markdown('<div class="green-card">', unsafe_allow_html=True)
st.subheader("🕸️ Volatility Radar (Grid Scanner)")

alerts = db_utils.get_grid_alerts(limit=50)

if alerts:
    df_grid = pd.DataFrame(alerts)

    # Parser Logic
    def parse_grid_reason(reason):
        pump_match = re.search(r'Pumped \+([\d\.]+)%', reason)
        pump = float(pump_match.group(1)) if pump_match else 0.0
        
        shrink_match = re.search(r'Consolidated \(([\d\.]+)x\)', reason)
        shrink = float(shrink_match.group(1)) if shrink_match else 1.0
        return pd.Series([pump, shrink])

    df_grid[['pump_pct', 'shrink_factor']] = df_grid['reason'].apply(parse_grid_reason)
    df_display = df_grid[['symbol', 'pump_pct', 'shrink_factor', 'created_at']].copy()
    
    # Simple Style
    st.dataframe(
        df_display,
        column_config={
            "symbol": "Asset",
            "pump_pct": st.column_config.ProgressColumn(
                "24h Pump", format="%d%%", min_value=0, max_value=100
            ),
            "shrink_factor": st.column_config.NumberColumn(
                "Shrink (Risk)", format="%.2fx"
            ),
            "created_at": st.column_config.DatetimeColumn(
                "Time Detected", format="HH:mm:ss"
            )
        },
        width="stretch",  # <--- FIXED WARNING
        hide_index=True,
        height=300
    )
else:
    st.info("Scanner is quiet. No high-volatility targets found.")

st.markdown('</div>', unsafe_allow_html=True)


# --- 🤖 SECTION 2: EXECUTION LOGS ---
st.markdown('<div class="green-card">', unsafe_allow_html=True)
st.subheader("🤖 Bot Activity Log")

logs = db_utils.get_recent_logs(limit=50)

if logs:
    df_logs = pd.DataFrame(logs)
    
    # Filter out the GRID alerts from the main log to avoid duplicate noise
    # (Assuming we only want trade execution / system events here)
    df_logs = df_logs[df_logs['operation'] != 'GRID_ALERT']

    st.dataframe(
        df_logs,
        width="stretch", # <--- FIXED WARNING
        height=400,
        hide_index=True,
        column_config={
            "created_at": st.column_config.DatetimeColumn("Timestamp", format="HH:mm:ss"),
            "operation": "Action",
            "symbol": "Symbol",
            "direction": "Side",
            "reason": "Logic / Signal"
        }
    )
else:
    st.caption("No recent trading activity.")

st.markdown('</div>', unsafe_allow_html=True)
