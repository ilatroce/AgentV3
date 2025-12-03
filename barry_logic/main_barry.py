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

# --- CONFIGURAZIONE BARRY: SAFE LONG ONLY 🛡️ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        

# Money Management
TOTAL_ALLOCATION = 25.0       
MAX_POSITIONS = 10            
LEVERAGE = 20                 

# Size per Slot
SIZE_PER_TRADE_USD = (TOTAL_ALLOCATION / MAX_POSITIONS) * LEVERAGE

# Strategia
BUY_OFFSET = 0.001   
TP_TARGET = 0.002    

def get_open_orders(bot, ticker):
    try:
        orders = bot.info.open_orders(bot.account.address)
        return [o for o in orders if o['coin'] == ticker]
    except: return []

def run_barry():
    print(f"⚡ [Barry Safe] Avvio su {TICKER} (Reduce-Only Mode).")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Recupera Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue
            
            # 2. Stato
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            open_orders = get_open_orders(bot, TICKER)
            
            buy_orders = [o for o in open_orders if o['side'] == 'B']
            sell_orders = [o for o in open_orders if o['side'] == 'A'] # Questi sono i TP
            
            # Dati Posizione
            pos_size_coin = float(my_pos['size']) if my_pos else 0.0
            entry_price = float(my_pos['entry_price']) if my_pos else 0.0
            
            # Calcolo Slot
            current_position_usd = pos_size_coin * current_price
            filled_slots = round(current_position_usd / SIZE_PER_TRADE_USD)
            pending_buy_slots = len(buy_orders)
            total_busy_slots = filled_slots + pending_buy_slots
            
            print(f"\n⚡ P: {current_price:.4f} | Slots: {total_busy_slots}/{MAX_POSITIONS} (Pos: {filled_slots}, Buy: {pending_buy_slots})")

            action_taken = False

            # --- FASE 1: TAKE PROFIT (Reduce Only) ---
            # Se abbiamo merce (pos_size > 0), dobbiamo avere un ordine di vendita che la copre.
            
            # Quantità già in vendita (TP attivi)
            size_in_sell_orders = sum(float(o['sz']) for o in sell_orders)
            
            # Quanta roba è "nuda" (senza TP)?
            uncovered_size = pos_size_coin - size_in_sell_orders
            
            # Se c'è roba scoperta (tolleranza 2$)
            if uncovered_size * current_price > 2.0:
                print(f"🛡️ [TP CHECK] Posizione scoperta: {uncovered_size:.2f} SUI")
                
                # Prezzo TP: Entry + Target
                tp_price = round(entry_price + TP_TARGET, 4)
                if tp_price <= current_price: tp_price = current_price * 1.002
                
                amount = round(uncovered_size, 1)
                
                if amount > 0:
                    print(f"   Piazzo LIMIT SELL (Reduce-Only): {amount} @ {tp_price}")
                    
                    # Usa il parametro "reduceOnly": True
                    # In Hyperliquid SDK grezzo si passa nelle opzioni
                    res = bot.exchange.order(TICKER, False, amount, tp_price, {"limit": {"tif": "Alo"}, "reduceOnly": True})
                    
                    if res['status'] == 'ok':
                        statuses = res.get('response', {}).get('data', {}).get('statuses', [{}])
                        if 'error' not in statuses[0]:
                            print("   ✅ TP Piazzato.")
                            action_taken = True
                        else:
                            print(f"   ❌ Errore TP: {statuses[0]}")

            # --- FASE 2: ACQUISTO (Buy Limit) ---
            if total_busy_slots < MAX_POSITIONS and not action_taken:
                
                target_buy_price = round(current_price - BUY_OFFSET, 4)
                
                too_close = False
                for o in buy_orders:
                    if abs(float(o['limitPx']) - target_buy_price) < 0.005:
                        too_close = True; break
                
                if not too_close:
                    amount = round(SIZE_PER_TRADE_USD / target_buy_price, 1)
                    
                    print(f"🔫 [BUY] Piazzo Limit Long: {amount} @ {target_buy_price}")
                    
                    res = bot.exchange.order(TICKER, True, amount, target_buy_price, {"limit": {"tif": "Alo"}})
                    
                    if res['status'] == 'ok':
                        statuses = res.get('response', {}).get('data', {}).get('statuses', [{}])
                        if 'error' not in statuses[0]:
                            db_utils.log_bot_operation({"operation": "OPEN", "symbol": TICKER, "direction": "LONG", "reason": "Maker Accumulation", "agent": AGENT_NAME})
                            action_taken = True
                else:
                    print(f"   Attesa: Ordine Buy già in zona.")

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
