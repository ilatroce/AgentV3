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

# --- CONFIGURAZIONE BARRY: NEUTRAL GRID ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        # Controllo ogni 15 secondi

# Money Management
TOTAL_ALLOCATION_USD = 25.0   # Capitale Reale usato
LEVERAGE = 20                 # Leva 20x
GRID_LINES = 52               # 52 Linee
RANGE_PCT = 0.01              # Range +/- 1%

# Calcoli Griglia
STEP_PCT = (RANGE_PCT * 2) / GRID_LINES 

# Gatekeeper
VOLATILITY_LOOKBACK_MIN = 15 
VOLATILITY_THRESHOLD = 0.01  # 1%
PAUSE_DURATION = 900         # 15 Minuti pausa

def check_volatility_gatekeeper(bot, ticker):
    """Controlla volatilità. True = Safe, False = Danger."""
    try:
        df = bot.get_candles(ticker, interval="1m", limit=VOLATILITY_LOOKBACK_MIN)
        if df.empty: return True 
        
        high_max = df['high'].max()
        low_min = df['low'].min()
        
        volatility = (high_max - low_min) / low_min
        
        if volatility > VOLATILITY_THRESHOLD:
            print(f"⛔ [GATEKEEPER] Volatilità eccessiva ({volatility*100:.2f}%)!")
            return False
        return True
    except Exception as e:
        print(f"Err Gatekeeper: {e}")
        return True

def run_barry():
    print(f"⚡ [Barry Grid] Avvio su {TICKER}. Range +/- {RANGE_PCT*100}%.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    triggered_levels = set() 
    
    while True:
        try:
            # 1. Recupera Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0:
                time.sleep(5); continue

            # 2. Gatekeeper + SAFETY FLUSH (La modifica è qui)
            is_safe = check_volatility_gatekeeper(bot, TICKER)
            
            if not is_safe:
                print("⚠️ MERCATO PERICOLOSO RILEVATO.")
                
                # Controllo se ho posizioni da chiudere ("Flush")
                account = bot.get_account_status()
                positions = account.get("open_positions", [])
                my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
                
                if my_pos:
                    pnl_usd = float(my_pos['pnl_usd'])
                    print(f"💀 [FLUSH] Chiudo posizione {my_pos['side']} d'emergenza prima della pausa.")
                    bot.close_position(TICKER)
                    
                    payload = {
                        "operation": "CLOSE", "symbol": TICKER, 
                        "reason": "Gatekeeper Flush (High Volatility)", 
                        "pnl": pnl_usd, "agent": AGENT_NAME
                    }
                    db_utils.log_bot_operation(payload)
                else:
                    print("   Nessuna posizione aperta. Sono al sicuro.")

                print(f"⏳ [PAUSA] Dormo per {PAUSE_DURATION/60} minuti.")
                time.sleep(PAUSE_DURATION)
                
                # Reset Totale al risveglio
                center_price = None
                triggered_levels = set()
                continue 

            # 3. Gestione Stato Account (Se siamo Safe)
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # --- SETUP CENTRO GRIGLIA ---
            if not my_pos:
                if center_price is None:
                    center_price = current_price
                    triggered_levels = set()
                    print(f"🎯 [GRID START] Nuovo Centro: ${center_price:.4f}")
            else:
                if center_price is None:
                    center_price = float(my_pos['entry_price'])
                    print(f"🎯 [GRID RESUME] Centro recuperato: ${center_price:.4f}")

            # Calcoli
            upper_limit = center_price * (1 + RANGE_PCT)
            lower_limit = center_price * (1 - RANGE_PCT)
            
            # Debug
            # print(f"⚡ P: {current_price:.4f} | C: {center_price:.4f}")

            # --- AZIONE 1: STOP LOSS (Fuori Range) ---
            if current_price > upper_limit or current_price < lower_limit:
                if my_pos:
                    pnl_usd = float(my_pos['pnl_usd'])
                    print(f"💀 [STOP LOSS] Prezzo fuori range. CHIUDO TUTTO.")
                    bot.close_position(TICKER)
                    
                    payload = {
                        "operation": "CLOSE", "symbol": TICKER, 
                        "reason": "Grid Range Broken", "pnl": pnl_usd, "agent": AGENT_NAME
                    }
                    db_utils.log_bot_operation(payload)
                
                center_price = None
                triggered_levels = set()
                time.sleep(5)
                continue

            # --- AZIONE 2: ESECUZIONE GRIGLIA ---
            pct_diff = (current_price - center_price) / center_price
            current_level_index = int(pct_diff / STEP_PCT)
            
            if current_level_index != 0 and current_level_index not in triggered_levels:
                
                bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                
                if current_level_index > 0: # Sopra -> SHORT
                    direction = "SHORT"
                    print(f"🔴 [GRID SELL] Linea +{current_level_index}")
                    bot.execute_order(TICKER, "SHORT", bullet_size_usd) 
                    
                else: # Sotto -> LONG
                    direction = "LONG"
                    print(f"🟢 [GRID BUY] Linea {current_level_index}")
                    bot.execute_order(TICKER, "LONG", bullet_size_usd) 

                triggered_levels.add(current_level_index)
                
                # Yo-Yo Reset
                levels_to_remove = []
                for lvl in triggered_levels:
                    if abs(lvl - current_level_index) >= 2: 
                        levels_to_remove.append(lvl)
                
                for lvl in levels_to_remove:
                    triggered_levels.remove(lvl)
                    step_profit = bullet_size_usd * STEP_PCT
                    payload = {
                        "operation": "CLOSE_PARTIAL", "symbol": TICKER, "agent": AGENT_NAME,
                        "reason": f"Grid Return Lvl {lvl}", "pnl": step_profit
                    }
                    db_utils.log_bot_operation(payload)

                if direction:
                    payload = {
                        "operation": "OPEN", "symbol": TICKER, "direction": direction,
                        "reason": f"Grid Line {current_level_index}", "agent": AGENT_NAME,
                        "target_portion_of_balance": 0.01
                    }
                    db_utils.log_bot_operation(payload)

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
