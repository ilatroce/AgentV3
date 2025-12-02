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

# Ignoriamo i warning di pandas
warnings.filterwarnings('ignore')

# --- CONFIGURAZIONE REALE ---
TOTAL_DEPOSIT = 70.00  # Aggiornato (25+25+20)
ALLOCATION_BRUCE = 25.00
ALLOCATION_BARRY = 25.00
ALLOCATION_WALLY = 20.00 # Nuova allocazione per Wally

# --- PALETTE COLORI HAPPY HARBOR ---
BG_COLOR = "#4B8056"      # Verde scuro (Sfondo principale)
SIDEBAR_COLOR = "#00695C" # Verde petrolio (Sidebar)
CARD_WHITE = "#FFFFFF"    # Sfondo Card
TEXT_DARK = "#263238"     # Testo scuro (dentro le card bianche)
TEXT_LIGHT = "#FFFFFF"    # Testo chiaro (sullo sfondo verde)
ACCENT_GREEN = "#00C853"  # Profit
ACCENT_RED = "#D50000"    # Loss

# Temi Agenti
THEME = {
    "Bruce": {"primary": "#FBC02D", "light": "#FFF9C4", "icon": "🦇"}, # Giallo
    "Barry": {"primary": "#29B6F6", "light": "#E1F5FE", "icon": "⚡"}, # Azzurro
    "Wally": {"primary": "#FF7043", "light": "#FFCCBC", "icon": "🧪"}, # Arancione (Nuovo!)
    "Global": {"primary": "#009688", "light": "#B2DFDB", "icon": "⚓"}
}

st.set_page_config(page_title="Happy Harbor", page_icon="⚓", layout="wide", initial_sidebar_state="expanded")

# --- CSS CUSTOM ---
st.markdown(f"""
    <style>
    /* Sfondo App */
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_LIGHT}; }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{ background-color: {SIDEBAR_COLOR}; }}
    section[data-testid="stSidebar"] * {{ color: white !important; }}
    
    /* Metriche Temporali (Box piccoli) */
    .time-card {{
        background-color: {CARD_WHITE};
        border-radius: 10px;
        padding: 10px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }}
    .time-card div {{ color: {TEXT_DARK} !important; }} /* Fix testo invisibile */
    
    /* Card Principali */
    .main-card {{
        background-color: {CARD_WHITE};
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        margin-bottom: 20px;
    }}
    .main-card div {{ color: {TEXT_DARK}; }} /* Fix testo invisibile */
    
    /* Badge Operazioni */
    .op-badge {{
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 12px;
        color: white !important;
    }}
    
    /* Titoli */
    h1, h2, h3 {{ color: {TEXT_LIGHT} !important; font-family: 'Segoe UI', sans-serif; text-shadow: 1px 1px 2px rgba(0,0,0,0.2); }}

    /* Fix per i testi dentro le card delle posizioni */
    .pos-card {{
        background-color: {CARD_WHITE};
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        color: {TEXT_DARK} !important; /* Importante! */
    }}
    .pos-card strong {{ color: {TEXT_DARK} !important; }}
    
    </style>
    """, unsafe_allow_html=True)

load_dotenv()

