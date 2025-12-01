import streamlit as st
import pandas as pd
import psycopg2
import os
import json
import plotly.express as px
from datetime import datetime, timedelta
from dotenv import load_dotenv
from PIL import Image

# --- CONFIGURAZIONE PORTAFOGLI VIRTUALI (Esempio) ---
TOTAL_DEPOSIT = 3039.67 # Esempio dal tuo screenshot
ALLOCATION_BRUCE = 2000.00
ALLOCATION_BARRY = 1000.00

# --- COLORI HAPPY HARBOR ---
HAPPY_GREEN_BG = "#48A986" # Verde acqua dello sfondo
HAPPY_GREEN_DARK = "#3A8C6E" # Verde più scuro per la sidebar
CARD_BG_WHITE = "#FFFFFF"
CARD_BG_YELLOW = "#FFF4C3"
CARD_BG_BLUE = "#C3E6F5"
TEXT_COLOR_DARK = "#2C3E50"
ACCENT_GREEN = "#2ECC71" # Per i profitti

THEME = {
    "Bruce": {"primary": "#F5C518", "bg": CARD_BG_YELLOW, "icon": "🦇"},
    "Barry": {"primary": "#3498DB", "bg": CARD_BG_BLUE, "icon": "⚡"},
    "Global": {"primary": HAPPY_GREEN_DARK, "bg": CARD_BG_WHITE, "icon": "🌐"}
}

st.set_page_config(page_title="Happy Harbor Dashboard", page_icon="⚓", layout="wide", initial_sidebar_state="expanded")

# --- CSS STYLES (REBRANDING HAPPY HARBOR) ---
st.markdown(f"""
    <style>
    /* Sfondo principale e testo */
    .stApp {{ background-color: {HAPPY_GREEN_BG}; color: {TEXT_COLOR_DARK}; }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {HAPPY_GREEN_DARK};
    }}
    section[data-testid="stSidebar"] .css-17lntkn, section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span {{
        color: white !important;
    }}

    /* Titoli */
    h1, h2, h3 {{ font-family: 'Comic Sans MS', 'Arial', sans-serif; color: white !important; text-align: center; }}
    .agent-title {{ font-size: 24px; font-weight: bold; margin-bottom: 10px; color: {TEXT_COLOR_DARK} !important; text-align: left !important;}}

    /* Card personalizzate */
    .metric-card {{
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 15px;
    }}
    .card-white {{ background-color: {CARD_BG_WHITE}; }}
    .card-yellow {{ background-color: {CARD_BG_YELLOW}; border: 2px solid #F7DC6F; }}
    .card-blue {{ background-color: {CARD_BG_BLUE}; border: 2px solid #AED6F1; }}

    /* Testo nelle card */
    .metric-label {{ font-size: 14px; color: #7F8C8D; }}
    .metric-value {{ font-size: 32px; font-weight: bold; color: {TEXT_COLOR_DARK}; }}
    .metric-profit {{ font-size: 16px; font-weight: bold; color: {ACCENT_GREEN}; background-color: #D5F5E3; padding: 5px 10px; border-radius: 10px; display: inline-block; margin-top: 5px;}}
    
    /* Icone e sub-metriche */
    .sub-metric-container {{ display: flex; align-items: center; margin-top: 15px; }}
    .sub-metric-icon {{ font-size: 24px; margin-right: 10px; background-color: rgba(255,255,255,0.5); padding: 10px; border-radius: 50%; }}
    .sub-metric-box {{ margin-right: 30px; }}
    .sub-metric-label {{ font-size: 12px; color: #7F8C8D; }}
    .sub-metric-value {{ font-size: 18px; font-weight: bold; color: {TEXT_COLOR_DARK}; }}

    </style>
    """, unsafe_allow_html=True)

load_dotenv()

