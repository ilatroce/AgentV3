import sys
import os
import time
import pandas as pd
import traceback
from dotenv import load_dotenv

# Importa i moduli dalla cartella superiore (Salotto)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE BARRY (THE FLASH) ---
AGENT_NAME = "Barry"
TICKER = "SOL"         # Barry preferisce coin veloci
TIMEFRAME = "15m"      # Timeframe per le Bollinger
LOOP_SPEED = 60        # Barry controlla i mercati ogni 60 secondi
ALLOCATION_PCT = 0.05  # Barry è prudente: usa solo il 5% del saldo per trade
BB_LENGTH = 20         # Lunghezza standard Bollinger
BB_STD = 2.0           # Deviazione standard

def calculate_bollinger(df):
    """Calcola le bande di Bollinger sull'ultimo dato disponibile"""
    if df.empty: return None
    df['sma'] = df['close'].rolling(window=BB_LENGTH).mean()
    df['std'] = df['close'].rolling(window=BB_LENGTH).std()
    df['upper'] = df['sma'] + (df['std'] * BB_STD)
    df['lower'] = df['sma'] - (df['std'] * BB_STD)
    return df.iloc[-1]

def run_barry():
    print(f"⚡ [Barry] Speed Force attivata su {TICKER}...")
    print(f"⚡ [Barry] Allocazione per trade: {ALLOCATION_PCT*100}% del saldo.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    
    # IMPORTANTE: testnet=False usa soldi veri!
    bot = HyperLiquidTrader(private_key, wallet, testnet=False) 

    while True:
        try:
            print(f"\n⚡ [Barry] Scansiono il mercato ({time.strftime('%H:%M:%S')})...")
            
            # 1. SCARICA STORICO (Necessario per Bollinger)
            # Assicurati di aver aggiornato hyperliquid_trader.py con get_candles!
            df_candles = bot.get_candles(TICKER, interval=TIMEFRAME, limit=50)
            last_candle = calculate_bollinger(df_candles)
            
            if last_candle is None:
                print("⚠️ Dati insufficienti per calcolare indicatori. Aspetto...")
                time.sleep(10)
                continue

            current_price = last_candle['close']
            upper_band = last_candle['upper']
            lower_band = last_candle['lower']
            mid_band = last_candle['sma']
            
            print(f"   Prezzo Attuale: {current_price:.4f}")
            print(f"   Range Bollinger: {lower_band:.4f} (Low) <---> {upper_band:.4f} (High)")

            # 2. CONTROLLO POSIZIONI
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            # Cerca se Barry ha già una posizione aperta su questo Ticker
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            action = None
            direction = None
            reason = ""
            realized_pnl = 0.0 # Fondamentale per la Dashboard

            # --- STRATEGIA ---
            
            # CASO A: NESSUNA POSIZIONE -> Cerca un ingresso "Sniper"
            if not my_pos:
                if current_price <= lower_band:
                    action = "OPEN"
                    direction = "LONG"
                    reason = f"Grid Entry: Prezzo ha toccato la Banda Inferiore ({lower_band:.2f})"
                elif current_price >= upper_band:
                    action = "OPEN"
                    direction = "SHORT"
                    reason = f"Grid Entry: Prezzo ha toccato la Banda Superiore ({upper_band:.2f})"
                else:
                    print("   Nessun segnale di ingresso. Barry resta in attesa.")

            # CASO B: POSIZIONE APERTA -> Gestisci l'uscita (Mean Reversion)
            else:
                side = my_pos['side'].upper() # LONG o SHORT
                entry = float(my_pos['entry_price'])
                pnl = float(my_pos['pnl_usd'])
                print(f"   Posizione Attiva: {side} | Entry: {entry} | PnL: ${pnl:.2f}")
                
                # Logica di Uscita: TP Dinamico alla Media Centrale
                should_close = False
                
                if side == "LONG" and current_price >= mid_band:
                    reason = f"Take Profit: Ritorno alla media ({mid_band:.2f}) completato."
                    should_close = True
                elif side == "SHORT" and current_price <= mid_band:
                    reason = f"Take Profit: Ritorno alla media ({mid_band:.2f}) completato."
                    should_close = True
                
                # Stop Loss di emergenza (Opzionale, es. se perdi più di 2$)
                # if pnl < -2.0: 
                #     reason = "Stop Loss: Emergenza attivata."
                #     should_close = True

                if should_close:
                    action = "CLOSE"
                    direction = "FLAT"
                    realized_pnl = pnl # Catturiamo il profitto per la Dashboard!

            # --- ESECUZIONE ORDINI ---
            if action == "OPEN":
                # 1. Calcola Size
                balance = float(account.get('balance_usd', 0))
                size_usd = balance * ALLOCATION_PCT
                
                print(f"⚡ ESEGUO OPEN {direction}: Investo ${size_usd:.2f}")
                
                # 2. Esegui Ordine Reale (Scommenta quando pronto)
                # bot.execute_order(TICKER, direction, size_usd) 
                
                # 3. Log Database
                payload = {
                    "operation": "OPEN", 
                    "symbol": TICKER, 
                    "direction": direction, 
                    "reason": reason,
                    "target_portion_of_balance": ALLOCATION_PCT,
                    "agent": AGENT_NAME 
                }
                db_utils.log_bot_operation(payload)
                print("   [DB] Operazione OPEN salvata.")

            elif action == "CLOSE":
                print(f"⚡ ESEGUO CLOSE: Incasso ${realized_pnl:.2f}")
                
                # 1. Chiudi Ordine Reale (Scommenta quando pronto)
                # bot.close_position(TICKER)
                
                # 2. Log Database (CON PNL!)
                payload = {
                    "operation": "CLOSE", 
                    "symbol": TICKER, 
                    "reason": reason, 
                    "agent": AGENT_NAME,
                    "pnl": realized_pnl,          # <--- Per la dashboard
                    "realized_pnl": realized_pnl  # <--- Ridondanza per sicurezza
                }
                db_utils.log_bot_operation(payload)
                print("   [DB] Operazione CLOSE salvata con profitto.")

        except Exception as e:
            print(f"⚡ Errore nel ciclo di Barry: {e}")
            traceback.print_exc()
            time.sleep(10) # Pausa di sicurezza in caso di crash
        
        # Attesa fino al prossimo tick
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
