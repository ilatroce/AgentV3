import sys
import os
import time
import pandas as pd
import traceback
from dotenv import load_dotenv

# Importa i moduli dalla cartella superiore
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE BARRY ---
AGENT_NAME = "Barry"
TICKER = "SOL"         # Barry corre su Solana (veloce ed economica)
TIMEFRAME = "15m"      # Timeframe per le Bollinger
LOOP_SPEED = 60        # Controlla ogni 60 secondi
ALLOCATION_PCT = 0.05  # Usa il 5% del saldo per trade
BB_LENGTH = 20         # Lunghezza Bollinger
BB_STD = 2.0           # Deviazione Standard

def calculate_bollinger(df):
    if df.empty: return None
    df['sma'] = df['close'].rolling(window=BB_LENGTH).mean()
    df['std'] = df['close'].rolling(window=BB_LENGTH).std()
    df['upper'] = df['sma'] + (df['std'] * BB_STD)
    df['lower'] = df['sma'] - (df['std'] * BB_STD)
    return df.iloc[-1]

def run_barry():
    print(f"⚡ [Barry] Inizializzazione Speed Force su {TICKER}...")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    
    # IMPORTANTE: Metti False per soldi veri, True per test
    bot = HyperLiquidTrader(private_key, wallet, testnet=False) 

    while True:
        try:
            print(f"\n⚡ [Barry] Analisi {time.strftime('%H:%M:%S')}...")
            
            # 1. Scarica Dati Storici
            df_candles = bot.get_candles(TICKER, interval=TIMEFRAME, limit=50)
            last_candle = calculate_bollinger(df_candles)
            
            if last_candle is None:
                print("⚠️ Dati insufficienti per calcolare Bollinger.")
                time.sleep(10)
                continue

            current_price = last_candle['close']
            upper_band = last_candle['upper']
            lower_band = last_candle['lower']
            mid_band = last_candle['sma']
            
            print(f"   Prezzo: {current_price:.4f} | Bande: {lower_band:.4f} - {upper_band:.4f}")

            # 2. Controllo Posizioni
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            action = None
            direction = None
            reason = ""

            # --- STRATEGIA ---
            
            # A) NESSUNA POSIZIONE -> CERCA INGRESSO
            if not my_pos:
                if current_price <= lower_band:
                    action = "OPEN"
                    direction = "LONG"
                    reason = f"Sniper Entry: Prezzo ({current_price}) ha toccato la Banda Inferiore ({lower_band:.2f})"
                elif current_price >= upper_band:
                    action = "OPEN"
                    direction = "SHORT"
                    reason = f"Sniper Entry: Prezzo ({current_price}) ha toccato la Banda Superiore ({upper_band:.2f})"
                else:
                    print("   Nessun segnale. Aspetto ai bordi del range.")

            # B) POSIZIONE APERTA -> GESTISCI USCITA (Mean Reversion)
            else:
                side = my_pos['side'].upper() # LONG o SHORT
                entry = float(my_pos['entry_price'])
                pnl = float(my_pos['pnl_usd'])
                print(f"   Posizione attiva: {side} (PnL: ${pnl:.2f})")
                
                # Chiudi se tocca la media centrale (TP Dinamico)
                close_signal = False
                
                if side == "LONG" and current_price >= mid_band:
                    reason = "Take Profit: Ritorno alla media (Mid Band) completato."
                    close_signal = True
                elif side == "SHORT" and current_price <= mid_band:
                    reason = "Take Profit: Ritorno alla media (Mid Band) completato."
                    close_signal = True
                
                # Stop Loss di emergenza (-20% ROI o simili, gestiscilo come vuoi)
                # if pnl < -2.0: close_signal = True...

                if close_signal:
                    action = "CLOSE"
                    direction = "FLAT"

            # --- ESECUZIONE ---
            if action == "OPEN":
                # Calcolo size
                balance = float(account.get('balance_usd', 0))
                size_usd = balance * ALLOCATION_PCT
                # Esegui ordine (qui dovresti avere il metodo execute_order nel trader)
                # Per ora simuliamo il segnale per il DB
                
                # bot.open_position(TICKER, direction, size_usd) <--- Sostituisci con tua chiamata reale
                print(f"⚡ ESEGUO: {action} {direction} su {TICKER}")
                
                # Log Database
                payload = {
                    "operation": "OPEN", 
                    "symbol": TICKER, 
                    "direction": direction, 
                    "reason": reason,
                    "target_portion_of_balance": ALLOCATION_PCT
                }
                # IMPORTANTE: Passiamo agent_name="Barry" (richiede aggiornamento db_utils o lo passiamo nel raw)
                # Se non hai aggiornato db_utils, lo mettiamo nel payload JSON per vederlo nella dashboard
                payload["agent"] = AGENT_NAME 
                
                # db_utils.log_bot_operation(payload) # <--- Scommenta quando esegui davvero

            elif action == "CLOSE":
                # bot.close_position(TICKER)
                print(f"⚡ ESEGUO: CHIUSURA POSIZIONE su {TICKER}")
                payload = {"operation": "CLOSE", "symbol": TICKER, "reason": reason, "agent": AGENT_NAME}
                # db_utils.log_bot_operation(payload)

        except Exception as e:
            print(f"⚡ Errore critico Barry: {e}")
            traceback.print_exc()
            time.sleep(10)
        
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
