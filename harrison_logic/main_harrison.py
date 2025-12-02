import sys
import os
import time
import pandas as pd
import traceback
from dotenv import load_dotenv

# Import root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE HARRISON: VOLATILITY HUNTER (REVERSE GRID) 🌪️ ---
AGENT_NAME = "Harrison"
TICKER = "FARTCOIN"        # Harrison ama la volatilità, DOGE è perfetto
LOOP_SPEED = 15         # Controllo veloce (5s)

# Money Management
TOTAL_ALLOCATION_USD = 25.0   
LEVERAGE = 25                 # Leva 25x (Aggressivo)
GRID_LEVELS = 10              # 10 Livelli per lato (Pyramiding)
BREAKOUT_TARGET_PCT = 0.01    # Target 1% (Take Profit Finale)

# Calcolo Step: 1% / 10 livelli = 0.1% a scalino
STEP_PCT = BREAKOUT_TARGET_PCT / GRID_LEVELS 

# Gatekeeper INVERSO (Si attiva solo se c'è caos)
VOLATILITY_LOOKBACK_MIN = 15 
MIN_VOLATILITY_THRESHOLD = 0.01  # DEVE esserci almeno 1% di movimento recente
PAUSE_DURATION = 900             # 15 Minuti di sonno se il mercato è piatto

def check_volatility_activation(bot, ticker):
    """
    Ritorna True se c'è ABBASTANZA volatilità per operare.
    Ritorna False se il mercato è troppo piatto (Harrison dorme).
    """
    try:
        df = bot.get_candles(ticker, interval="1m", limit=VOLATILITY_LOOKBACK_MIN)
        if df.empty: return False 
        
        high_max = df['high'].max()
        low_min = df['low'].min()
        
        volatility = (high_max - low_min) / low_min
        
        # Se la volatilità è BASSA (< 1%), Harrison non lavora
        if volatility < MIN_VOLATILITY_THRESHOLD:
            print(f"💤 [SLEEP] Volatilità troppo bassa ({volatility*100:.2f}%). Torno a dormire.")
            return False
            
        print(f"🌪️ [ACTIVE] Volatilità rilevata ({volatility*100:.2f}%). Caccia aperta!")
        return True
    except Exception as e:
        print(f"Err Volatility Check: {e}")
        return False

def run_harrison():
    print(f"🌪️ [Harrison] Avvio su {TICKER}. Attendo tempesta (>1% vol).")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    highest_level_reached = 0 # Track record del livello massimo toccato (per Stop Loss a gradini)
    
    while True:
        try:
            # 1. Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(2); continue

            # 2. Gatekeeper Inverso (Si attiva solo se VOLATILITÀ ALTA)
            is_active_market = check_volatility_activation(bot, TICKER)
            
            # Se il mercato è piatto E non abbiamo posizioni -> Dormi
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)

            if not is_active_market and not my_pos:
                print(f"💤 Harrison dorme per {PAUSE_DURATION/60} minuti.")
                time.sleep(PAUSE_DURATION)
                center_price = None # Al risveglio ricalcola il centro
                continue

            # 3. Setup Centro
            if not my_pos:
                if center_price is None:
                    center_price = current_price
                    highest_level_reached = 0
                    print(f"🎯 [HARRISON START] Centro fissato: ${center_price:.4f}")
            else:
                # Se siamo in ballo, il centro è fisso all'entry
                if center_price is None:
                    center_price = float(my_pos['entry_price'])

            # Calcolo posizione nella griglia
            pct_diff = (current_price - center_price) / center_price
            current_level_idx = int(pct_diff / STEP_PCT) # Es. +3, -4
            
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            
            # --- AZIONE 1: TAKE PROFIT FINALE (Breakthrough 1%) ---
            if abs(pct_diff) >= BREAKOUT_TARGET_PCT:
                print(f"🚀 [VICTORY] Target 1% raggiunto! Chiudo tutto in profitto.")
                bot.close_position(TICKER)
                
                payload = {
                    "operation": "CLOSE", "symbol": TICKER, 
                    "reason": "Target 1% Hit (Victory)", "pnl": pnl_usd, "agent": AGENT_NAME
                }
                db_utils.log_bot_operation(payload)
                
                center_price = None
                highest_level_reached = 0
                time.sleep(10)
                continue

            # --- AZIONE 2: PYRAMIDING (Aggiungi se il trend continua) ---
            # Se superiamo il livello massimo raggiunto finora
            if abs(current_level_idx) > abs(highest_level_reached):
                
                # Calcolo direzione
                direction = "LONG" if current_level_idx > 0 else "SHORT"
                
                # Safety check: non invertire il trend (se ero long e ora sono sotto zero, non apro short qui, aspetto stop loss)
                if highest_level_reached != 0 and (current_level_idx * highest_level_reached < 0):
                    pass # Siamo nella zona opposta ma dobbiamo prima chiudere la vecchia
                else:
                    print(f"🌪️ [PYRAMID] Livello {current_level_idx} raggiunto! Aumento posizione.")
                    
                    # Size del "Proiettile" (Più piccola perché ne aggiungiamo tante)
                    bullet_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                    
                    bot.execute_order(TICKER, direction, bullet_usd)
                    
                    highest_level_reached = current_level_idx
                    
                    payload = {
                        "operation": "OPEN", "symbol": TICKER, "direction": direction,
                        "reason": f"Trend Level {current_level_idx}", "agent": AGENT_NAME,
                        "target_portion_of_balance": 0.01
                    }
                    db_utils.log_bot_operation(payload)
                    time.sleep(1)

            # --- AZIONE 3: TRAILING STOP (Il "Gradino Precedente") ---
            # Se il prezzo torna indietro di 1 Livello rispetto al massimo raggiunto -> CHIUDI TUTTO
            # Esempio: Siamo arrivati a +5. Se il prezzo scende a +4 -> STOP LOSS.
            
            should_close = False
            
            if highest_level_reached > 0: # Eravamo LONG
                if current_level_idx < (highest_level_reached - 1): # Sceso di 2 gradini (Buffer sicurezza) o 1 secco
                    print(f"✂️ [TRAILING CUT] Prezzo sceso da Lvl {highest_level_reached} a {current_level_idx}.")
                    should_close = True
            
            elif highest_level_reached < 0: # Eravamo SHORT
                if current_level_idx > (highest_level_reached + 1): # Salito di gradini
                    print(f"✂️ [TRAILING CUT] Prezzo salito da Lvl {highest_level_reached} a {current_level_idx}.")
                    should_close = True

            if should_close and my_pos:
                print("💀 Chiusura posizione (Trend Invertito).")
                bot.close_position(TICKER)
                
                payload = {
                    "operation": "CLOSE", "symbol": TICKER, 
                    "reason": f"Trailing Stop (Rev from Lvl {highest_level_reached})", 
                    "pnl": pnl_usd, "agent": AGENT_NAME
                }
                db_utils.log_bot_operation(payload)
                
                center_price = None
                highest_level_reached = 0
                time.sleep(5)

        except Exception as e:
            print(f"Err Harrison: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_harrison()
