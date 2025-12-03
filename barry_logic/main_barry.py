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

# --- CONFIGURAZIONE BARRY: SHORT GRID MAKER ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        # Controllo ogni 15 secondi

# Money Management
TOTAL_MARGIN = 50.0    # Budget Reale (Margin)
LEVERAGE = 20          # Leva 20x
GRID_LINES = 30        # 30 Griglie totali

# Range Operativo
RANGE_TOP = 1.90
RANGE_BOTTOM = 1.45
CENTER_PRICE = 1.69    # Punto di partenza

# Calcoli Geometrici
TOTAL_NOTIONAL = TOTAL_MARGIN * LEVERAGE  # Potenza di fuoco (es. 1000$)
SIZE_PER_GRID_USD = TOTAL_NOTIONAL / GRID_LINES # Es. 33$ a ordine
GRID_STEP = (RANGE_TOP - RANGE_BOTTOM) / GRID_LINES # Step di prezzo

def get_grid_levels():
    """Genera i prezzi esatti della griglia da Bottom a Top"""
    levels = []
    for i in range(GRID_LINES + 1):
        price = RANGE_BOTTOM + (GRID_STEP * i)
        levels.append(round(price, 4))
    return levels

def cancel_all_orders(bot):
    """Pulisce il book"""
    try:
        # FIX: Usa account_address invece di account.address
        addr = bot.account_address
        open_orders = bot.info.open_orders(addr)
        for order in open_orders:
            if order['coin'] == TICKER:
                bot.exchange.cancel(TICKER, order['oid'])
        print(f"🧹 [CLEANUP] Ordini cancellati.")
    except Exception as e: 
        print(f"Err cleanup: {e}")

def run_barry():
    print(f"⚡ [Barry ShortGrid] Avvio su {TICKER}.")
    print(f"   Range: {RANGE_BOTTOM} - {RANGE_TOP} | Centro: {CENTER_PRICE}")
    print(f"   Size per livello: ${SIZE_PER_GRID_USD:.2f}")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    # 1. Setup Iniziale: Startup Short?
    account = bot.get_account_status()
    my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
    
    if not my_pos:
        print("⚡ [STARTUP] Nessuna posizione. Apro SHORT iniziale (Metà allocazione)...")
        # Metà allocazione = 15 grid * size
        startup_size = SIZE_PER_GRID_USD * (GRID_LINES / 2)
        # Usa market entry per l'inizio
        bot.execute_order(TICKER, "SHORT", startup_size)
        time.sleep(2) 
    
    # Genera i livelli fissi della griglia
    grid_prices = get_grid_levels()
    
    while True:
        try:
            # A. Controllo Prezzo e Range (KILL SWITCH)
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue
            
            # print(f"\n⚡ [CHECK] Prezzo: {current_price:.4f}")

            # SE FUORI RANGE -> CHIUDI TUTTO E MUORI
            if current_price >= RANGE_TOP or current_price <= RANGE_BOTTOM:
                print(f"💀 [KILL SWITCH] Prezzo fuori range! Chiudo tutto e termino.")
                
                cancel_all_orders(bot)
                
                account = bot.get_account_status()
                my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
                if my_pos:
                    pnl = float(my_pos['pnl_usd'])
                    bot.close_position(TICKER)
                    
                    payload = {
                        "operation": "CLOSE", "symbol": TICKER, 
                        "reason": "Out of Range (Kill Switch)", 
                        "pnl": pnl, "agent": AGENT_NAME
                    }
                    db_utils.log_bot_operation(payload)
                
                print("👋 Addio. Programma terminato.")
                sys.exit(0) 

            # B. Riconciliazione Griglia (Logic Loop)
            # FIX: Usa account_address anche qui
            open_orders = bot.info.open_orders(bot.account_address)
            my_orders = [o for o in open_orders if o['coin'] == TICKER]
            my_order_prices = [float(o['limitPx']) for o in my_orders]
            
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            
            # Size della posizione attuale (in coin)
            pos_size_coin = float(my_pos['size']) if my_pos else 0.0
            
            # Cicla attraverso tutti i livelli ideali della griglia
            for level_price in grid_prices:
                
                level_price = round(level_price, 4)
                
                # C'è già un ordine qui?
                has_order = any(abs(p - level_price) < 0.0001 for p in my_order_prices)
                
                if has_order:
                    continue 
                
                # --- LOGICA PIAZZAMENTO ---
                # Calcola coin amount
                amount_coin = round(SIZE_PER_GRID_USD / level_price, 1) 
                
                # 1. LIVELLO SOPRA IL PREZZO -> LIMIT SELL (Short)
                if level_price > current_price:
                    print(f"   ➕ Piazzamento: SELL (Short) @ {level_price}")
                    # Usa funzione nativa per Limit Order
                    bot.exchange.order(TICKER, False, amount_coin, level_price, {"limit": {"tif": "Gtc"}})
                    time.sleep(0.1)
                
                # 2. LIVELLO SOTTO IL PREZZO -> LIMIT BUY (Take Profit)
                # SOLO se abbiamo posizione short aperta da coprire!
                elif level_price < current_price:
                    if pos_size_coin > amount_coin: 
                        print(f"   ➕ Piazzamento: BUY (TP) @ {level_price}")
                        bot.exchange.order(TICKER, True, amount_coin, level_price, {"limit": {"tif": "Gtc"}})
                        # Scaliamo virtualmente per non piazzare troppi buy
                        pos_size_coin -= amount_coin
                        time.sleep(0.1)

        except Exception as e:
            print(f"Err Barry: {e}")
            traceback.print_exc()
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
