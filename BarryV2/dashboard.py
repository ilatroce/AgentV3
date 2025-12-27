import streamlit as st
import pandas as pd
import time
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_utils

# --- 🖥️ CONFIGURATION ---
st.set_page_config(
    page_title="Terminal",
    page_icon="💻",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- ⬛ PURE BLACK TERMINAL CSS ---
st.markdown("""
<style>
    /* 1. Force Pure Black Background */
    .stApp {
        background-color: #000000 !important;
    }
    
    /* 2. Hide Header/Footer for full immersion */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    
    /* 3. Terminal Font */
    body, p, div, span, pre, code {
        color: #00ff41 !important; /* Matrix Green Text */
        font-family: 'Courier New', Courier, monospace !important;
        font-size: 14px;
    }

    /* 4. Remove Streamlit Padding */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- 🔄 AUTO REFRESH (Every 2s for "Real-time" feel) ---
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 2:
    st.session_state.last_refresh = time.time()
    st.rerun()

# --- 💻 THE LOGIC ---
# We fetch BOTH Grid Alerts and Regular Logs in one go
# We need a custom query or just fetch raw logs if get_recent_logs handles it.
# db_utils.get_recent_logs fetches from 'bot_operations' which includes EVERYTHING.
raw_logs = db_utils.get_recent_logs(limit=200)

if raw_logs:
    terminal_output = []
    
    for log in raw_logs:
        # 1. Parse Timestamp
        # Handle cases where created_at might be string or datetime
        ts_val = log.get('created_at')
        if isinstance(ts_val, pd.Timestamp) or hasattr(ts_val, 'strftime'):
            ts = ts_val.strftime('%H:%M:%S')
        else:
            ts = str(ts_val).split('T')[-1].split('.')[0] # Fallback
            
        # 2. Extract Fields
        op = log.get('operation', 'UNKNOWN')
        sym = log.get('symbol') or "---"
        direction = log.get('direction') or "-"
        reason = log.get('reason') or "No details"
        
        # 3. Format the Line (Terminal Style)
        # Example: [22:05:10] GRID_ALERT   | BTC    | PUMPED +15% ...
        line = f"[{ts}] {op:<12} | {sym:<6} | {direction:<4} | {reason}"
        terminal_output.append(line)

    # Join with newlines
    full_log_text = "\n".join(terminal_output)
    
    # Display as a Code Block (Preserves spacing, monospaced, scrollable)
    st.text(f"root@happy-harbor:~# tail -f /var/log/trading_bot.log\n\n{full_log_text}")

else:
    st.text("root@happy-harbor:~# Waiting for logs...")
