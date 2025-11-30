import streamlit as st
import pandas as pd
import psycopg2
import os
import json
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- CONFIGURAZIONE ---
MANUAL_DEPOSIT = 26.0  # <--- MODIFICA QUI IL TUO DEPOSITO INIZIALE
BATMAN_YELLOW = "#F5C518"
BATMAN_BLACK = "#0E1117"
BATMAN_GREY = "#1f1f1f"

st.set_page_config(
    page_title="AGENT BRUCE - Wayne Tech",
    page_icon="🦇",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS PERSONALIZZATO (BATMAN STYLE) ---
st.markdown(f"""
    <style>
    .stApp {{
        background-color: {BATMAN_BLACK};
        color: white;
    }}
    h1, h2, h3 {{
        color: {BATMAN_YELLOW} !important;
        font-family: 'Arial Black', sans-serif;
    }}
    .metric-card {{
        background-color: {BATMAN_GREY};
        border-left: 5px solid {BATMAN_YELLOW};
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 10px;
    }}
    .stDataFrame {{
        border: 1px solid #333;
    }}
    </style>
    """, unsafe_allow_html=True)

load_dotenv()

# --- FUNZIONI DATABASE ---
@st.cache_data(ttl=60) # Cache di 60 secondi per non sovraccaricare il DB
def load_data():
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        
        # 1. Storico Saldo (Account Snapshots)
        query_balance = "SELECT created_at, balance_usd, raw_payload FROM account_snapshots ORDER BY created_at ASC"
        df_balance = pd.read_sql(query_balance, conn)
        
        # 2. Operazioni (Bot Operations)
        query_ops = "SELECT * FROM bot_operations ORDER BY created_at DESC"
        df_ops = pd.read_sql(query_ops, conn)
        
        # 3. Posizioni Aperte (Dall'ultimo snapshot)
        # Recuperiamo l'ultimo ID snapshot
        query_last_snap = "SELECT id FROM account_snapshots ORDER BY created_at DESC LIMIT 1"
        last_snap_id = pd.read_sql(query_last_snap, conn)
        
        df_positions = pd.DataFrame()
        if not last_snap_id.empty:
            snap_id = last_snap_id.iloc[0]['id']
            query_pos = f"SELECT * FROM open_positions WHERE snapshot_id = {snap_id}"
            df_positions = pd.read_sql(query_pos, conn)

        conn.close()
        return df_balance, df_ops, df_positions
    except Exception as e:
        st.error(f"Errore connessione DB: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def calculate_pnl_change(df, hours_ago):
    if df.empty: return 0.0
    
    now = df.iloc[-1]['created_at']
    target_time = now - timedelta(hours=hours_ago)
    
    # Trova il record più vicino al target_time
    closest_row = df.iloc[(df['created_at'] - target_time).abs().argsort()[:1]]
    
    if closest_row.empty: return 0.0
    
    past_balance = closest_row.iloc[0]['balance_usd']
    current_balance = df.iloc[-1]['balance_usd']
    
    return current_balance - past_balance

# --- MAIN PAGE ---

st.title("🦇 AGENT BRUCE // DASHBOARD")
st.markdown("---")

df_balance, df_ops, df_positions = load_data()

if not df_balance.empty:
    # --- SEZIONE 1: KPI & PROFITTI ---
    current_equity = df_balance.iloc[-1]['balance_usd']
    total_pnl = current_equity - MANUAL_DEPOSIT
    pnl_color = "green" if total_pnl >= 0 else "red"

    # Prima riga: Saldo Gigante
    col_main_1, col_main_2 = st.columns([1, 3])
    with col_main_1:
        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size: 14px; color: #888;">WAYNE ENTERPRISE VALUE</div>
            <div style="font-size: 36px; font-weight: bold; color: {BATMAN_YELLOW};">${current_equity:,.2f}</div>
            <div style="font-size: 18px; color: {pnl_color};">PNL: ${total_pnl:+.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_main_2:
        # Metriche temporali
        cols = st.columns(6)
        timeframes = {
            "12H": 12, "24H": 24, "3GG": 72, 
            "7GG": 168, "14GG": 336, "30GG": 720
        }
        
        for i, (label, hours) in enumerate(timeframes.items()):
            delta = calculate_pnl_change(df_balance, hours)
            color = "#00FF00" if delta >= 0 else "#FF4444"
            with cols[i]:
                st.markdown(f"""
                <div style="text-align: center; background: #262730; padding: 10px; border-radius: 5px;">
                    <div style="color: #aaa; font-size: 12px;">{label}</div>
                    <div style="color: {color}; font-weight: bold;">${delta:+.2f}</div>
                </div>
                """, unsafe_allow_html=True)

    # --- SEZIONE 2: GRAFICO EQUITY ---
    st.subheader("📈 EQUITY CURVE")
    fig = px.area(df_balance, x='created_at', y='balance_usd', template='plotly_dark')
    fig.update_traces(line_color=BATMAN_YELLOW, fill_color='rgba(245, 197, 24, 0.1)')
    fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, use_container_width=True)

    # --- SEZIONE 3: POSIZIONI APERTE ---
    st.subheader("⚔️ POSIZIONI ATTIVE")
    if not df_positions.empty:
        cols_pos = st.columns(3)
        for idx, row in df_positions.iterrows():
            # Estrattore PnL sicuro
            pnl = row.get('pnl_usd', 0)
            symbol = row.get('symbol', 'UNKNOWN')
            side = row.get('side', 'N/A').upper()
            size = row.get('size', 0)
            leverage = row.get('leverage', 'N/A')
            
            # Recupera ragionamento se disponibile nel raw_payload
            raw_data = row.get('raw_payload')
            reasoning = "Analisi in corso..."
            if isinstance(raw_data, dict):
                 reasoning = raw_data.get('reason', reasoning)
            elif isinstance(raw_data, str):
                try:
                    js = json.loads(raw_data)
                    reasoning = js.get('reason', reasoning)
                except: pass

            card_color = "border-left: 5px solid #00FF00;" if pnl >= 0 else "border-left: 5px solid #FF4444;"
            
            with cols_pos[idx % 3]:
                st.markdown(f"""
                <div style="background-color: #1E1E1E; padding: 15px; border-radius: 5px; margin-bottom: 10px; {card_color}">
                    <h3 style="margin:0; color: white !important;">{symbol} <span style="font-size:12px; color:#888;">{side} x{leverage}</span></h3>
                    <div style="font-size: 24px; font-weight: bold; margin-top: 5px;">${pnl:+.2f}</div>
                    <hr style="border-color: #333;">
                    <div style="font-size: 12px; color: #ccc; font-style: italic;">"{reasoning}"</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("Nessuna posizione aperta al momento. Batman è in sorveglianza.")

    # --- SEZIONE 4: STORICO OPERAZIONI ---
    st.subheader(f"🗃️ LOG MISSIONI (Totale: {len(df_ops)})")
    
    if not df_ops.empty:
        # Tabella personalizzata
        for index, row in df_ops.head(100).iterrows():
            raw_payload = row['raw_payload']
            reason = "N/A"
            
            # Parsing JSON per trovare il motivo
            try:
                if isinstance(raw_payload, str):
                    data = json.loads(raw_payload)
                else:
                    data = raw_payload
                
                # Cerchiamo campi comuni di "pensiero"
                reason = data.get('reason') or data.get('thought') or data.get('rationale') or "Nessun ragionamento salvato"
            except:
                reason = "Errore lettura dati"

            # Colori per direzione
            direction = row['direction'].upper()
            dir_color = "green" if "LONG" in direction else "red"
            
            with st.expander(f"{row['created_at'].strftime('%d/%m %H:%M')} | {row['symbol']} | :{dir_color}[{direction}]"):
                st.markdown(f"**Leverage:** x{row['leverage']}")
                st.markdown(f"**Allocazione:** {float(row['target_portion_of_balance'])*100:.1f}% del portafoglio")
                st.markdown("### 🧠 Bruce's Reasoning:")
                st.info(reason)
                st.markdown("---")
                st.json(raw_payload) # Mostra i dati grezzi per debug
    else:
        st.write("Nessuna operazione registrata.")

else:
    st.warning("⚠️ Database vuoto o non raggiungibile. In attesa del primo segnale.")

# Footer
st.markdown("<br><br><div style='text-align: center; color: #555;'>Made with Wayne Tech Enterprise Systems</div>", unsafe_allow_html=True)