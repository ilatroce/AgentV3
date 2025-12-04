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

# --- CONFIGURAZIONE BARRY: HEDGING GRINDER (SUI + SOL) ⚔️ ---
AGENT_NAME = "Barry"
LOOP_SPEED = 5         # Controllo veloce

# Asset
TICKER_MAIN = "SUI"    # Asset Principale (Long Scalp)
TICKER_HEDGE = "SOL"   # Asset Copertura (Short Scalp)

# Money Management
LEVERAGE = 20          # Leva 20x
POSITION_SIZE_USD = 10.0 # Valore Nozionale (10$ totali = 0.50$ margine)

# Strategia SUI (Long)
SUI_BUY_OFFSET = 0.001   # Compra a -0.001$ dal prezzo
SUI_TP_TARGET = 0.002    # Vendi a +0.002$ dall'entry

# Strategia SOL (Short Hedge)
SOL_SELL_OFFSET = 0.01   # Shorta a +0.01$ dal prezzo
SOL_TP_TARGET = 0.02     # Chiudi short a +0.02$ (ovvero prezzo -0.02$)

def get_open_orders(bot, ticker):
    try:
        orders = bot.info.open_orders(bot.account.address)
        return [o for o in orders if o['coin'] == ticker]
    except: return []

def cancel_orders(bot, ticker):
    """Cancella tutti gli ordini su un ticker"""
    try:
        orders = get_open_orders(bot, ticker)
        for o in orders:
            bot.exchange.cancel(ticker, o['oid'])
    except: pass

def run_barry():
    print(f"⚔️ [Barry Hedge] Avvio su {TICKER_MAIN} (Main) & {TICKER_HEDGE} (Hedge).")
    print(f"   Size: ${POSITION_SIZE_USD} | Leva: {LEVERAGE}x")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Recupera Prezzi e Stato
            price_sui = bot.get_market_price(TICKER_MAIN)
            price_sol = bot.get_market_price(TICKER_HEDGE)
            
            if price_sui == 0 or price_sol == 0:
                time.sleep(2); continue

            account = bot.get_account_status()
            
            # Trova Posizioni
            pos_sui = next((p for p in account["open_positions"] if p["symbol"] == TICKER_MAIN), None)
            pos_sol = next((p for p in account["open_positions"] if p["symbol"] == TICKER_HEDGE), None)
            
            # PnL di SUI (Serve per attivare SOL)
            sui_pnl = float(pos_sui['pnl_usd']) if pos_sui else 0.0
            
            print(f"\n⚡ SUI: {price_sui:.4f} (PnL ${sui_pnl:.2f}) | SOL: {price_sol:.2f}")

            # --- LOGICA A: GESTIONE SUI (Main Loop) ---
            # Obiettivo: Avere sempre 1 Long aperto o in apertura.
            
            orders_sui = get_open_orders(bot, TICKER_MAIN)
            
            if not pos_sui:
                # NESSUNA POSIZIONE -> PIAZZA BUY ORDER
                # Cerchiamo se c'è già un ordine di acquisto pendente
                buy_exists = any(o['side'] == 'B' for o in orders_sui)
                
                if not buy_exists:
                    print(f"🔵 [SUI] Flat. Piazzo Limit Buy.")
                    # Cancella eventuali vecchi sell residui
                    cancel_orders(bot, TICKER_MAIN)
                    
                    target_price = round(price_sui - SUI_BUY_OFFSET, 4)
                    amount = round(POSITION_SIZE_USD / target_price, 1)
                    
                    bot.exchange.order(TICKER_MAIN, True, amount, target_price, {"limit": {"tif": "Alo"}})
                    
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": TICKER_MAIN, "direction": "LONG", "reason": "Cycle Start", "agent": AGENT_NAME})
            
            else:
                # POSIZIONE APERTA -> GESTISCI TAKE PROFIT
                # Se siamo Long, dobbiamo avere un ordine di vendita (TP)
                sell_exists = any(o['side'] == 'A' for o in orders_sui)
                
                if not sell_exists:
                    entry_px = float(pos_sui['entry_price'])
                    tp_price = round(entry_px + SUI_TP_TARGET, 4)
                    size_to_sell = float(pos_sui['size'])
                    
                    # Sicurezza: TP deve essere sopra il prezzo attuale (Maker)
                    if tp_price <= price_sui: tp_price = price_sui * 1.001
                    
                    print(f"🔵 [SUI] Long attivo. Piazzo TP @ {tp_price}")
                    bot.exchange.order(TICKER_MAIN, False, size_to_sell, tp_price, {"limit": {"tif": "Alo"}, "reduceOnly": True})


            # --- LOGICA B: GESTIONE SOL (Hedge Loop) ---
            # Obiettivo: Aprire Short SOLO se SUI è in rosso.
            
            orders_sol = get_open_orders(bot, TICKER_HEDGE)
            
            # Condizione Attivazione: SUI in perdita (es. < -0.05$ per evitare rumore)
            # O se abbiamo già una posizione SOL aperta da gestire
            hedging_needed = (sui_pnl < -0.01) # Se SUI perde più di 1 centesimo
            
            if not pos_sol:
                # SIAMO FLAT SU SOL
                if hedging_needed:
                    # Controlla se c'è già ordine short pendente
                    short_exists = any(o['side'] == 'A' for o in orders_sol)
                    
                    if not short_exists:
                        print(f"🔴 [SOL] SUI soffre. Attivo Hedge Short.")
                        cancel_orders(bot, TICKER_HEDGE)
                        
                        target_price = round(price_sol + SOL_SELL_OFFSET, 2) # SOL ha meno decimali
                        amount = round(POSITION_SIZE_USD / target_price, 2)
                        
                        # Limit Sell (Short)
                        bot.exchange.order(TICKER_HEDGE, False, amount, target_price, {"limit": {"tif": "Alo"}})
                        
                        db_utils.log_bot_operation({"operation": "OPEN", "symbol": TICKER_HEDGE, "direction": "SHORT", "reason": "Hedge Activation", "agent": AGENT_NAME})
                else:
                    # Se non serve hedging e non abbiamo posizioni, puliamo ordini vecchi
                    if orders_sol:
                        print(f"🟢 [SOL] SUI ok. Cancello ordini Hedge inutilizzati.")
                        cancel_orders(bot, TICKER_HEDGE)

            else:
                # POSIZIONE SOL APERTA -> GESTISCI TAKE PROFIT
                # Dobbiamo chiudere lo short in profitto
                buy_back_exists = any(o['side'] == 'B' for o in orders_sol)
                
                if not buy_back_exists:
                    entry_px = float(pos_sol['entry_price'])
                    # Short TP: Prezzo Entry - Target
                    tp_price = round(entry_px - SOL_TP_TARGET, 2)
                    size_to_cover = float(pos_sol['size'])
                    
                    if tp_price >= price_sol: tp_price = price_sol * 0.999
                    
                    print(f"🔴 [SOL] Short attivo. Piazzo TP @ {tp_price}")
                    # Buy Limit Reduce-Only
                    bot.exchange.order(TICKER_HEDGE, True, size_to_cover, tp_price, {"limit": {"tif": "Alo"}, "reduceOnly": True})

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
