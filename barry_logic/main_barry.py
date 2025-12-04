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

# --- CONFIGURAZIONE BARRY: STRICT HEDGER (SUI + SOL) ⚔️ ---
AGENT_NAME = "Barry"
LOOP_SPEED = 10        # Rallentato a 10s per dare tempo alle API

# Asset
TICKER_MAIN = "SUI"    # Long
TICKER_HEDGE = "SOL"   # Short

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 

# Strategia
SUI_BUY_OFFSET = 0.001   # Entry: Prezzo - 0.001
SUI_TP_TARGET = 0.02     # Exit: Entry + 0.02

SOL_SELL_OFFSET = 0.01   # Entry Hedge: Prezzo + 0.01
SOL_TP_TARGET = 0.02     # Exit Hedge: Entry - 0.02

def get_orders(bot, ticker):
    """Ritorna (buy_orders, sell_orders) liste"""
    try:
        orders = bot.info.open_orders(bot.account.address)
        my_orders = [o for o in orders if o['coin'] == ticker]
        buys = [o for o in my_orders if o['side'] == 'B']
        sells = [o for o in my_orders if o['side'] == 'A']
        return buys, sells
    except: return [], []

def cancel_list(bot, ticker, order_list):
    """Cancella una lista specifica di ordini"""
    for o in order_list:
        print(f"🧹 [CLEANUP] Cancello ordine superfluo {o['oid']} su {ticker}")
        bot.exchange.cancel(ticker, o['oid'])
        time.sleep(0.1)

def run_barry():
    print(f"⚔️ [Barry Strict] Avvio. Max 1 Ordine per Asset.")
    
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
            
            # Ordini Pendenti
            sui_buys, sui_sells = get_orders(bot, TICKER_MAIN)
            sol_buys, sol_sells = get_orders(bot, TICKER_HEDGE)

            # PnL Monitor
            pnl_sui = float(pos_sui['pnl_usd']) if pos_sui else 0.0
            pnl_sol = float(pos_sol['pnl_usd']) if pos_sol else 0.0
            
            print(f"\n⚡ SUI: {p_sui} (PnL {pnl_sui:.2f}) | SOL: {p_sol} (PnL {pnl_sol:.2f})")

            # ==========================================
            # LOGICA SUI (MAIN - LONG STRATEGY)
            # ==========================================
            if pos_sui:
                # --- STATO: IN POSIZIONE ---
                # Regola: DEVE esserci 1 SELL (TP). ZERO BUY.
                
                # 1. Pulizia Buy errati
                if sui_buys: cancel_list(bot, TICKER_MAIN, sui_buys)
                
                # 2. Controllo TP (Sell)
                if not sui_sells:
                    entry = float(pos_sui['entry_price'])
                    size = float(pos_sui['size'])
                    tp_price = round(entry + SUI_TP_TARGET, 4)
                    if tp_price <= p_sui: tp_price = p_sui * 1.001 # Maker fix
                    
                    print(f"🔵 [SUI] Piazzamento TP Maker: {size} @ {tp_price}")
                    bot.exchange.order(TICKER_MAIN, False, size, tp_price, {"limit": {"tif": "Alo"}, "reduceOnly": True})
                else:
                    # Se c'è già più di 1 ordine sell, è un errore -> resetta
                    if len(sui_sells) > 1:
                        cancel_list(bot, TICKER_MAIN, sui_sells)
            else:
                # --- STATO: FLAT ---
                # Regola: DEVE esserci 1 BUY (Entry). ZERO SELL.
                
                # 1. Pulizia Sell errati
                if sui_sells: cancel_list(bot, TICKER_MAIN, sui_sells)
                
                # 2. Controllo Entry (Buy)
                if not sui_buys:
                    target = round(p_sui - SUI_BUY_OFFSET, 4)
                    amount = round(POSITION_SIZE_USD / target, 1)
                    print(f"🔵 [SUI] Piazzamento Entry: {amount} @ {target}")
                    bot.exchange.order(TICKER_MAIN, True, amount, target, {"limit": {"tif": "Alo"}})
                else:
                    if len(sui_buys) > 1: cancel_list(bot, TICKER_MAIN, sui_buys)

            # ==========================================
            # LOGICA SOL (HEDGE - SHORT STRATEGY)
            # ==========================================
            # Attivazione Hedge: Se SUI perde > 0.05$ (tolleranza rumore)
            hedge_active = (pnl_sui < -0.05)
            
            if pos_sol:
                # --- STATO: IN HEDGE ---
                # Regola: DEVE esserci 1 BUY (TP Chiudi Short). ZERO SELL.
                
                # 1. Pulizia Sell (Entry Short) errati
                if sol_sells: cancel_list(bot, TICKER_HEDGE, sol_sells)
                
                # 2. Controllo TP (Buy Back)
                if not sol_buys:
                    entry = float(pos_sol['entry_price'])
                    size = float(pos_sol['size'])
                    # Target Short: Entry - Target
                    tp_price = round(entry - SOL_TP_TARGET, 2)
                    if tp_price >= p_sol: tp_price = p_sol * 0.999
                    
                    print(f"🔴 [SOL] Piazzamento TP Hedge: {size} @ {tp_price}")
                    bot.exchange.order(TICKER_HEDGE, True, size, tp_price, {"limit": {"tif": "Alo"}, "reduceOnly": True})
                else:
                    if len(sol_buys) > 1: cancel_list(bot, TICKER_HEDGE, sol_buys)
            
            else:
                # --- STATO: FLAT (HEDGE OFF/WAITING) ---
                
                # Se non serve Hedge -> Pulizia totale e Basta
                if not hedge_active:
                    if sol_buys or sol_sells:
                        print("🟢 [SOL] Hedge non richiesto. Pulisco ordini.")
                        cancel_list(bot, TICKER_HEDGE, sol_buys + sol_sells)
                
                # Se serve Hedge -> Piazza Entry Short
                else:
                    # Regola: DEVE esserci 1 SELL (Entry Short). ZERO BUY.
                    if sol_buys: cancel_list(bot, TICKER_HEDGE, sol_buys)
                    
                    if not sol_sells:
                        target = round(p_sol + SOL_SELL_OFFSET, 2)
                        amount = round(POSITION_SIZE_USD / target, 2)
                        print(f"🔴 [SOL] Piazzamento Hedge Short: {amount} @ {target}")
                        bot.exchange.order(TICKER_HEDGE, False, amount, target, {"limit": {"tif": "Alo"}})
                    else:
                        if len(sol_sells) > 1: cancel_list(bot, TICKER_HEDGE, sol_sells)

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
