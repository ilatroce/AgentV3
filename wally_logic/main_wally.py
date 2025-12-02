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

# --- CONFIGURAZIONE WALLY: MAKER GRID (AVAX) 🧪 ---
AGENT_NAME = "Wally"
TICKER = "AVAX"        
LOOP_SPEED = 10        # 10s

# Money Management
TOTAL_ALLOCATION_USD = 20.0   
LEVERAGE = 20                 
GRID_LINES = 52               
RANGE_PCT = 0.01              # Range +/- 1%

# Calcoli Griglia
STEP_PCT = (RANGE_PCT * 2) / GRID_LINES 

# Gatekeeper
VOLATILITY_LOOKBACK_MIN = 15 
VOLATILITY_THRESHOLD = 0.01  # 1%
PAUSE_DURATION = 900         

def check_gatekeeper(bot, ticker):
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

def cancel_all_limit_orders(bot, ticker):
    """Cancella tutti gli ordini pendenti per questo ticker"""
    try:
        addr = bot.account_address 
        open_orders = bot.info.open_orders(addr)
        for order in open_orders:
            if order['coin'] == ticker:
                # print(f"🧹 Cancello ordine {order['oid']}...")
                bot.exchange.cancel(ticker, order['oid'])
                time.sleep(0.1) 
        print(f"🧹 [CLEANUP] Ordini Limit cancellati su {ticker}.")
    except Exception as e:
        print(f"Err cancel_all: {e}")

def run_wally():
    print(f"🧪 [Wally MAKER] Avvio su {TICKER}. Range +/- {RANGE_PCT*100}%.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    grid_initialized = False
    
    while True:
        try:
            # 1. Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue

            # 2. Gatekeeper
            is_safe = check_gatekeeper(bot, TICKER)
            
            if not is_safe:
                print("⚠️ MERCATO PERICOLOSO. PAUSA E CANCELLAZIONE.")
                cancel_all_limit_orders(bot, TICKER)
                
                # Flush
                account = bot.get_account_status()
                my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
                if my_pos:
                    pnl_usd = float(my_pos['pnl_usd'])
                    print(f"💀 [FLUSH] Chiudo tutto a mercato.")
                    bot.close_position(TICKER)
                    payload = {"operation": "CLOSE", "symbol": TICKER, "reason": "Gatekeeper Flush", "pnl": pnl_usd, "agent": AGENT_NAME}
                    db_utils.log_bot_operation(payload)

                print(f"⏳ Dormo per {PAUSE_DURATION/60} minuti.")
                time.sleep(PAUSE_DURATION)
                center_price = None; grid_initialized = False; continue 

            # 3. Stato Account
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            
            # --- INIZIALIZZAZIONE GRIGLIA (MAKER) ---
            if not grid_initialized:
                
                if not my_pos:
                    center_price = current_price
                    print(f"🎯 [GRID START] Nuovo Centro: ${center_price:.4f}")
                else:
                    center_price = float(my_pos['entry_price'])
                    print(f"🎯 [GRID RESUME] Centro recuperato: ${center_price:.4f}")

                bullet_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                print(f"🛠️ [BUILD] Piazzo {GRID_LINES} ordini Limit (Size: ~${bullet_usd:.2f})...")
                
                # LATO BUY (Sotto il centro)
                for i in range(1, int(GRID_LINES/2) + 1):
                    # CALCOLO PREZZO E ARROTONDAMENTO (FIX ERROR)
                    raw_price = center_price * (1 - (STEP_PCT * i))
                    price = round(raw_price, 4) # Arrotonda prezzo a 4 decimali
                    
                    if price < current_price: 
                        raw_amount = bullet_usd / price
                        amount = round(raw_amount, 2) # Arrotonda quantità a 2 decimali
                        
                        res = bot.exchange.order(TICKER, True, amount, price, {"limit": {"tif": "Gtc"}})
                        if res['status'] == 'ok': print(f"   ➕ Limit BUY @ {price}")
                        time.sleep(0.2)

                # LATO SELL (Sopra il centro)
                for i in range(1, int(GRID_LINES/2) + 1):
                    # CALCOLO PREZZO E ARROTONDAMENTO (FIX ERROR)
                    raw_price = center_price * (1 + (STEP_PCT * i))
                    price = round(raw_price, 4) # Arrotonda prezzo a 4 decimali
                    
                    if price > current_price:
                        raw_amount = bullet_usd / price
                        amount = round(raw_amount, 2) # Arrotonda quantità a 2 decimali
                        
                        res = bot.exchange.order(TICKER, False, amount, price, {"limit": {"tif": "Gtc"}})
                        if res['status'] == 'ok': print(f"   ➖ Limit SELL @ {price}")
                        time.sleep(0.2)

                grid_initialized = True
                print("✅ Griglia Piazzata.")

            # --- MONITORAGGIO STOP LOSS ---
            upper_limit = center_price * (1 + RANGE_PCT)
            lower_limit = center_price * (1 - RANGE_PCT)
            
            if current_price > upper_limit or current_price < lower_limit:
                print(f"💀 [STOP LOSS] Prezzo fuori range ({current_price}). CHIUDO TUTTO.")
                cancel_all_limit_orders(bot, TICKER)
                if my_pos:
                    pnl_usd = float(my_pos['pnl_usd'])
                    bot.close_position(TICKER)
                    payload = {"operation": "CLOSE", "symbol": TICKER, "reason": "Range Broken", "pnl": pnl_usd, "agent": AGENT_NAME}
                    db_utils.log_bot_operation(payload)
                center_price = None; grid_initialized = False; time.sleep(10); continue

            # --- REFRESH GRIGLIA ---
            # Se la griglia è mezza vuota, resettiamo per seguire il prezzo
            open_orders = bot.info.open_orders(bot.account_address)
            my_orders = [o for o in open_orders if o['coin'] == TICKER]
            
            if len(my_orders) < (GRID_LINES * 0.5): 
                print("🔄 [REFRESH] Molti ordini eseguiti. Ripiazzo la griglia.")
                cancel_all_limit_orders(bot, TICKER)
                grid_initialized = False 
                time.sleep(5)

        except Exception as e:
            print(f"Err Wally: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_wally()
