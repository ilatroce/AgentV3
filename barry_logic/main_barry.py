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

# --- CONFIGURAZIONE BARRY: SINGLE SHOT HEDGER ⚔️ ---
AGENT_NAME = "Barry"
LOOP_SPEED = 15        

# Asset
TICKER_MAIN = "SUI"    # Long Strategy
TICKER_HEDGE = "SOL"   # Short Strategy

# Money Management
LEVERAGE = 20          
POSITION_SIZE_USD = 10.0 # 10$ a posizione

# Strategia
# SUI: Compra a -0.001, Vende a +0.002
SUI_OFFSET = 0.001   
SUI_TP = 0.002

# SOL: Shorta a +0.01, Chiude a -0.02
SOL_OFFSET = 0.01
SOL_TP = 0.02

def manage_asset(bot, ticker, mode, price, pnl_trigger=None):
    """
    Gestisce un singolo asset (SUI o SOL).
    mode: 'LONG' (per SUI) o 'SHORT' (per SOL)
    pnl_trigger: Se serve per attivare l'hedge (solo per SOL)
    """
    try:
        # 1. Analisi Stato
        account = bot.get_account_status()
        my_pos = next((p for p in account["open_positions"] if p["symbol"] == ticker), None)
        
        # Recupera ordini aperti
        orders = bot.info.open_orders(bot.account_address)
        my_orders = [o for o in orders if o['coin'] == ticker]
        
        # Separa Limit (Entry) da Trigger (TP)
        limit_orders = [o for o in my_orders if o['orderType'] == 'Limit']
        trigger_orders = [o for o in my_orders if 'trigger' in o['orderType']]

        # --- CASO A: ABBIAMO UNA POSIZIONE APERTA ---
        if my_pos:
            # 1. Pulizia: Non devono esserci ordini Limit (Entry) se siamo già dentro
            if limit_orders:
                print(f"🧹 [{ticker}] In posizione. Cancello ordini Limit superflui.")
                for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
            
            # 2. Gestione Take Profit (Trigger)
            # Dobbiamo avere ESATTAMENTE 1 Trigger Order corretto
            entry_px = float(my_pos['entry_price'])
            size = float(my_pos['size'])
            
            # Calcolo Prezzo TP
            if mode == 'LONG':
                target_px = round(entry_px + SUI_TP, 4)
                # Sicurezza: Se prezzo > target, il TP market scatta subito (bene)
                is_buy_close = False # Chiudo Long vendendo
            else: # SHORT
                target_px = round(entry_px - SOL_TP, 2) # SOL ha meno decimali
                is_buy_close = True # Chiudo Short comprando

            # Controlliamo se esiste già il TP corretto
            tp_exists = False
            for o in trigger_orders:
                # Tolleranza prezzo minima
                if abs(float(o['triggerPx']) - target_px) < (target_px * 0.001) and float(o['sz']) == size:
                    tp_exists = True
                else:
                    # Se c'è un TP vecchio o sbagliato, cancellalo
                    print(f"♻️ [{ticker}] Aggiorno TP (Vecchio: {o['triggerPx']} -> Nuovo: {target_px})")
                    bot.exchange.cancel(ticker, o['oid'])
            
            if not tp_exists:
                print(f"🛡️ [{ticker}] Piazzo Take Profit Trigger @ {target_px}")
                bot.place_take_profit(ticker, is_buy_close, size, target_px)

        # --- CASO B: SIAMO FLAT (NESSUNA POSIZIONE) ---
        else:
            # 1. Pulizia: Non devono esserci Trigger (TP) se siamo flat
            if trigger_orders:
                print(f"🧹 [{ticker}] Flat. Cancello Trigger orfani.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # 2. Logica di Entrata
            should_enter = True
            
            # Per SOL (Hedge), entriamo SOLO se SUI perde soldi (pnl_trigger < 0)
            if mode == 'SHORT' and (pnl_trigger is None or pnl_trigger > -0.05):
                should_enter = False
                # Se c'erano ordini pendenti di hedge, cancellali perché non servono più
                if limit_orders:
                    print(f"🟢 [{ticker}] Hedge non necessario. Cancello ordini.")
                    for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                return # Esci

            if should_enter:
                # Calcolo Target Entry
                if mode == 'LONG': # SUI
                    target_entry = round(price - SUI_OFFSET, 4)
                    is_buy_entry = True
                else: # SHORT (SOL)
                    target_entry = round(price + SOL_OFFSET, 2)
                    is_buy_entry = False

                # Calcolo Size
                amount = round(POSITION_SIZE_USD / target_entry, 1)

                # TRAILING ENTRY: Controlla se l'ordine esistente è "buono"
                order_ok = False
                if limit_orders:
                    # Ne teniamo solo 1, cancelliamo gli altri se ce ne sono troppi
                    if len(limit_orders) > 1:
                        for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                    else:
                        # Controlla se il prezzo è ancora valido
                        current_order_px = float(limit_orders[0]['limitPx'])
                        # Se la differenza è piccola, tienilo. Se è grande, sposta.
                        if abs(current_order_px - target_entry) < (target_entry * 0.0005): 
                            order_ok = True
                        else:
                            print(f"🔄 [{ticker}] Trailing Entry: {current_order_px} -> {target_entry}")
                            bot.exchange.cancel(ticker, limit_orders[0]['oid'])
                
                if not order_ok:
                    print(f"🔫 [{ticker}] Piazzo Limit {mode}: {amount} @ {target_entry}")
                    # Order normale GTC (Good till Cancel)
                    bot.exchange.order(ticker, is_buy_entry, amount, target_entry, {"limit": {"tif": "Gtc"}})
                    
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "reason": "Trailing Entry", "agent": AGENT_NAME})

    except Exception as e:
        print(f"Err Manage {ticker}: {e}")

def run_barry():
    print(f"⚔️ [Barry Smart] Avvio Trailing Entry + Native TP.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # Dati Mercato
            p_sui = bot.get_market_price(TICKER_MAIN)
            p_sol = bot.get_market_price(TICKER_HEDGE)
            if p_sui == 0 or p_sol == 0: time.sleep(5); continue

            # PnL Monitor per Hedge
            account = bot.get_account_status()
            pos_sui = next((p for p in account["open_positions"] if p["symbol"] == TICKER_MAIN), None)
            pnl_sui = float(pos_sui['pnl_usd']) if pos_sui else 0.0
            
            print(f"\n⚡ SUI: {p_sui} | SOL: {p_sol} | Hedge Trigger: {pnl_sui:.2f}")

            # 1. Gestisci SUI (Main)
            manage_asset(bot, TICKER_MAIN, 'LONG', p_sui)
            
            # 2. Gestisci SOL (Hedge - attivato dal pnl di SUI)
            manage_asset(bot, TICKER_HEDGE, 'SHORT', p_sol, pnl_trigger=pnl_sui)

        except Exception as e:
            print(f"Err Loop: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
