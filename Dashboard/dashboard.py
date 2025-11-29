import streamlit as st
import pandas as pd
import psycopg2
import os
import plotly.express as px
from dotenv import load_dotenv

# Configurazione Pagina
st.set_page_config(
    page_title="Cri, sono il più forte!!",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Carica variabili
load_dotenv()

# --- FUNZIONI DATABASE ---
def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def load_data():
    conn = get_connection()
    
    # 1. Scarica storico saldo
    query_balance = """
    SELECT created_at, balance_usd 
    FROM account_snapshots 
    ORDER BY created_at ASC
    """
    df_balance = pd.read_sql(query_balance, conn)
    
    # 2. Scarica ultime operazioni
    query_ops = """
    SELECT created_at, symbol, operation, direction, leverage, target_portion_of_balance
    FROM bot_operations
    ORDER BY created_at DESC
    LIMIT 100
    """
    df_ops = pd.read_sql(query_ops, conn)
    
    # 3. Scarica errori (per monitoraggio)
    query_errors = """
    SELECT created_at, error_type, error_message, source
    FROM errors
    ORDER BY created_at DESC
    LIMIT 20
    """
    df_errors = pd.read_sql(query_errors, conn)
    
    conn.close()
    return df_balance, df_ops, df_errors

# --- INTERFACCIA UTENTE ---

st.title("🤖 Il Trading bot di un vero Full Stack Deverope")

# Bottone Refresh
if st.button('🔄 Aggiorna Dati'):
    st.rerun()

try:
    df_balance, df_ops, df_errors = load_data()

    # --- KPI IN ALTO ---
    if not df_balance.empty:
        current_balance = df_balance.iloc[-1]['balance_usd']
        start_balance = df_balance.iloc[0]['balance_usd']
        pnl = current_balance - start_balance
        pnl_pct = (pnl / start_balance) * 100 if start_balance > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Saldo Attuale", f"${current_balance:,.2f}")
        col2.metric("📈 PnL Totale", f"${pnl:,.2f}", f"{pnl_pct:.2f}%")
        col3.metric("🔢 Operazioni Registrate", len(df_ops))

    # --- GRAFICO SALDO ---
    st.subheader("Andamento Portafoglio")
    if not df_balance.empty:
        fig = px.line(df_balance, x='created_at', y='balance_usd', title='Curva del Saldo (Equity Curve)')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun dato sul saldo ancora disponibile.")

    # --- TABELLE ---
    tab1, tab2 = st.tabs(["📝 Storico Operazioni", "⚠️ Log Errori"])

    with tab1:
        st.subheader("Ultime Operazioni Eseguite")
        if not df_ops.empty:
            st.dataframe(df_ops, use_container_width=True)
        else:
            st.write("Nessuna operazione trovata.")

    with tab2:
        st.subheader("Errori di Sistema")
        if not df_errors.empty:
            st.dataframe(df_errors, use_container_width=True)
        else:
            st.success("Nessun errore recente! Il sistema è sano.")

except Exception as e:
    st.error(f"Errore di connessione al Database: {e}")
    st.write("Assicurati che la variabile DATABASE_URL sia impostata correttamente.")