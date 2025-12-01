import streamlit as st
import pandas as pd
import psycopg2
import os
import json
import plotly.express as px
from datetime import datetime, timedelta
from dotenv import load_dotenv
from PIL import Image
import warnings

# Ignoriamo i warning di pandas per la connessione DB (non sono errori critici)
warnings.filterwarnings('ignore')

# --- CONFIGURAZIONE REALE ---
TOTAL_DEPOSIT = 26.97  # Il tuo deposito iniziale reale
ALLOCATION_BRUCE = 20.00
ALLOCATION_BARRY = 6.97

# --- PALETTE COLORI HAPPY HARBOR ---
BG_COLOR = "#E0F2F1"      # Verde acqua chiarissimo
SIDEBAR_COLOR = "#00695C" # Verde petrolio
CARD_WHITE = "#FFFFFF"
TEXT_DARK = "#263238"
ACCENT_GREEN = "#00C853"  # Profit
ACCENT_RED = "#D50000"    # Loss

# Temi Agenti
THEME = {
    "Bruce": {"primary": "#FBC02D", "light": "#FFF9C4", "icon": "🦇"}, # Giallo Bat
    "Barry": {"primary": "#29B6F6", "light": "#E1F5FE", "icon": "⚡"}, # Azzurro Flash
    "Global": {"primary": "#009688", "light": "#B2DFDB", "icon": "⚓"}
}

st.set_page_config(page_title="Happy Harbor", page_icon="⚓", layout="wide", initial_sidebar_state="expanded")

# --- CSS CUSTOM ---
st.markdown(f"""
    <style>
    /* Sfondo App */
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_DARK}; }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{ background-color: {SIDEBAR_COLOR}; }}
    section[data-testid="stSidebar"] * {{ color: white !important; }}
    
    /* Metriche Temporali (Box piccoli) */
    .time-card {{
        background-color: {CARD_WHITE};
        border-radius: 10px;
        padding: 10px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }}
    
    /* Card Principali */
    .main-card {{
        background-color: {CARD_WHITE};
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }}
    
    /* Badge Operazioni */
    .op-badge {{
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 12px;
        color: white;
    }}
    
    h1, h2, h3 {{ color: {TEXT_DARK} !important; font-family: 'Segoe UI', sans-serif; }}
    </style>
    """, unsafe_allow_html=True)

load_dotenv()

# --- 1. CARICAMENTO DATI (DB REALE) ---
@st.cache_data(ttl=10)
def load_data():
    try:
        # Usa connect con context manager per sicurezza
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            
            # Snapshot Saldo
            df_bal = pd.read_sql("SELECT created_at, balance_usd FROM account_snapshots ORDER BY created_at ASC", conn)
            
            # Operazioni
            df_ops = pd.read_sql("SELECT * FROM bot_operations ORDER BY created_at DESC", conn)
            
            # Posizioni Aperte (Ultimo snapshot)
            last_snap = pd.read_sql("SELECT id FROM account_snapshots ORDER BY created_at DESC LIMIT 1", conn)
            df_pos = pd.DataFrame()
            if not last_snap.empty:
                sid = last_snap.iloc[0]['id']
                df_pos = pd.read_sql(f"SELECT * FROM open_positions WHERE snapshot_id = {sid}", conn)
            
            # Logica assegnazione Agente
            def detect_agent(row):
                # 1. Cerca nella colonna se esiste
                if 'agent_name' in row and row['agent_name']: return row['agent_name']
                # 2. Cerca nel JSON
                try:
                    p = row['raw_payload']
                    if isinstance(p, str): p = json.loads(p)
                    if isinstance(p, dict): return p.get('agent', 'Bruce')
                except: pass
                return 'Bruce' # Default

            if not df_ops.empty:
                df_ops['agent_clean'] = df_ops.apply(detect_agent, axis=1)
            else:
                df_ops['agent_clean'] = []

            return df_bal, df_ops, df_pos

    except Exception as e:
        # Non mostriamo l'errore a schermo intero per non rompere la UI, ma logghiamo
        print(f"Errore caricamento dati: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- FUNZIONI CALCOLO ---
def calculate_pnl_change(df, hours_ago):
    if df.empty: return 0.0, 0.0
    now = df.iloc[-1]['created_at']
    target = now - timedelta(hours=hours_ago)
    row = df.iloc[(df['created_at'] - target).abs().argsort()[:1]]
    if row.empty: return 0.0, 0.0
    
    past = row.iloc[0]['balance_usd']
    curr = df.iloc[-1]['balance_usd']
    delta = curr - past
    pct = (delta / past * 100) if past > 0 else 0
    return delta, pct

def get_virtual_equity(agent_name, initial, df_ops):
    """Calcola la curva del saldo virtuale per agente"""
    if df_ops.empty: return pd.DataFrame()
    ops = df_ops[df_ops['agent_clean'] == agent_name].sort_values('created_at')
    
    points = []
    curr = initial
    
    # Punto zero
    if not ops.empty:
        start_date = ops.iloc[0]['created_at'] - timedelta(hours=1)
        points.append({"time": start_date, "equity": initial})
    
    for _, row in ops.iterrows():
        pnl = 0.0
        if row['operation'] == 'CLOSE':
            try:
                raw = row['raw_payload']
                if isinstance(raw, str): raw = json.loads(raw)
                # Cerca vari modi in cui potremmo aver salvato il pnl
                pnl = float(raw.get('pnl', raw.get('realized_pnl', 0.0)))
            except: pass
        curr += pnl
        points.append({"time": row['created_at'], "equity": curr})
        
    return pd.DataFrame(points)

# --- UI COMPONENTS ---
def render_metric_pill(label, val, delta, delta_pct):
    color = ACCENT_GREEN if delta >= 0 else ACCENT_RED
    st.markdown(f"""
    <div class="time-card">
        <div style="font-size: 11px; color: #888;">{label}</div>
        <div style="font-size: 14px; font-weight: bold; color: {TEXT_DARK};">${val:,.2f}</div>
        <div style="font-size: 11px; color: {color}; font-weight: bold;">
            {delta:+.2f} ({delta_pct:+.1f}%)
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_history_list(df_ops_agent):
    if df_ops_agent.empty:
        st.info("Nessuna operazione registrata.")
        return

    for _, row in df_ops_agent.head(50).iterrows():
        sym = row.get('symbol', 'UNKNOWN')
        op = row.get('operation', 'N/A').upper()
        
        # FIX CRITICO: Gestione sicura di direction se è NULL nel DB
        direction_val = row.get('direction')
        direction = direction_val.upper() if direction_val else ''
        
        date = row['created_at'].strftime('%d/%m %H:%M')
        
        # Badge Stile
        if "OPEN" in op:
            bg = "#4CAF50" # Green
            txt = f"OPEN {direction}"
        elif "CLOSE" in op:
            bg = "#FF9800" # Orange
            txt = "CLOSE"
        else:
            bg = "#9E9E9E"
            txt = op

        # Estrazione Reason
        reason = "N/A"
        try:
            raw = row['raw_payload']
            if isinstance(raw, str): raw = json.loads(raw)
            reason = raw.get('reason', 'Nessun dettaglio')
        except: pass

        st.markdown(f"""
        <details style="background: white; border: 1px solid #eee; border-radius: 8px; padding: 10px; margin-bottom: 8px;">
            <summary style="cursor: pointer; font-weight: 500; color: #333;">
                <span style="color
