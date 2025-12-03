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

# --- CONFIGURAZIONE BARRY: ACCUMULATOR LEVERAGED ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        

# Money Management
TOTAL_ALLOCATION = 50.0       # Budget Totale Reale
MAX_POSITIONS = 10            # Numero massimo di slot
LEVERAGE = 20                 # LEVA 20x (Fondamentale!)

# Calcolo Size Nozionale per Slot
# 50$ / 10 = 5$ Reali -> x20 Leva = 100$ Nozionali a ordine (Ben sopra il limite minimo)
SIZE_PER_TRADE_USD = (TOTAL_ALLOCATION / MAX_POSITIONS) * LEVERAGE

# Strategia
BUY_OFFSET = 0.005   # Compra a -1 cent
TP_TARGET = 0.01    # Vendi a +2 cent

def get_open_orders(bot, ticker):
    try:
        orders = bot.info.open_orders(bot.account.address)
        return [o for o in orders if o['coin'] == ticker]
    except: return []

def run_barry():
    print(f"⚡ [Barry Accumulator] Avvio su {TICKER}.")
    print(f"   Slot: {MAX_POSITIONS} | Margin/Slot: ${TOTAL_ALLOCATION/MAX_POSITIONS:.2f}")
    print(f"   Order Size (Notional): ${SIZE_PER_TRADE_USD:.2f} (Leva {LEVERAGE}x)")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Recupera Prezzo
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue
            
            # 2. Analisi Slot
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            open_orders = get_open_orders(bot, TICKER)
            
            buy_orders = [o for o in open_orders if o['side'] == 'B']
            sell_orders = [o for o in open_orders if o['side'] == 'A']
            
            # Calcolo Slot Occupati
            current_position_notional = (float(my_pos['size']) * current_price) if my_pos else 0
            filled_slots = round(current_position_notional / SIZE_PER_TRADE_USD)
            pending_buy_slots = len(buy_orders)
            total_busy_slots = filled_slots + pending_buy_slots
            
            print(f"\n⚡ P: {current_price:.4f} | Slots: {total_busy_slots}/{MAX_POSITIONS} (Fill:{filled_slots} Pend:{pending_buy_slots})")

            action_taken = False

            # --- FASE 1: DIFESA (Piazza TP se manca) ---
            if my_pos and not action_taken:
                pos_size = float(my_pos['size'])
                sell_orders_size = sum(float(o['sz']) for o in sell_orders)
                uncovered_size = pos_size - sell_orders_size
                
                # Se c'è posizione scoperta > 2$ (tolleranza)
                if uncovered_size * current_price > 2.0:
                    print(f"🛡️ [DEFENSE] Posizione scoperta: {uncovered_size:.1f} {TICKER}")
                    
                    entry_px = float(my_pos['entry_price'])
                    tp_price = round(entry_px + TP_TARGET, 4)
                    if tp_price <= current_price: tp_price = current_price * 1.005
                    
                    amount = round(uncovered_size, 1) # Arrotondamento SUI
                    
                    if amount > 0:
                        print(f"   Piazzo TP LIMIT SELL: {amount} @ {tp_price}")
                        # Forza Limit Maker (Alo = Add Liquidity Only)
                        res = bot.exchange.order(TICKER, False, amount, tp_price, {"limit": {"tif": "Alo"}})
                        print(f"   Risposta: {res}")
                        
                        if res['status'] == 'ok':
                            # Verifichiamo se dentro 'response' c'è un errore nascosto
                            statuses = res.get('response', {}).get('data', {}).get('statuses', [{}])
                            if 'error' not in statuses[0]:
                                db_utils.log_bot_operation({"operation": "CLOSE_PARTIAL", "symbol": TICKER, "reason": "TP Set", "agent": AGENT_NAME})
                                action_taken = True
                            else:
                                print(f"   ❌ Errore API: {statuses[0]}")

            # --- FASE 2: ATTACCO (Accumulo) ---
            if total_busy_slots < MAX_POSITIONS and not action_taken:
                
                target_buy_price = round(current_price - BUY_OFFSET, 4)
                
                # Check duplicati
                too_close = False
                for o in buy_orders:
                    if abs(float(o['limitPx']) - target_buy_price) < 0.005:
                        too_close = True; break
                
                if not too_close:
                    amount = round(SIZE_PER_TRADE_USD / target_buy_price, 1) # Arrotondamento SUI
                    
                    print(f"🔫 [ATTACK] Slot libero! Piazzo BUY: {amount} @ {target_buy_price}")
                    
                    # Usa "Alo" (Post-Only) per garantire di essere Maker
                    res = bot.exchange.order(TICKER, True, amount, target_buy_price, {"limit": {"tif": "Alo"}})
                    print(f"   Risposta: {res}")
                    
                    if res['status'] == 'ok':
                        statuses = res.get('response', {}).get('data', {}).get('statuses', [{}])
                        if 'error' not in statuses[0]:
                            db_utils.log_bot_operation({"operation": "OPEN", "symbol": TICKER, "direction": "LONG", "reason": "Maker Buy", "agent": AGENT_NAME})
                            action_taken = True
                        else:
                            print(f"   ❌ Errore API: {statuses[0]}")
                else:
                    print(f"   Attesa: Ordine già presente in zona.")

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