# --- FUNZIONI DATI (Invariate) ---
@st.cache_data(ttl=10)
def load_data():
    # ... (Il codice per caricare i dati dal DB rimane lo stesso di prima)
    # Per brevità, qui userò dati mock-up per farti vedere il risultato visivo.
    # Tu mantieni la tua funzione load_data() originale che si connette al DB.
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- UI COMPONENTS ---
def render_main_kpi(title, value, pnl, pnl_pct):
    pnl_txt = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    pnl_pct_txt = f"(+{pnl_pct:.2f}%)" if pnl_pct >= 0 else f"({pnl_pct:.2f}%)"
    
    st.markdown(f"""
    <div class="metric-card card-white">
        <div style="display: flex; align-items: center;">
            <div style="background-color: #E8F6F3; padding: 15px; border-radius: 15px; margin-right: 20px; font-size: 30px;">👛</div>
            <div>
                <div class="metric-label">{title}</div>
                <div class="metric-value">${value:,.2f}</div>
                <div class="metric-profit">Profit {pnl_txt} {pnl_pct_txt}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_agent_card(agent_name, allocation, total_trades, virtual_portfolio):
    theme = THEME[agent_name]
    card_class = "card-yellow" if agent_name == "Bruce" else "card-blue"
    
    st.markdown(f"""
    <div class="metric-card {card_class}">
        <div class="agent-title">{agent_name} {theme['icon']}</div>
        <div style="display: flex; align-items: center; margin-bottom: 20px;">
            <div class="sub-metric-icon">{theme['icon']}</div>
            <div>
                <div class="metric-label">Virtual Portfolio</div>
                <div class="metric-value">${virtual_portfolio:,.2f}</div>
            </div>
        </div>
        <div style="display: flex;">
            <div class="sub-metric-box">
                <div style="display: flex; align-items: center;">
                    <div style="font-size: 20px; margin-right: 5px;">📊</div>
                    <div>
                        <div class="sub-metric-label">Allocation</div>
                        <div class="sub-metric-value">{allocation/TOTAL_DEPOSIT*100:.0f}%</div>
                    </div>
                </div>
            </div>
            <div class="sub-metric-box">
                 <div style="display: flex; align-items: center;">
                    <div style="font-size: 20px; margin-right: 5px;">🔁</div>
                    <div>
                        <div class="sub-metric-label">Total Trades</div>
                        <div class="sub-metric-value">{total_trades}</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- MAIN APP ---

# 1. CARICAMENTO LOGO CENTRALE
col_logo_1, col_logo_2, col_logo_3 = st.columns([1, 2, 1])
with col_logo_2:
    try:
        # Assicurati che happy_harbor_logo.png sia nella root della repo
        image = Image.open('happy_harbor_logo.png')
        st.image(image, use_column_width=True)
    except FileNotFoundError:
        st.warning("⚠️ Immagine 'happy_harbor_logo.png' non trovata. Caricala nella root della repository.")

st.title("HAPPY HARBOR DASHBOARD")

# Sidebar Navigazione
st.sidebar.title("HAPPY HARBOR")
page = st.sidebar.radio("Navigazione", ["Overview (Main) 🌐", "Agent Bruce 🦇", "Agent Barry ⚡"])

# --- PAGINA OVERVIEW ---
if page == "Overview (Main) 🌐":
    st.markdown("### 🏛️ CONTO REALE (Cross Margin)")
    # Dati Mock-up dall'immagine (Sostituisci con i tuoi dati reali dal DB)
    render_main_kpi("Totale Hyperliquid", 3039.67, 263.07, 0.77)
    
    st.markdown("### 🏆 Performance Agenti")
    colA, colB = st.columns(2)
    
    with colA:
        # Dati Mock-up Bruce
        render_agent_card("Bruce", ALLOCATION_BRUCE, 13, 2373.26)
        
    with colB:
        # Dati Mock-up Barry
        render_agent_card("Barry", ALLOCATION_BARRY, 137, 2623.20)

# --- PAGINE DI DETTAGLIO (Mantengono la struttura precedente ma col nuovo tema) ---
elif page == "Agent Bruce 🦇":
    st.markdown(f"<h2 class='agent-title'>Agent Bruce 🦇 Dettagli</h2>", unsafe_allow_html=True)
    # Qui puoi riutilizzare la funzione render_agent_detail() del codice precedente
    # adattandola con i nuovi colori se vuoi, o lasciandola com'era per ora.
    st.info("Pagina di dettaglio di Bruce (in costruzione col nuovo tema...)")

elif page == "Agent Barry ⚡":
    st.markdown(f"<h2 class='agent-title'>Agent Barry ⚡ Dettagli</h2>", unsafe_allow_html=True)
    st.info("Pagina di dettaglio di Barry (in costruzione col nuovo tema...)")