# --- 1. CARICAMENTO DATI ---
@st.cache_data(ttl=10)
def load_data():
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            
            # Snapshot Saldo
            df_bal = pd.read_sql("SELECT created_at, balance_usd FROM account_snapshots ORDER BY created_at ASC", conn)
            
            # Operazioni
            df_ops = pd.read_sql("SELECT * FROM bot_operations ORDER BY created_at DESC", conn)
            
            # Posizioni Aperte
            last_snap = pd.read_sql("SELECT id FROM account_snapshots ORDER BY created_at DESC LIMIT 1", conn)
            df_pos = pd.DataFrame()
            if not last_snap.empty:
                sid = last_snap.iloc[0]['id']
                df_pos = pd.read_sql(f"SELECT * FROM open_positions WHERE snapshot_id = {sid}", conn)
            
            # Riconoscimento Agenti
            def detect_agent(row):
                # 1. Cerca nella colonna
                if 'agent_name' in row and row['agent_name']: return row['agent_name']
                # 2. Cerca nel JSON
                try:
                    p = row['raw_payload']
                    if isinstance(p, str): p = json.loads(p)
                    if isinstance(p, dict) and 'agent' in p: return p['agent']
                except: pass

                # 3. Inferenza da Simbolo (Regole Justice League)
                sym = row.get('symbol', '')
                if sym == 'SUI': return 'Barry'
                if sym == 'AVAX': return 'Wally' # Wally prende AVAX
                if sym in ['BTC', 'ETH', 'SOL']: return 'Bruce'

                return 'Bruce' # Default

            if not df_ops.empty:
                df_ops['agent_clean'] = df_ops.apply(detect_agent, axis=1)
            else:
                df_ops['agent_clean'] = []

            return df_bal, df_ops, df_pos

    except Exception as e:
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
    """Calcola la curva del saldo virtuale"""
    if df_ops.empty: return pd.DataFrame()
    
    # Filtra solo le operazioni dell'agente specifico
    ops = df_ops[df_ops['agent_clean'] == agent_name].sort_values('created_at')
    
    points = []
    curr = initial
    
    # Punto zero
    if not ops.empty:
        start_date = ops.iloc[0]['created_at'] - timedelta(hours=1)
        points.append({"time": start_date, "equity": initial})
    else:
        # Se non ci sono operazioni, crea almeno una linea piatta
        points.append({"time": datetime.now() - timedelta(days=1), "equity": initial})
        points.append({"time": datetime.now(), "equity": initial})
        return pd.DataFrame(points)
    
    for _, row in ops.iterrows():
        pnl = 0.0
        # Cerchiamo il PnL solo sulle chiusure (Totali o Parziali)
        if 'CLOSE' in row['operation'].upper():
            try:
                raw = row['raw_payload']
                if isinstance(raw, str): raw = json.loads(raw)
                # Barry salva in 'pnl', Wally in 'pnl', Bruce potrebbe non averlo (FIXARE BRUCE)
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
                <strong style="color: #333;">{sym}</strong>
                <span class="op-badge" style="background-color: {bg}; margin-left: 10px;">{txt}</span>
            </summary>
            <div style="padding: 10px; font-size: 13px; color: #555; background: #fafafa; margin-top: 5px; border-radius: 5px;">
                <em>"{reason}"</em>
                <br>
                <span style="font-size: 11px; color: #999;">Lev: x{row.get('leverage', 'N/A')} | Alloc: {float(row.get('target_portion_of_balance',0))*100:.1f}%</span>
            </div>
        </details>
        """, unsafe_allow_html=True)

# --- MAIN APP LOGIC ---

df_bal, df_ops, df_pos = load_data()

# LOGO
col_L1, col_L2, col_L3 = st.columns([1, 2, 1])
with col_L2:
    try:
        if os.path.exists('happy_harbor_logo.png'):
            st.image('happy_harbor_logo.png', use_container_width=True)
        else:
            st.title("⚓ HAPPY HARBOR")
    except: st.title("⚓ HAPPY HARBOR")

# SIDEBAR NAVIGAZIONE
st.sidebar.title("Navigazione")
# Aggiunto Wally alla lista
page = st.sidebar.radio("Vai a:", ["Overview 🌐", "Bruce 🦇", "Barry ⚡", "Wally 🧪"])

# --- VIEW: OVERVIEW ---
if page == "Overview 🌐":
    
    # 1. Totale Reale
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
    
    # 2. Metriche Temporali
    st.subheader("⏱️ Andamento nel Tempo")
    cols = st.columns(6)
    times = {"12H": 12, "24H": 24, "3GG": 72, "7GG": 168, "14GG": 336, "30GG": 720}
    for i, (lab, h) in enumerate(times.items()):
        d_val, d_pct = calculate_pnl_change(df_bal, h)
        with cols[i]:
            render_metric_pill(lab, d_val, d_val, d_pct)
            
    # 3. Confronto Performance (%)
    st.subheader("🆚 Performance Bot a Confronto (%)")
    
    # Calcoliamo le curve per tutti e 3
    eq_bruce = get_virtual_equity("Bruce", ALLOCATION_BRUCE, df_ops)
    eq_barry = get_virtual_equity("Barry", ALLOCATION_BARRY, df_ops)
    eq_wally = get_virtual_equity("Wally", ALLOCATION_WALLY, df_ops)

    # Prepariamo i dati per il grafico multi-linea
    all_data = []
    
    if not eq_bruce.empty:
        eq_bruce['pct_change'] = (eq_bruce['equity'] - ALLOCATION_BRUCE) / ALLOCATION_BRUCE * 100
        eq_bruce['Agent'] = 'Bruce'
        all_data.append(eq_bruce)
        
    if not eq_barry.empty:
        eq_barry['pct_change'] = (eq_barry['equity'] - ALLOCATION_BARRY) / ALLOCATION_BARRY * 100
        eq_barry['Agent'] = 'Barry'
        all_data.append(eq_barry)
        
    if not eq_wally.empty:
        eq_wally['pct_change'] = (eq_wally['equity'] - ALLOCATION_WALLY) / ALLOCATION_WALLY * 100
        eq_wally['Agent'] = 'Wally'
        all_data.append(eq_wally)

    if all_data:
        df_compare = pd.concat(all_data)
        
        # Mappa colori
        color_map = {
            'Bruce': THEME['Bruce']['primary'], 
            'Barry': THEME['Barry']['primary'],
            'Wally': THEME['Wally']['primary']
        }

        fig_comp = px.line(df_compare, x='time', y='pct_change', color='Agent', color_discrete_map=color_map)
        fig_comp.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            height=300,
            margin=dict(l=0,r=0,t=20,b=0),
            legend=dict(font=dict(color=TEXT_LIGHT))
        )
        fig_comp.update_xaxes(color=TEXT_LIGHT, showgrid=False)
        fig_comp.update_yaxes(color=TEXT_LIGHT, title="Crescita %", showgrid=True, gridcolor="#555")
        st.plotly_chart(fig_comp, use_container_width=True)
    else:
        st.info("Dati insufficienti per il confronto.")

# --- VIEW: AGENTI (BRUCE / BARRY / WALLY) ---
else:
    # Determina quale agente
    if "Bruce" in page: agent = "Bruce"
    elif "Barry" in page: agent = "Barry"
    elif "Wally" in page: agent = "Wally"
    
    # Allocazione specifica
    if agent == "Bruce": alloc = ALLOCATION_BRUCE
    elif agent == "Barry": alloc = ALLOCATION_BARRY
    elif agent == "Wally": alloc = ALLOCATION_WALLY
    
    t = THEME[agent]
    
    st.markdown(f"<h2 style='color: {t['primary']} !important;'>{t['icon']} Agente {agent}</h2>", unsafe_allow_html=True)
    
    # Calcoli Portfolio Virtuale
    df_equity = get_virtual_equity(agent, alloc, df_ops)
    curr_virt_base = df_equity.iloc[-1]['equity'] if not df_equity.empty else alloc

    # Unrealized PnL (Dalle posizioni aperte ora)
    relevant_syms = []
    if agent == 'Bruce': relevant_syms = ['BTC', 'ETH', 'SOL']
    elif agent == 'Barry': relevant_syms = ['SUI']
    elif agent == 'Wally': relevant_syms = ['AVAX'] # Wally su AVAX
    
    unrealized_pnl = 0.0
    if not df_pos.empty:
        agent_pos = df_pos[df_pos['symbol'].isin(relevant_syms)]
        if not agent_pos.empty:
            unrealized_pnl = agent_pos['pnl_usd'].sum()

    curr_virt = curr_virt_base + unrealized_pnl
    virt_pnl = curr_virt - alloc
    virt_pct = (virt_pnl / alloc * 100) if alloc > 0 else 0
    
    # KPI CARD
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"""
        <div class="main-card" style="background-color: {t['light']}; border: 1px solid {t['primary']};">
            <div style="color: #555;">Portafoglio Virtuale</div>
            <div style="font-size: 32px; font-weight: bold; color: {TEXT_DARK};">${curr_virt:,.2f}</div>
            <div style="color: {ACCENT_GREEN if virt_pnl>=0 else ACCENT_RED}; font-weight: bold;">
                {virt_pnl:+.2f} ({virt_pct:+.2f}%)
            </div>
            <div style="font-size: 11px; color: #777; margin-top:5px;">
                (Unrealized: ${unrealized_pnl:+.2f})
            </div>
            <hr style="border-color: #ddd;">
            <div style="font-size: 12px; color: #555;">Allocazione: ${alloc:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        if not df_equity.empty:
            fig = px.line(df_equity, x='time', y='equity', title="Performance Virtuale (Realized)")
            fig.update_traces(line_color=t['primary'], line_width=3)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, margin=dict(l=0,r=0,t=30,b=0))
            fig.update_xaxes(color=TEXT_LIGHT)
            fig.update_yaxes(color=TEXT_LIGHT)
            st.plotly_chart(fig, use_container_width=True)

    # POSIZIONI ATTIVE (Card Fixata)
    st.subheader(f"⚔️ Posizioni Attive ({agent})")
    
    my_pos = df_pos[df_pos['symbol'].isin(relevant_syms)] if not df_pos.empty else pd.DataFrame()
    
    if not my_pos.empty:
        cols_p = st.columns(3)
        for idx, row in my_pos.iterrows():
            pnl = row['pnl_usd']
            color = "#4CAF50" if pnl >= 0 else "#F44336"
            with cols_p[idx % 3]:
                # CSS Inline per forzare il colore del testo
                st.markdown(f"""
                <div class="pos-card" style="border-left: 5px solid {color};">
                    <div style="font-size: 18px; font-weight: bold; color: #333;">{row['symbol']}</div>
                    <div style="font-size: 12px; color: #666;">{row['side']} x{row['leverage']}</div>
                    <div style="font-size: 24px; font-weight: bold; color: {color}; margin-top: 5px;">
                        ${pnl:+.2f}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info(f"{agent} è Flat (nessuna posizione).")

    # STORICO
    st.subheader("📜 Storico Operazioni")
    my_ops = df_ops[df_ops['agent_clean'] == agent] if 'agent_clean' in df_ops.columns else pd.DataFrame()
    render_history_list(my_ops)

st.markdown("<br><div style='text-align: center; color: #ccc; font-size: 12px;'>Happy Harbor Hosting Services © 2024</div>", unsafe_allow_html=True)
