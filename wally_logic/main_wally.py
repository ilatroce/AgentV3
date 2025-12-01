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

# --- CONFIGURAZIONE WALLY: TEST DRIVER 🧪 ---
AGENT_NAME = "Wally"
TICKER = "AVAX"        # Asset diverso per non disturbare Barry
LOOP_SPEED = 5         # Controllo veloce

# Money Management
TOTAL_ALLOCATION_USD = 25.0   # Budget per il test
LEVERAGE = 25                 # Ricorda di impostare 20x su Hyperliquid per AVAX!
GRID_LINES = 52               # 52 Linee
RANGE_PCT = 0.01              # Range +/- 1%

# Calcolo Step
STEP_PCT = (RANGE_PCT * 2) / GRID_LINES 

# Safety Caps
MAX_NOTIONAL_POSITION = TOTAL_ALLOCATION_USD * LEVERAGE 
STOP_LOSS_PRICE_PCT = 0.015 

# Gatekeeper
MAX_CANDLE_SIZE = 0.008

def check_gatekeeper(bot, ticker):
    try:
        df = bot.get_candles(ticker, "1m", 15)
        if df.empty: return True
        
        open_p = df['open'].iloc[-1]
        close_p = df['close'].iloc[-1]
        if abs(close_p - open_p) / open_p > MAX_CANDLE_SIZE:
            print("⛔ [GATEKEEPER] Candela troppo grande!")
            return False
        return True
    except: return True

def run_wally():
    print(f"🧪 [Wally Test] Avvio su {TICKER}. Allocazione: ${MAX_NOTIONAL_POSITION:.2f}")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    active_levels = {} 
    
    while True:
        try:
            # 1. Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(2); continue

            # 2. Gatekeeper
            if not check_gatekeeper(bot, TICKER):
                print("⏳ Mercato agitato. Pausa 60s.")
                time.sleep(60)
                continue

            # 3. Stato Account
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # Controllo Esposizione
            current_size_usd = 0.0
            if my_pos:
                current_size_usd = float(my_pos['size']) * current_price
            
            # --- CENTRO GRIGLIA ---
            if not my_pos:
                if center_price is None or len(active_levels) > 0:
                    center_price = current_price
                    active_levels = {} 
                    print(f"🎯 [RESET] Nuovo Centro: ${center_price:.4f}")
            else:
                if center_price is None:
                    center_price = float(my_pos['entry_price'])
                    print(f"🎯 [RESUME] Centro: ${center_price:.4f}")

            # Calcolo Indice Griglia
            pct_diff = (current_price - center_price) / center_price
            current_idx = int(pct_diff / STEP_PCT)
            
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0

            # --- AZIONE 1: STOP LOSS ---
            if abs(pct_diff) > STOP_LOSS_PRICE_PCT:
                if my_pos:
                    print("💀 [STOP LOSS] Fuori Range. Chiudo tutto.")
                    bot.close_position(TICKER)
                    payload = {"operation": "CLOSE", "symbol": TICKER, "reason": "Stop Loss", "pnl": pnl_usd, "agent": AGENT_NAME}
                    db_utils.log_bot_operation(payload)
                center_price = None
                active_levels = {}
                time.sleep(10)
                continue

            # --- AZIONE 2: APERTURA (Accumulo) ---
            if current_idx != 0 and current_idx not in active_levels:
                if current_size_usd >= MAX_NOTIONAL_POSITION:
                    pass
                else:
                    bullet_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                    direction = "SHORT" if current_idx > 0 else "LONG"
                    
                    print(f"🧪 [OPEN] Livello {current_idx} ({direction}) @ {current_price:.4f}")
                    bot.execute_order(TICKER, direction, bullet_usd)
                    
                    active_levels[current_idx] = current_price
                    
                    payload = {
                        "operation": "OPEN", "symbol": TICKER, "direction": direction,
                        "reason": f"Grid Lvl {current_idx}", "agent": AGENT_NAME,
                        "target_portion_of_balance": 0.01
                    }
                    db_utils.log_bot_operation(payload)
                    time.sleep(1)

            # --- AZIONE 3: CHIUSURA (Take Profit) ---
            levels_to_close = []
            for lvl_idx in list(active_levels.keys()):
                is_profit = False
                # SHORT: Chiude se prezzo scende (indice minore)
                if lvl_idx > 0:
                    if current_idx < lvl_idx: 
                        is_profit = True
                        close_dir = "LONG"
                # LONG: Chiude se prezzo sale (indice maggiore)
                elif lvl_idx < 0:
                    if current_idx > lvl_idx: 
                        is_profit = True
                        close_dir = "SHORT"

                if is_profit:
                    print(f"💎 [PROFIT] Livello {lvl_idx} recuperato!")
                    bullet_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                    bot.execute_order(TICKER, close_dir, bullet_usd)
                    levels_to_close.append(lvl_idx)
                    
                    step_gain = bullet_usd * STEP_PCT
                    payload = {
                        "operation": "CLOSE_PARTIAL", "symbol": TICKER, "agent": AGENT_NAME,
                        "reason": f"Scalp Lvl {lvl_idx}", "pnl": step_gain
                    }
                    db_utils.log_bot_operation(payload)
                    time.sleep(1)

            for lvl in levels_to_close:
                del active_levels[lvl]

            if not my_pos and active_levels:
                active_levels = {}
                center_price = None

        except Exception as e:
            print(f"Err Wally: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_wally()
