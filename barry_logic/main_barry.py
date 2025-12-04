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

# --- CONFIGURAZIONE BARRY: HEDGER (HANDS OFF TP) 🛡️ ---
AGENT_NAME = "Barry"
LOOP_SPEED = 15        

# Asset
TICKER_MAIN = "SUI"    # Long
TICKER_HEDGE = "SOL"   # Short

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 

# Strategia
SUI_OFFSET = 0.001   
SUI_TP = 0.003

SOL_OFFSET = 0.03
SOL_TP = 0.07

def manage_asset(bot, ticker, mode, price, pnl_trigger=None):
    try:
        # 1. Analisi Stato
        account = bot.get_account_status()
        my_pos = next((p for p in account["open_positions"] if p["symbol"] == ticker), None)
        
        # Recupera ordini aperti
        orders = bot.info.open_orders(bot.account_address)
        my_orders = [o for o in orders if o['coin'] == ticker]
        
        limit_orders = []
        trigger_orders = []
        
        for o in my_orders:
            o_type = o.get('orderType', o.get('type', 'Limit'))
            if (isinstance(o_type, dict) and 'trigger' in o_type) or \
               (isinstance(o_type, str) and 'trigger' in o_type.lower()):
                trigger_orders.append(o)
            else:
                limit_orders.append(o)

        # --- CASO A: POSIZIONE APERTA (Gestione TP) ---
        if my_pos:
            # 1. Pulizia: Cancella ordini di Entrata (Limit)
            if limit_orders:
                print(f"🧹 [{ticker}] In posizione. Cancello Limit Entry.")
                for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
            
            # 2. LOGICA "HANDS OFF" TP
            pos_size = float(my_pos['size'])
            
            # C'è ALMENO UN TP valido (che copra almeno il 90% della size)?
            # Se sì, NON TOCCARE NULLA.
            valid_tp_exists = False
            for o in trigger_orders:
                if float(o['sz']) >= (pos_size * 0.9):
                    valid_tp_exists = True
                    break
            
            if valid_tp_exists:
                # print(f"✅ [{ticker}] TP Presente. Standby.")
                return # ESCI SUBITO, NON FARE NULLA

            # Se siamo qui, significa che NON c'è nessun TP valido.
            # Cancelliamo eventuali TP "spazzatura" (size troppo piccola)
            if trigger_orders:
                print(f"♻️ [{ticker}] TP inadeguato. Resetto.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # Piazziamo il NUOVO TP una volta sola
            entry_px = float(my_pos['entry_price'])
            
            if mode == 'LONG':
                target_px = round(entry_px + SUI_TP, 4)
                is_buy_close = False 
                # Safety: Il TP deve essere sopra il prezzo attuale
                if target_px <= price: target_px = price * 1.002
            else: # SHORT
                target_px = round(entry_px - SOL_TP, 2)
                is_buy_close = True 
                if target_px >= price: target_px = price * 0.998

            print(f"🛡️ [{ticker}] Piazzo TP @ {target_px}")
            bot.place_take_profit(ticker, is_buy_close, pos_size, target_px)

        # --- CASO B: SIAMO FLAT (Gestione Entry) ---
        else:
            # 1. Pulizia TP vecchi
            if trigger_orders:
                print(f"🧹 [{ticker}] Flat. Cancello TP.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # 2. Logica Hedge Check
            should_enter = True
            if mode == 'SHORT' and (pnl_trigger is None or pnl_trigger > -0.05):
                should_enter = False
                if limit_orders: 
                    print(f"🟢 [{ticker}] Hedge Off. Cancello ordini.")
                    for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                return 

            # 3. Trailing Entry (Come prima)
            if should_enter:
                if mode == 'LONG': 
                    target_entry = round(price - SUI_OFFSET, 4)
                    is_buy_entry = True
                else: 
                    target_entry = round(price + SOL_OFFSET, 2)
                    is_buy_entry = False

                amount = round(POSITION_SIZE_USD / target_entry, 1)

                order_ok = False
                if limit_orders:
                    if len(limit_orders) > 1:
                        for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                    else:
                        current_px = float(limit_orders[0]['limitPx'])
                        # Aggiorna solo se si sposta significativamente
                        if abs(current_px - target_entry) < (target_entry * 0.0005): 
                            order_ok = True
                        else:
                            bot.exchange.cancel(ticker, limit_orders[0]['oid'])
                
                if not order_ok:
                    print(f"🔫 [{ticker}] Piazzo Entry Limit: {amount} @ {target_entry}")
                    bot.exchange.order(ticker, is_buy_entry, amount, target_entry, {"limit": {"tif": "Gtc"}})
                    
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "reason": "Trailing Entry", "agent": AGENT_NAME})

    except Exception as e:
        print(f"Err Manage {ticker}: {e}")

def run_barry():
    print(f"⚔️ [Barry Hands-Off] Avvio SUI/SOL Hedge.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            p_sui = bot.get_market_price(TICKER_MAIN)
            p_sol = bot.get_market_price(TICKER_HEDGE)
            if p_sui == 0 or p_sol == 0: time.sleep(5); continue

            account = bot.get_account_status()
            pos_sui = next((p for p in account["open_positions"] if p["symbol"] == TICKER_MAIN), None)
            pnl_sui = float(pos_sui['pnl_usd']) if pos_sui else 0.0
            
            print(f"\n⚡ SUI: {p_sui} | SOL: {p_sol} | Hedge Trigger: {pnl_sui:.2f}")

            manage_asset(bot, TICKER_MAIN, 'LONG', p_sui)
            manage_asset(bot, TICKER_HEDGE, 'SHORT', p_sol, pnl_trigger=pnl_sui)

        except Exception as e:
            print(f"Err Loop: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
