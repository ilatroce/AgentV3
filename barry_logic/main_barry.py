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

# --- CONFIGURAZIONE BARRY: TAKER ACCUMULATOR (SUI) ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        # 15 Secondi

# Money Management
TOTAL_ALLOCATION = 50.0       
MAX_POSITIONS = 10            
LEVERAGE = 20                 

# Size per Slot (Nozionale)
# 50$ / 10 = 5$ Reali -> x20 = 100$ Nozionali
SIZE_PER_TRADE_USD = (TOTAL_ALLOCATION / MAX_POSITIONS) * LEVERAGE

# Strategia (Prezzi Assoluti per SUI)
BUY_OFFSET = 0.01   # Compra ogni volta che scende di 1 cent
TP_TARGET = 0.02    # Vendi quando sei in profitto di 2 cent sul prezzo medio

def run_barry():
    print(f"⚡ [Barry Taker] Avvio su {TICKER}. Mode: MARKET ORDERS.")
    print(f"   Size per trade: ${SIZE_PER_TRADE_USD:.2f}")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    last_buy_price = None

    while True:
        try:
            # 1. Dati Mercato
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue
            
            # 2. Dati Posizione
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            
            # --- SICUREZZA ANTI-SHORT ---
            if my_pos and my_pos['side'] == 'SHORT':
                print("🚨 [ALLARME] Trovata posizione SHORT! Chiudo subito.")
                bot.close_position(TICKER)
                time.sleep(2); continue

            # Dati utili
            pos_size_coin = float(my_pos['size']) if my_pos else 0.0
            entry_price = float(my_pos['entry_price']) if my_pos else 0.0
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            
            # Calcolo Slot Usati
            current_notional = pos_size_coin * current_price
            slots_used = round(current_notional / SIZE_PER_TRADE_USD)
            
            print(f"\n⚡ P: {current_price:.4f} | Avg Entry: {entry_price:.4f} | Slot: {slots_used}/{MAX_POSITIONS}")

            action_taken = False

            # --- AZIONE 1: TAKE PROFIT (Vendi tutto o una parte) ---
            if my_pos and current_price >= (entry_price + TP_TARGET):
                print(f"💰 [TAKE PROFIT] Prezzo {current_price} > Target {entry_price + TP_TARGET:.4f}")
                
                sell_size_usd = SIZE_PER_TRADE_USD
                max_sell_usd = pos_size_coin * current_price * 0.99 
                
                if sell_size_usd > max_sell_usd:
                    sell_size_usd = max_sell_usd 
                
                if max_sell_usd < 10.0: 
                    print("   Chiusura totale (rimanenza bassa).")
                    bot.close_position(TICKER)
                else:
                    print(f"   Vendita Parziale (Market): ${sell_size_usd:.2f}")
                    bot.execute_order(TICKER, "SHORT", sell_size_usd)
                
                payload = {"operation": "CLOSE_PARTIAL", "symbol": TICKER, "reason": "Taker TP", "pnl": pnl_usd / slots_used if slots_used > 0 else 0, "agent": AGENT_NAME}
                db_utils.log_bot_operation(payload)
                
                last_buy_price = current_price 
                action_taken = True
                time.sleep(2)

            # --- AZIONE 2: BUY THE DIP (Accumulo) ---
            if not action_taken and slots_used < MAX_POSITIONS:
                
                should_buy = False
                
                # Caso A: Prima entrata
                if not my_pos:
                    should_buy = True
                    print("🆕 Prima entrata.")
                
                # Caso B: Mediare (DCA)
                else:
                    reference_price = last_buy_price if last_buy_price else entry_price
                    if current_price <= (reference_price - BUY_OFFSET):
                        should_buy = True
                        print(f"📉 Dip rilevato (-{BUY_OFFSET}).")

                if should_buy:
                    print(f"🔫 [BUY] Market Order: ${SIZE_PER_TRADE_USD:.2f}")
                    bot.execute_order(TICKER, "LONG", SIZE_PER_TRADE_USD)
                    
                    last_buy_price = current_price
                    
                    payload = {"operation": "OPEN", "symbol": TICKER, "direction": "LONG", "reason": "Taker Buy", "agent": AGENT_NAME, "target_portion_of_balance": 0.01}
                    db_utils.log_bot_operation(payload)
                    time.sleep(2)

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
