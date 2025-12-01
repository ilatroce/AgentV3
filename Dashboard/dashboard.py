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
                <span style="color: #888; font-size: 12px; margin-right: 10px;">{date}</span>
                <strong>{sym}</strong>
                <span class="op-badge" style="background-color: {bg}; margin-left: 10px;">{txt}</span>
            </summary>
            <div style="padding: 10px; font-size: 13px; color: #555; background: #fafafa; margin-top: 5px; border-radius: 5px;">
                <em>"{reason}"</em>
                <br>
                <span style="font-size: 11px; color: #999;">Lev: x{row.get('leverage', 'N/A')} | Alloc: {float(row.get('target_portion_of_balance',0))*100:.1f}%</span>
            </div>
        </details>
        """, unsafe_allow_html=True)

# --- MAIN LOGIC ---

df_bal, df_ops, df_pos = load_data()

# LOGO HEADER
col_L1, col_L2, col_L3 = st.columns([1, 2, 1])
with col_L2:
    try:
        if os.path.exists('happy_harbor_logo.png'):
            st.image('happy_harbor_logo.png', use_container_width=True) # Aggiornato per evitare warning
        else:
            st.title("⚓ HAPPY HARBOR")
    except: st.title("⚓ HAPPY HARBOR")

# SIDEBAR
st.sidebar.title("Navigazione")
page = st.sidebar.radio("Vai a:", ["Overview 🌐", "Bruce 🦇", "Barry ⚡"])

# --- PAGINA OVERVIEW ---
if page == "Overview 🌐":
    
    # 1. KPI PRINCIPALE (SALDO REALE)
    curr_bal = df_bal.iloc[-1]['balance_usd'] if not df_bal.empty else TOTAL_DEPOSIT
    total_pnl = curr_bal - TOTAL_DEPOSIT
    total_pct = (total_pnl / TOTAL_DEPOSIT * 100)
    
    st.markdown(f"""
    <div class="main-card" style="border-top: 5px solid {THEME['Global']['primary']};">
        <div style="font-size: 14px; color: #666;">TOTALE CONTO (Cross Margin)</div>
        <div style="font-size: 42px; font-weight: bold; color: {TEXT_DARK};">${curr_bal:,.2f}</div>
        <div style="font-size: 18px; color: {ACCENT_GREEN if total_pnl>=0 else ACCENT_RED}; font-weight: bold;">
            {total_pnl:+.2f} ({total_pct:+.2f}%)
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 2. METRICHE TEMPORALI
    st.subheader("⏱️ Andamento nel Tempo")
    cols = st.columns(6)
    times = {"12H": 12, "24H": 24, "3GG": 72, "7GG": 168, "14GG": 336, "30GG": 720}
    for i, (lab, h) in enumerate(times.items()):
        d_val, d_pct = calculate_pnl_change(df_bal, h)
        with cols[i]:
            render_metric_pill(lab, d_val, d_val, d_pct)
            
    # 3. GRAFICO GLOBALE
    st.subheader("📈 Curva Equity Totale")
    if not df_bal.empty:
        fig = px.area(df_bal, x='created_at', y='balance_usd')
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=300, margin=dict(l=0,r=0,t=0,b=0))
        fig.update_traces(line_color=THEME['Global']['primary'], fillcolor=THEME['Global']['light'])
        st.plotly_chart(fig, use_container_width=True) # Aggiornato per evitare warning

# --- PAGINE AGENTI (BRUCE / BARRY) ---
else:
    agent = "Bruce" if "Bruce" in page else "Barry"
    alloc = ALLOCATION_BRUCE if agent == "Bruce" else ALLOCATION_BARRY
    t = THEME[agent]
    
    # Titolo
    st.markdown(f"<h2 style='color: {t['primary']} !important;'>{t['icon']} Agente {agent}</h2>", unsafe_allow_html=True)
    
    # Dati Agente
    df_equity = get_virtual_equity(agent, alloc, df_ops)
    curr_virt = df_equity.iloc[-1]['equity'] if not df_equity.empty else alloc
    virt_pnl = curr_virt - alloc
    virt_pct = (virt_pnl / alloc * 100)
    
    # KPI Agente
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"""
        <div class="main-card" style="background-color: {t['light']}; border: 1px solid {t['primary']};">
            <div style="color: #555;">Portafoglio Virtuale</div>
            <div style="font-size: 32px; font-weight: bold;">${curr_virt:,.2f}</div>
            <div style="color: {ACCENT_GREEN if virt_pnl>=0 else ACCENT_RED}; font-weight: bold;">
                {virt_pnl:+.2f} ({virt_pct:+.2f}%)
            </div>
            <hr>
            <div style="font-size: 12px;">Allocazione Iniziale: ${alloc:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        if not df_equity.empty:
            fig = px.line(df_equity, x='time', y='equity', title="Performance Virtuale")
            fig.update_traces(line_color=t['primary'], line_width=3)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True) # Aggiornato

    # Posizioni Attive
    st.subheader(f"⚔️ Posizioni Attive ({agent})")
    relevant_syms = ['BTC', 'ETH', 'SOL'] if agent == 'Bruce' else ['SOL']
    
    my_pos = df_pos[df_pos['symbol'].isin(relevant_syms)] if not df_pos.empty else pd.DataFrame()
    
    if not my_pos.empty:
        cols_p = st.columns(3)
        for idx, row in my_pos.iterrows():
            pnl = row['pnl_usd']
            color = "#4CAF50" if pnl >= 0 else "#F44336"
            with cols_p[idx % 3]:
                st.markdown(f"""
                <div style="background: white; border-left: 5px solid {color}; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                    <strong>{row['symbol']}</strong> {row['side']} x{row['leverage']}
                    <div style="font-size: 20px; font-weight: bold; color: {color};">${pnl:+.2f}</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info(f"{agent} non ha posizioni aperte al momento.")

    # Storico
    st.subheader("📜 Storico Operazioni")
    # Filtriamo per agente
    my_ops = df_ops[df_ops['agent_clean'] == agent] if 'agent_clean' in df_ops.columns else pd.DataFrame()
    render_history_list(my_ops)

st.markdown("<br><div style='text-align: center; color: #aaa; font-size: 12px;'>Happy Harbor Hosting Services © 2024</div>", unsafe_allow_html=True)
