from indicators import analyze_multiple_tickers
from news_feed import fetch_latest_news
from trading_agent import previsione_trading_agent
from sentiment import get_sentiment
from forecaster import get_crypto_forecasts
from hyperliquid_trader import HyperLiquidTrader
import os
import json
import db_utils
import time  # <--- Importante per il loop
import traceback # <--- Importante per i log
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAZIONE ---
TESTNET = False   # True = soldi finti, False = soldi veri
TIMEFRAME_LOOP = 900 # Secondi di pausa tra un'operazione e l'altra (es. 1 ora)

# --- 1. SETUP INIZIALE DATABASE ---
print("[Main] Avvio del sistema...")
try:
    print("[Main] Inizializzazione Database in corso...")
    db_utils.init_db() # <--- QUESTA riga crea le tabelle su Postgres!
    print("[Main] Database pronto e tabelle verificate.")
except Exception as e:
    print(f"!!! ERRORE CRITICO DATABASE !!!: {e}")
    # Se il DB non va, è inutile partire.
    exit(1)

# --- SETUP CREDENZIALI ---
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

if not PRIVATE_KEY or not WALLET_ADDRESS:
    raise RuntimeError("PRIVATE_KEY o WALLET_ADDRESS mancanti nelle Variabili!")

# --- 2. LOOP INFINITO DEL BOT ---
while True:
    print(f"\n--- Inizio ciclo di trading: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    try:
        # Inizializza il trader
        bot = HyperLiquidTrader(
            secret_key=PRIVATE_KEY,
            account_address=WALLET_ADDRESS,
            testnet=TESTNET
        )

        # A. RACCOLTA DATI
        print("[1/5] Analisi Indicatori...")
        tickers = ['BTC', 'ETH', 'SOL']
        indicators_txt, indicators_json  = analyze_multiple_tickers(tickers)
        
        print("[2/5] Scarico News...")
        news_txt = fetch_latest_news()
        
        print("[3/5] Analisi Sentiment...")
        sentiment_txt, sentiment_json  = get_sentiment()
        
        print("[4/5] Analisi Forecast...")
        forecasts_txt, forecasts_json = get_crypto_forecasts()

        # Preparazione Prompt
        msg_info=f"""<indicatori>\n{indicators_txt}\n</indicatori>\n\n
        <news>\n{news_txt}</news>\n\n
        <sentiment>\n{sentiment_txt}\n</sentiment>\n\n
        <forecast>\n{forecasts_txt}\n</forecast>\n\n"""

        # B. LOG ACCOUNT & CHECK
        account_status = bot.get_account_status()
        portfolio_data = f"{json.dumps(account_status)}"
        
        # Salvataggio stato account nel DB
        snapshot_id = db_utils.log_account_status(account_status)
        print(f"[DB] Stato account salvato (ID snapshot: {snapshot_id})")

        # Lettura System Prompt
        with open('system_prompt.txt', 'r') as f:
            base_prompt = f.read()
        system_prompt = base_prompt.format(portfolio_data, msg_info)
            
        # C. INTELLIGENZA ARTIFICIALE
        print("[5/5] L'AI sta ragionando...")
        out = previsione_trading_agent(system_prompt)
        print(f"DECISIONE AI: {out}")
        
        # D. ESECUZIONE
        bot.execute_signal(out)

        # E. SALVATAGGIO OPERAZIONE
        op_id = db_utils.log_bot_operation(
            out, 
            system_prompt=system_prompt, 
            indicators=indicators_json, 
            news_text=news_txt, 
            sentiment=sentiment_json, 
            forecasts=forecasts_json
        )
        print(f"[DB] Operazione salvata con successo (ID: {op_id})")

    except Exception as e:
        # Se succede un errore, lo logghiamo nel DB ma NON fermiamo il loop
        err_msg = f"Errore nel ciclo: {e}"
        print(err_msg)
        traceback.print_exc()
        try:
            db_utils.log_error(e, context={"tickers": tickers}, source="main_loop")
            print("[DB] Errore salvato nella tabella 'errors'.")
        except:
            print("Impossibile salvare l'errore nel DB (forse DB giù?)")

    print(f"Ciclo finito. In pausa per {TIMEFRAME_LOOP} secondi...")
    time.sleep(TIMEFRAME_LOOP)