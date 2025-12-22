import streamlit as st
import pandas as pd
import plotly.express as px
import os
import time
from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.utils import constants

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Happy Harbor",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- LOAD SECRETS ---
load_dotenv()
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

# --- CUSTOM CSS (THEME) ---
st.markdown("""
    <style>
    .main {
        background-color: #0E1117;
    }
    .metric-card {
        background-color: #262730;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #41444C;
        text-align: center;
    }
    h1, h2, h3 {
        color: #FFFFFF;
    }
    </style>
    """, unsafe_allow_html=True)

# --- HEADER ---
st.title("⚓ Happy Harbor")
st.markdown("### Trading Bot Hosting & Analytics")
st.markdown("---")

# --- DATA FETCHING ---
@st.cache_data(ttl=60) # Cache data for 60 seconds to prevent API spam
def fetch_data():
    if not WALLET_ADDRESS:
        return None, None
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # 1. Get User State (Balance & Positions)
    user_state = info.user_state(WALLET_ADDRESS)
    
    # 2. Get Trade History (Fills)
    fills = info.user_fills(WALLET_ADDRESS)
    
    return user_state, fills

try:
    if not WALLET_ADDRESS:
        st.error("⚠️ WALLET_ADDRESS not found in environment variables.")
        st.stop()

    user_state, fills = fetch_data()
    
    # --- METRICS CALCULATION ---
    # 1. Account Value
    margin_summary = user_state['marginSummary']
    account_value = float(margin_summary['accountValue'])
    pnl_history = float(margin_summary['totalNtlPos']) # Unrealized PnL
    
    # 2. Process Trade History (Barry's Performance)
    if fills:
        df_fills = pd.DataFrame(fills)
        df_fills['closedPnl'] = df_fills['closedPnl'].astype(float)
        df_fills['time'] = pd.to_datetime(df_fills['time'], unit='ms')
        
        # Filter only closed trades (where PnL is not 0)
        closed_trades = df_fills[df_fills['closedPnl'] != 0].copy()
        
        total_trades = len(closed_trades)
        if total_trades > 0:
            total_pnl = closed_trades['closedPnl'].sum()
            winning_trades = closed_trades[closed_trades['closedPnl'] > 0]
            win_rate = (len(winning_trades) / total_trades) * 100
            best_trade = closed_trades['closedPnl'].max()
            worst_trade = closed_trades['closedPnl'].min()
        else:
            total_pnl = 0
            win_rate = 0
            best_trade = 0
            worst_trade = 0
    else:
        total_trades = 0
        total_pnl = 0
        win_rate = 0
        best_trade = 0
        worst_trade = 0

    # --- DASHBOARD LAYOUT ---

    # Row 1: The "Leaderboard" (Metrics)
    st.subheader(f"🤖 Agent: Barry (Trend Follower)")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(label="💰 Portfolio Value", value=f"${account_value:,.2f}", delta=f"${pnl_history:,.2f} (Open PnL)")
    
    with col2:
        st.metric(label="📈 Total Realized PnL", value=f"${total_pnl:,.2f}", delta_color="normal")
        
    with col3:
        st.metric(label="🎯 Win Rate", value=f"{win_rate:.1f}%", delta=f"{total_trades} Trades")
        
    with col4:
        st.metric(label="⚖️ Best / Worst", value=f"${best_trade:.1f} / ${worst_trade:.1f}")

    st.markdown("---")

    # Row 2: Charts & Positions
    c1, c2 = st.columns([2, 1])

    with c1:
        st.subheader("📊 PnL Growth Curve")
        if total_trades > 0:
            # Sort by time and calculate cumulative PnL
            closed_trades = closed_trades.sort_values(by='time')
            closed_trades['cumulative_pnl'] = closed_trades['closedPnl'].cumsum()
            
            fig = px.line(closed_trades, x='time', y='cumulative_pnl', title='Barry\'s Equity Curve', markers=True)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='white'))
            fig.update_traces(line_color='#00FFAA')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Waiting for first closed trade to generate chart...")

    with c2:
        st.subheader("🛡️ Active Positions")
        positions = user_state['assetPositions']
        active_positions = [p['position'] for p in positions if float(p['position']['szi']) != 0]
        
        if active_positions:
            for p in active_positions:
                symbol = p['coin']
                size = float(p['szi'])
                entry_price = float(p['entryPx'])
                pnl = float(p['unrealizedPnl'])
                side = "LONG 🟢" if size > 0 else "SHORT 🔴"
                
                st.markdown(f"""
                **{symbol}** | {side}
                * Entry: ${entry_price:,.2f}
                * Size: {size}
                * **PnL: ${pnl:,.2f}**
                ---
                """)
        else:
            st.write("Barry is currently looking for opportunities (No open positions).")

except Exception as e:
    st.error(f"Error connecting to Hyperliquid: {e}")

# Auto-refresh every 60 seconds
time.sleep(60)
st.rerun()
