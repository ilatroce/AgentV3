import streamlit as st
import pandas as pd
import psycopg2
import os
import json
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- CONFIGURAZIONE PORTAFOGLI VIRTUALI ---
# La somma deve fare il tuo deposito reale attuale circa
TOTAL_DEPOSIT = 26.97 
ALLOCATION_BRUCE = 20.00  # Capitale assegnato a Bruce
ALLOCATION_BARRY = 6.97   # Capitale assegnato a Barry

# --- COLORI ---
THEME = {
    "Bruce": {"primary": "#F5C518", "bg": "rgba(245, 197, 24, 0.1)", "icon": "🦇"},
    "Barry": {"primary": "#E81D22", "bg": "rgba(232, 29, 34, 0.1)", "icon": "⚡"},
    "Global": {"primary": "#FFFFFF", "bg": "#333333", "icon": "🌐"}
}

st.set_page_config(page_title="JUSTICE LEAGUE TRADING", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

# --- CSS STYLES ---
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: white; }
    .metric-card { background-color: #1f1f1f; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #333; }
    .agent-title { font-family: 'Arial Black'; font-size: 24px; margin-bottom: 0px; }
    </style>
    """, unsafe_allow_html=True)

load_dotenv()

# --- FUNZIONI DATI ---
@st.cache_data(ttl=10)
def load_data():
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        
        # 1. Carichiamo tutto
        df_bal = pd.read_sql("SELECT created_at, balance_usd FROM account_snapshots ORDER BY created_at ASC", conn)
        df_ops = pd.read_sql("SELECT * FROM bot_operations ORDER BY created_at DESC", conn)
        
        # 2. Posizioni Aperte
        last_snap = pd.read_sql("SELECT id FROM account_snapshots ORDER BY created_at DESC LIMIT 1", conn)
        df_pos = pd.DataFrame()
        if not last_snap.empty:
            sid = last_snap.iloc[0]['id']
            df_pos = pd.read_sql(f"SELECT * FROM open_positions WHERE snapshot_id = {sid}", conn)
            
        conn.close()

        # 3. NORMALIZZAZIONE AGENTI
        # Cerchiamo di capire chi ha fatto l'operazione. 
        # Se la colonna 'agent_name' non esiste o è null, guardiamo nel raw_payload.
        # Se non c'è nemmeno lì, assumiamo sia "Bruce" (legacy).
        
        def detect_agent(row):
            # Controllo 1: Colonna dedicata (se esiste nel tuo DB aggiornato)
            if 'agent_name' in row and row['agent_name']:
                return row['agent_name']
            
            # Controllo 2: Payload JSON
            try:
                payload = row['raw_payload']
                if isinstance(payload, str): payload = json.loads(payload)
                if isinstance(payload, dict):
                    return payload.get('agent', 'Bruce') # Default a Bruce
            except: pass
            
            return 'Bruce' # Fallback totale

        if not df_ops.empty:
            df_ops['agent_clean'] = df_ops.apply(detect_agent, axis=1)
        else:
            df_ops['agent_clean'] = []

        return df_bal, df_ops, df_pos

    except Exception as e:
        st.error(f"Errore DB: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- CALCOLO PNL VIRTUALE ---
def calculate_virtual_equity(agent_name, initial_allocation, df_ops):
    """
    Ricostruisce la curva del saldo basandosi sulla somma progressiva dei profitti
    delle operazioni chiuse di uno specifico agente.
    """
    if df_ops.empty: return pd.DataFrame()
    
    # Filtra operazioni dell'agente
    agent_ops = df_ops[df_ops['agent_clean'] == agent_name].copy()
    if agent_ops.empty: return pd.DataFrame()
    
    # Ordina per data crescente
    agent_ops = agent_ops.sort_values('created_at')
    
    # Estrai PnL dalle operazioni CLOSE (da raw_payload o calcolato)
    # Nota: Questo è approssimativo se non salviamo il PnL realizzato nella tabella operations.
    # Per ora simuliamo una equity curve basata sul numero di trade (semplificazione visiva)
    # o cerchiamo il pnl nel payload se presente.
    
    # MOCKUP PER LA DEMO: Assumiamo che ogni operazione abbia un risultato.
    # In produzione, dovresti salvare "realized_pnl" nella tabella bot_operations quando chiudi.
    # Qui usiamo un placeholder o cerchiamo di estrarlo.
    
    # Creiamo una lista cumulativa partendo dall'allocazione
    equity_data = []
    current_val = initial_allocation
    
    for _, row in agent_ops.iterrows():
        # Cerchiamo di estrarre il PnL reale se c'è, altrimenti 0
        pnl = 0.0
        try:
            raw = row['raw_payload']
            if isinstance(raw, str): raw = json.loads(raw)
            # Se Barry o Bruce salvano "pnl" o "profit" nel JSON quando chiudono
            if row['operation'] == 'CLOSE':
                pnl = float(raw.get('pnl', raw.get('realized_pnl', 0.0)))
        except: pass
        
        current_val += pnl
        equity_data.append({"time": row['created_at'], "equity": current_val})
        
    # Aggiungi il punto di partenza
    if equity_data:
        start_time = equity_data[0]['time'] - timedelta(hours=1)
        equity_data.insert(0, {"time": start_time, "equity": initial_allocation})
    else:
        equity_data.append({"time": datetime.now(), "equity": initial_allocation})
        
    return pd.DataFrame(equity_data)

# --- UI COMPONENTS ---
def render_kpi_card(title, value, pnl, pnl_pct, color):
    pnl_color = "#00FF00" if pnl >= 0 else "#FF4444"
    st.markdown(f"""
    <div class="metric-card" style="border-left: 5px solid {color};">
        <div style="color: #aaa; font-size: 12px;">{title}</div>
        <div style="font-size: 28px; font-weight: bold;">${value:,.2f}</div>
        <div style="color: {pnl_color}; font-size: 14px;">
            {pnl:+.2f} ({pnl_pct:+.2f}%)
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_agent_detail(agent_name, allocation, df_ops, df_pos):
    theme = THEME[agent_name]
    
    # Filtra dati
    my_ops = df_ops[df_ops['agent_clean'] == agent_name] if not df_ops.empty else pd.DataFrame()
    
    # Calcolo KPI
    realized_pnl = 0.0
    wins = 0
    total_trades = 0
    
    if not my_ops.empty:
        closes = my_ops[my_ops['operation'] == 'CLOSE']
        total_trades = len(closes)
        # Qui servirebbe il PnL reale salvato nel DB. Per ora è stimato.
        # realized_pnl = closes['pnl'].sum() 
    
    current_virtual_balance = allocation + realized_pnl
    pnl_pct = (realized_pnl / allocation * 100)
    
    # Header
    st.markdown(f"<h1 style='color:{theme['primary']}'>{theme['icon']} {agent_name.upper()} DASHBOARD</h1>", unsafe_allow_html=True)
    
    # KPI
    col1, col2, col3 = st.columns(3)
    with col1: render_kpi_card("Virtual Portfolio", current_virtual_balance, realized_pnl, pnl_pct, theme['primary'])
    with col2: render_kpi_card("Allocation", allocation, 0, 0, "#555")
    with col3: render_kpi_card("Total Trades", total_trades, 0, 0, "#555") # Placeholder
    
    # Grafico Dedicato
    st.subheader("Performance Curve")
    df_equity = calculate_virtual_equity(agent_name, allocation, df_ops)
    if not df_equity.empty:
        fig = px.area(df_equity, x='time', y='equity', template='plotly_dark')
        fig.update_traces(line_color=theme['primary'], fillcolor=theme['bg'])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Dati insufficienti per il grafico.")

    # Posizioni Aperte
    st.subheader("Attualmente a Mercato")
    # Filtriamo posizioni per agente (richiede che tu abbia salvato agent_name in open_positions o lo deduciamo dal symbol)
    # Per ora mostriamo tutte quelle compatibili col Ticker preferito dell'agente
    # Bruce usa BTC, ETH, SOL. Barry usa SOL. 
    # Miglioria futura: salvare 'agent' nella tabella open_positions.
    
    if not df_pos.empty:
        st.dataframe(df_pos) # Mostra grezzo per ora
    else:
        st.write("Nessuna posizione aperta.")
        
    # Ultimi Log
    st.subheader("Log Operativi")
    if not my_ops.empty:
        st.dataframe(my_ops[['created_at', 'symbol', 'operation', 'direction', 'target_portion_of_balance', 'raw_payload']].head(20))

# --- MAIN APP ---

df_bal, df_ops, df_pos = load_data()

# Sidebar Navigazione
st.sidebar.title("JUSTICE LEAGUE")
page = st.sidebar.radio("Seleziona Vista", ["Overview (Main)", "Agent Bruce 🦇", "Agent Barry ⚡"])

if page == "Overview (Main)":
    st.title("🌐 JUSTICE LEAGUE OVERVIEW")
    
    # 1. Totale Reale
    if not df_bal.empty:
        real_bal = df_bal.iloc[-1]['balance_usd']
        real_pnl = real_bal - TOTAL_DEPOSIT
        real_pct = (real_pnl / TOTAL_DEPOSIT * 100)
    else:
        real_bal = TOTAL_DEPOSIT
        real_pnl = 0
        real_pct = 0
        
    st.markdown("### 🏦 CONTO REALE (Cross Margin)")
    render_kpi_card("Totale Hyperliquid", real_bal, real_pnl, real_pct, "#FFFFFF")
    
    st.markdown("---")
    
    # 2. Confronto Agenti
    st.subheader("🏆 Performance Agenti")
    colA, colB = st.columns(2)
    
    with colA:
        # Mini Card Bruce
        # Calcolo PnL stimato (somma trade chiusi)
        # Nota: Questo richiede che log_bot_operation salvi il PnL quando chiude!
        # Se non lo fa ancora, questi valori saranno statici per ora.
        render_agent_detail("Bruce", ALLOCATION_BRUCE, df_ops, df_pos)
        
    with colB:
        # Mini Card Barry
        render_agent_detail("Barry", ALLOCATION_BARRY, df_ops, df_pos)

elif page == "Agent Bruce 🦇":
    render_agent_detail("Bruce", ALLOCATION_BRUCE, df_ops, df_pos)

elif page == "Agent Barry ⚡":
    render_agent_detail("Barry", ALLOCATION_BARRY, df_ops, df_pos)
