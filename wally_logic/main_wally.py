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
        # FIX: Usiamo account_address (stringa) invece di account.address (oggetto)
        # Questo evita l'errore 'no attribute account'
        addr = bot.account_address 
        
        open_orders = bot.info.open_orders(addr)
        for order in open_orders:
            if order['coin'] == ticker:
                print(f"🧹 Cancello ordine {order['oid']}...")
                bot.exchange.cancel(ticker, order['oid'])
                time.sleep(0.1) # Evita rate limit
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
                
                # A) Cancella ordini pendenti
                cancel_all_limit_orders(bot, TICKER)
                
                # B) Chiudi posizioni aperte (Flush)
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
                
                # Reset
                center_price = None
                grid_initialized = False
                continue 

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

                upper_limit = center_price * (1 + RANGE_PCT)
                lower_limit = center_price * (1 - RANGE_PCT)
                bullet_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                
                print(f"🛠️ [BUILD] Piazzo {GRID_LINES} ordini Limit...")
                
                # Piazziamo gli ordini
                # LATO BUY (Sotto il centro)
                for i in range(1, int(GRID_LINES/2) + 1):
                    price = center_price * (1 - (STEP_PCT * i))
                    if price < current_price: 
                        amount = round(bullet_usd / price, 4)
                        # Nota: Usiamo la funzione nativa exchange.order
                        res = bot.exchange.order(TICKER, True, amount, price, {"limit": {"tif": "Gtc"}})
                        # if res['status'] == 'ok': print(f"   ➕ Limit BUY @ {price:.4f}")
                        time.sleep(0.1)

                # LATO SELL (Sopra il centro)
                for i in range(1, int(GRID_LINES/2) + 1):
                    price = center_price * (1 + (STEP_PCT * i))
                    if price > current_price:
                        amount = round(bullet_usd / price, 4)
                        res = bot.exchange.order(TICKER, False, amount, price, {"limit": {"tif": "Gtc"}})
                        # if res['status'] == 'ok': print(f"   ➖ Limit SELL @ {price:.4f}")
                        time.sleep(0.1)

                grid_initialized = True
                print("✅ Griglia Piazzata.")

            # --- MONITORAGGIO E STOP LOSS ---
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
                
                center_price = None
                grid_initialized = False
                time.sleep(10)
                continue

            # --- REFRESH GRIGLIA ---
            # Se la griglia è stata consumata per metà, resettiamo
            # Usiamo account_address anche qui per sicurezza
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
