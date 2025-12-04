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

# --- CONFIGURAZIONE BARRY: STABLE HEDGER ⚔️ ---
AGENT_NAME = "Barry"
LOOP_SPEED = 15        

# Asset
TICKER_MAIN = "SUI"    # Long Strategy
TICKER_HEDGE = "SOL"   # Short Strategy

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 # 10$ a posizione

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
        
        # Recupera ordini aperti (Usa account_address per sicurezza)
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
            # 1. Pulizia: Se siamo dentro, cancelliamo gli ordini di ENTRATA (Limit)
            if limit_orders:
                print(f"🧹 [{ticker}] In posizione. Cancello Limit Entry.")
                for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
            
            # 2. Gestione Take Profit (Trigger) - LOGICA SET AND FORGET
            size = float(my_pos['size'])
            
            # C'è già un TP valido?
            tp_ok = False
            for o in trigger_orders:
                # Controlliamo SOLO se la size corrisponde. Il prezzo lo ignoriamo (lasciamo quello vecchio).
                # Questo evita il "ricalcolo continuo" che spostava il TP in perdita.
                if float(o['sz']) == size:
                    tp_ok = True
                    # print(f"🛡️ [{ticker}] TP già attivo @ {o['triggerPx']}. Non tocco.")
                    break
            
            # Se ci sono TP con size sbagliata (vecchi residui), cancellali
            if not tp_ok and trigger_orders:
                print(f"♻️ [{ticker}] TP size errata. Resetto.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # Se non c'è nessun TP valido, piazzalo ORA
            if not tp_ok and not trigger_orders:
                entry_px = float(my_pos['entry_price'])
                
                if mode == 'LONG':
                    target_px = round(entry_px + SUI_TP, 4)
                    is_buy_close = False 
                else: # SHORT
                    target_px = round(entry_px - SOL_TP, 2)
                    is_buy_close = True 

                print(f"🛡️ [{ticker}] Piazzo NUOVO TP @ {target_px}")
                bot.place_take_profit(ticker, is_buy_close, size, target_px)

        # --- CASO B: SIAMO FLAT ---
        else:
            # 1. Pulizia: Se siamo Flat, cancelliamo i TP (Trigger) vecchi
            if trigger_orders:
                print(f"🧹 [{ticker}] Flat. Cancello Trigger orfani.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # 2. Logica Entrata (Trailing Entry)
            should_enter = True
            
            # Hedge Logic: Entra su SOL solo se SUI perde > 0.05$
            if mode == 'SHORT' and (pnl_trigger is None or pnl_trigger > -0.05):
                should_enter = False
                if limit_orders: # Se c'era un ordine di hedge pronto ma non serve più
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

                # TRAILING ENTRY: Qui aggiorniamo continuamente per inseguire il prezzo
                order_ok = False
                if limit_orders:
                    if len(limit_orders) > 1:
                        for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                    else:
                        current_order_px = float(limit_orders[0]['limitPx'])
                        # Se il prezzo si è spostato molto, aggiorna
                        if abs(current_order_px - target_entry) < (target_entry * 0.0005): 
                            order_ok = True
                        else:
                            # print(f"🔄 [{ticker}] Trailing Entry: {current_order_px} -> {target_entry}")
                            bot.exchange.cancel(ticker, limit_orders[0]['oid'])
                
                if not order_ok:
                    print(f"🔫 [{ticker}] Piazzo Limit {mode}: {amount} @ {target_entry}")
                    bot.exchange.order(ticker, is_buy_entry, amount, target_entry, {"limit": {"tif": "Gtc"}})
                    
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "reason": "Trailing Entry", "agent": AGENT_NAME})

    except Exception as e:
        print(f"Err Manage {ticker}: {e}")

def run_barry():
    print(f"⚔️ [Barry Stable] Avvio Trailing Entry + Static TP.")
    
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
