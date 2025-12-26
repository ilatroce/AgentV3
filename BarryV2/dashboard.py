import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import sys
import os
import re

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_utils

# --- 🎨 CONFIG & STYLE ---
st.set_page_config(
    page_title="AgentV3 | Happy Harbor",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for that "Modern Dark Mode" feel
st.markdown("""
<style>
    .stApp {
        background-color: #0e1117;
    }
    .metric-card {
        background-color: #1e2127;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #2e3138;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .big-font {
        font-size: 24px !important;
        font-weight: 700;
        color: #ffffff;
    }
    .sub-font {
        font-size: 14px !important;
        color: #a0a0a0;
    }
</style>
""", unsafe_allow_html=True)

# --- 🔄 AUTO REFRESH ---
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 30:
    st.session_state.last_refresh = time.time()
    st.rerun()

# --- 🦜 HEADER ---
col1, col2 = st.columns([1, 5])
with col1:
    # Use emoji or local image
    st.write("## ⚓")
with col2:
    st.title("Happy Harbor Command Center")
    st.caption(f"Live Feed | Auto-refreshing every 30s | Last Update: {pd.Timestamp.now().strftime('%H:%M:%S')}")

st.divider()

# --- 🕸️ TAB 1: GRID HUNTER (NEW!) ---
# We put this first since it's your current focus
tab_grid, tab_ops, tab_pnl = st.tabs(["🕸️ Grid Hunter", "🤖 Bot Operations", "💰 P&L Analysis"])

with tab_grid:
    st.subheader("Volatility & Consolidation Scanner")
    
    # 1. Fetch Data
    alerts = db_utils.get_grid_alerts(limit=50)
    
    if alerts:
        # Convert to DataFrame
        df_grid = pd.DataFrame(alerts)
        
        # Parse 'reason' column to extract metrics
        # Expected format: "Pumped +15% & Consolidated (0.50x)" or "Vol: 1.50%, Chop: 55.0"
        def parse_grid_reason(reason):
            # Try to extract "Pumped +XX%"
            pump_match = re.search(r'Pumped \+([\d\.]+)%', reason)
            pump = float(pump_match.group(1)) if pump_match else 0.0
            
            # Try to extract "Consolidated (0.XXx)"
            shrink_match = re.search(r'Consolidated \(([\d\.]+)x\)', reason)
            shrink = float(shrink_match.group(1)) if shrink_match else 1.0
            
            return pd.Series([pump, shrink])

        # Apply parsing
        df_grid[['pump_pct', 'shrink_factor']] = df_grid['reason'].apply(parse_grid_reason)
        
        # Clean up Display Data
        df_display = df_grid[['symbol', 'pump_pct', 'shrink_factor', 'created_at', 'reason']].copy()
        
        # Calculate a "Hot Score" for sorting (Higher Pump + Lower Shrink = Better)
        df_display['hot_score'] = (df_display['pump_pct'] / 20) + (1 - df_display['shrink_factor'])
        df_display = df_display.sort_values(by='created_at', ascending=False)

        # 2. TOP METRICS ROW
        if not df_display.empty:
            top_pick = df_display.iloc[0]
            m1, m2, m3, m4 = st.columns(4)
            
            with m1:
                st.metric("🔥 Top Alert", top_pick['symbol'], f"+{top_pick['pump_pct']:.0f}% Pump")
            with m2:
                # Color code shrink: Green is good (<0.6), Red is bad (>0.8)
                shrink_val = top_pick['shrink_factor']
                delta_color = "normal" if shrink_val < 0.6 else "inverse"
                st.metric("📉 Contraction", f"{shrink_val}x", "Target: <0.60x", delta_color=delta_color)
            with m3:
                st.metric("⏱️ Spotted", pd.to_datetime(top_pick['created_at']).strftime('%H:%M:%S'))
            with m4:
                st.metric("🤖 Active Scanner", "GridScanner", "Running")

        # 3. FASHIONABLE DATAFRAME
        st.write("### 🎯 Live Opportunities")
        
        st.dataframe(
            df_display,
            column_config={
                "symbol": "Coin",
                "pump_pct": st.column_config.ProgressColumn(
                    "24h Pump %",
                    help="How much it pumped before stalling",
                    format="%d%%",
                    min_value=0,
                    max_value=100,
                ),
                "shrink_factor": st.column_config.NumberColumn(
                    "Shrink Factor",
                    help="1.0 = Max Volatility, 0.5 = Half Volatility (Consolidated)",
                    format="%.2fx"
                ),
                "created_at": st.column_config.DatetimeColumn(
                    "Detected At",
                    format="D MMM, HH:mm:ss"
                ),
                "reason": "Raw Signal",
                "hot_score": st.column_config.LineChartColumn(
                    "Signal Quality"
                )
            },
            use_container_width=True,
            hide_index=True,
            height=400
        )
    else:
        st.info("🕸️ No Grid Alerts found yet. Scanner is searching...")


# --- 🤖 TAB 2: OPERATIONS ---
with tab_ops:
    st.subheader("System Logs")
    
    logs = db_utils.get_recent_logs(limit=100)
    if logs:
        df_logs = pd.DataFrame(logs)
        
        # Color code operations
        def color_op(val):
            color = "gray"
            if "BUY" in val or "OPEN" in val: color = "green"
            elif "SELL" in val or "CLOSE" in val: color = "red"
            elif "GRID" in val: color = "purple"
            return f'color: {color}; font-weight: bold'

        st.dataframe(
            df_logs,
            use_container_width=True,
            height=500,
            hide_index=True,
            column_config={
                "created_at": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
                "operation": "Action",
                "symbol": "Ticker",
                "direction": "Side",
                "reason": "Logic"
            }
        )
    else:
        st.write("No logs available.")

# --- 💰 TAB 3: PnL (Placeholder) ---
with tab_pnl:
    st.write("### Performance Metrics")
    st.info("Connect this to your Hyperliquid Account Balance history later!")
    
    # Mock Data for Visual
    dates = pd.date_range(start="2025-01-01", periods=10)
    values = [100, 102, 105, 103, 108, 115, 120, 118, 125, 130]
    fig = px.area(x=dates, y=values, title="Equity Curve (Simulation)")
    fig.update_layout(plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="white")
    st.plotly_chart(fig, use_container_width=True)

# Footer
st.markdown("---")
st.caption("Agent V3 'Happy Harbor' | Built with Streamlit & Hyperliquid")
