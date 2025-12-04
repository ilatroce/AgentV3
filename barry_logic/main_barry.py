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

# --- CONFIGURAZIONE BARRY: ROCK SOLID HEDGER 🗿 ---
AGENT_NAME = "Barry"
LOOP_SPEED = 15        

# Asset
TICKER_MAIN = "SUI"    # Long Strategy
TICKER_HEDGE = "SOL"   # Short Strategy

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 

# Strategia
SUI_OFFSET = 0.001   
SUI_TP = 0.002

SOL_OFFSET = 0.01
SOL_TP = 0.02

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
            if isinstance(o_type, dict) and 'trigger' in o_type:
                trigger_orders.append(o)
            elif isinstance(o_type, str) and 'trigger' in o_type.lower():
                trigger_orders.append(o)
            else:
                limit_orders.append(o)

        # --- CASO A: ABBIAMO UNA POSIZIONE APERTA ---
        if my_pos:
            # 1. Pulizia Limit: Se siamo dentro, cancelliamo gli ordini di ENTRATA
            if limit_orders:
                print(f"🧹 [{ticker}] In posizione. Cancello Limit Entry.")
                for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
            
            # 2. Gestione Take Profit (Trigger) - STABILE
            current_pos_size = float(my_pos['size'])
            
            # Cerchiamo se esiste UN ordine TP valido che copra la size
            # Non ci interessa il prezzo esatto (lasciamo quello originale), basta che copra la size.
            tp_found = None
            
            for o in trigger_orders:
                order_sz = float(o['sz'])
                # Tolleranza 1% sulla size (per evitare problemi di arrotondamento)
                if abs(order_sz - current_pos_size) < (current_pos_size * 0.01):
                    tp_found = o
                    break
            
            # Se abbiamo trovato un TP valido, controlliamo se è l'unico
            if tp_found:
                # Se ce ne sono altri oltre a quello buono, cancellali (pulizia)
                if len(trigger_orders) > 1:
                    print(f"🧹 [{ticker}] Cancello TP duplicati.")
                    for o in trigger_orders:
                        if o['oid'] != tp_found['oid']:
                            bot.exchange.cancel(ticker, o['oid'])
                
                # Tutto ok, NON FACCIAMO NULLA. Il TP resta dov'è.
                # print(f"✅ [{ticker}] TP Stabile @ {tp_found['triggerPx']}")
            
            # Se NON abbiamo trovato un TP valido (o la size è cambiata troppo), piazziamone uno nuovo
            else:
                if trigger_orders:
                    print(f"♻️ [{ticker}] Size cambiata. Resetto TP.")
                    for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])
                
                entry_px = float(my_pos['entry_price'])
                if mode == 'LONG':
                    target_px = round(entry_px + SUI_TP, 4)
                    is_buy_close = False 
                else: # SHORT
                    target_px = round(entry_px - SOL_TP, 2)
                    is_buy_close = True 

                # Safety: Il TP deve essere migliorativo rispetto al prezzo attuale
                if mode == 'LONG' and target_px <= price: target_px = price * 1.002
                if mode == 'SHORT' and target_px >= price: target_px = price * 0.998

                print(f"🛡️ [{ticker}] Piazzo NUOVO TP @ {target_px} (Size: {current_pos_size})")
                bot.place_take_profit(ticker, is_buy_close, current_pos_size, target_px)

        # --- CASO B: SIAMO FLAT ---
        else:
            # 1. Pulizia Trigger: Se siamo Flat, cancelliamo TUTTI i TP
            if trigger_orders:
                print(f"🧹 [{ticker}] Flat. Cancello Trigger orfani.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # 2. Logica Entrata (Trailing Entry)
            should_enter = True
            
            if mode == 'SHORT' and (pnl_trigger is None or pnl_trigger > -0.05):
                should_enter = False
                if limit_orders: 
                    print(f"🟢 [{ticker}] Hedge non necessario. Cancello ordini.")
                    for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                return 

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
                        current_order_px = float(limit_orders[0]['limitPx'])
                        if abs(current_order_px - target_entry) < (target_entry * 0.0005): 
                            order_ok = True
                        else:
                            bot.exchange.cancel(ticker, limit_orders[0]['oid'])
                
                if not order_ok:
                    print(f"🔫 [{ticker}] Piazzo Limit {mode}: {amount} @ {target_entry}")
                    bot.exchange.order(ticker, is_buy_entry, amount, target_entry, {"limit": {"tif": "Gtc"}})
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "reason": "Trailing Entry", "agent": AGENT_NAME})

    except Exception as e:
        print(f"Err Manage {ticker}: {e}")

def run_barry():
    print(f"⚔️ [Barry Stable] Avvio Trailing Entry + Rock Solid TP.")
    
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
