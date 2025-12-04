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

# --- CONFIGURAZIONE BARRY: SMART HEDGER v2 🧠 ---
AGENT_NAME = "Barry"
LOOP_SPEED = 10        

# Asset
TICKER_MAIN = "SUI"    # Long
TICKER_HEDGE = "SOL"   # Short

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 

# Strategia
SUI_BUY_OFFSET = 0.001   
SUI_TP_TARGET = 0.02     

SOL_SELL_OFFSET = 0.01   
SOL_TP_TARGET = 0.02     

# --- NUOVO: SAFETY PARAMETERS ---
MAX_COMBINED_LOSS = -1.0 # Se perdiamo > 1$ in totale, intervenire
HEDGE_TRIGGER_LOSS = -0.50 # Attiva SOL solo se SUI perde > 0.50$

def get_open_orders(bot, ticker):
    try:
        orders = bot.info.open_orders(bot.account.address)
        return [o for o in orders if o['coin'] == ticker]
    except: return []

def cancel_orders(bot, ticker):
    try:
        orders = get_open_orders(bot, ticker)
        for o in orders:
            bot.exchange.cancel(ticker, o['oid'])
    except: pass

def run_barry():
    print(f"⚔️ [Barry SmartHedge] Avvio. Cut The Loser Logic.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # Dati Mercato
            p_sui = bot.get_market_price(TICKER_MAIN)
            p_sol = bot.get_market_price(TICKER_HEDGE)
            if p_sui == 0 or p_sol == 0: time.sleep(5); continue

            # Stato Account
            account = bot.get_account_status()
            pos_sui = next((p for p in account["open_positions"] if p["symbol"] == TICKER_MAIN), None)
            pos_sol = next((p for p in account["open_positions"] if p["symbol"] == TICKER_HEDGE), None)
            
            # PnL Monitor
            pnl_sui = float(pos_sui['pnl_usd']) if pos_sui else 0.0
            pnl_sol = float(pos_sol['pnl_usd']) if pos_sol else 0.0
            total_pnl = pnl_sui + pnl_sol
            
            print(f"\n⚡ Tot PnL: ${total_pnl:.2f} | SUI: ${pnl_sui:.2f} | SOL: ${pnl_sol:.2f}")

            # --- LOGICA 0: DEAD ZONE KILLER (Cut the Loser) ---
            # Se stiamo perdendo complessivamente troppo...
            if total_pnl < MAX_COMBINED_LOSS:
                print(f"💀 [EMERGENCY] Perdita totale eccessiva (${total_pnl:.2f}). Taglio la gamba peggiore.")
                
                # Chi è il colpevole?
                if pnl_sui < pnl_sol:
                    # SUI sta perdendo più di SOL -> Chiudi SUI
                    print(f"✂️ Taglio SUI (Loser). Mantengo Hedge.")
                    bot.close_position(TICKER_MAIN)
                    cancel_orders(bot, TICKER_MAIN)
                    # Nota: Rimaniamo solo con SOL short aperto.
                else:
                    # SOL sta perdendo più di SUI -> Chiudi SOL
                    print(f"✂️ Taglio SOL (Hedge fallito). Spero nel rimbalzo SUI.")
                    bot.close_position(TICKER_HEDGE)
                    cancel_orders(bot, TICKER_HEDGE)
                
                time.sleep(5)
                continue

            # --- LOGICA 1: GESTIONE SUI (MAIN) ---
            orders_sui = get_open_orders(bot, TICKER_MAIN)
            
            if pos_sui:
                # Se abbiamo posizione, assicuriamoci di avere TP
                if not any(o['side'] == 'A' for o in orders_sui):
                    tp = round(float(pos_sui['entry_price']) + SUI_TP_TARGET, 4)
                    if tp <= p_sui: tp = p_sui * 1.001
                    print(f"🔵 [SUI] TP Set @ {tp}")
                    bot.exchange.order(TICKER_MAIN, False, float(pos_sui['size']), tp, {"limit": {"tif": "Alo"}, "reduceOnly": True})
            else:
                # Se siamo Flat, piazza Entry Buy
                if not any(o['side'] == 'B' for o in orders_sui):
                    target = round(p_sui - SUI_BUY_OFFSET, 4)
                    amt = round(POSITION_SIZE_USD / target, 1)
                    print(f"🔵 [SUI] Entry Limit @ {target}")
                    bot.exchange.order(TICKER_MAIN, True, amt, target, {"limit": {"tif": "Alo"}})

            # --- LOGICA 2: GESTIONE SOL (HEDGE DINAMICO) ---
            orders_sol = get_open_orders(bot, TICKER_HEDGE)
            
            if pos_sol:
                # Se abbiamo Hedge aperto, gestiamo TP
                if not any(o['side'] == 'B' for o in orders_sol):
                    tp = round(float(pos_sol['entry_price']) - SOL_TP_TARGET, 2)
                    if tp >= p_sol: tp = p_sol * 0.999
                    print(f"🔴 [SOL] TP Hedge @ {tp}")
                    bot.exchange.order(TICKER_HEDGE, True, float(pos_sol['size']), tp, {"limit": {"tif": "Alo"}, "reduceOnly": True})
                
                # Uscita Intelligente dall'Hedge:
                # Se SUI è tornato in positivo, l'Hedge non serve più! Chiudilo (anche in pari o leggera perdita).
                if pnl_sui > 0.10: 
                    print(f"🟢 [SOL] SUI recuperato! Chiudo Hedge non necessario.")
                    bot.close_position(TICKER_HEDGE)
                    cancel_orders(bot, TICKER_HEDGE)

            else:
                # Se non abbiamo Hedge... ci serve?
                # Attiva SOLO se SUI perde più della soglia (es. -0.50$)
                if pnl_sui < HEDGE_TRIGGER_LOSS:
                    if not any(o['side'] == 'A' for o in orders_sol):
                        target = round(p_sol + SOL_SELL_OFFSET, 2)
                        amt = round(POSITION_SIZE_USD / target, 2)
                        print(f"🔴 [SOL] ATTIVAZIONE HEDGE @ {target}")
                        bot.exchange.order(TICKER_HEDGE, False, amt, target, {"limit": {"tif": "Alo"}})
                else:
                    # Se SUI va bene, cancella ordini hedge pendenti per pulizia
                    if orders_sol: cancel_orders(bot, TICKER_HEDGE)

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
