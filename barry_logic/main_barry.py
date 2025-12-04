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

POSITION_SIZE_USD = 20.0 # 10$ a posizione



# Strategia

# SUI: Compra a -0.001, Vende a +0.002

SUI_OFFSET = 0.001   

SUI_TP = 0.003



# SOL: Shorta a +0.01, Chiude a -0.02

SOL_OFFSET = 0.07

SOL_TP = 0.22



def manage_asset(bot, ticker, mode, price, pnl_trigger=None):

    """

    Gestisce un singolo asset (SUI o SOL) con FIX per 'orderType'.

    """

    try:

        # 1. Analisi Stato

        account = bot.get_account_status()

        my_pos = next((p for p in account["open_positions"] if p["symbol"] == ticker), None)

        

        # Recupera ordini aperti

        # FIX: Usa account_address

        orders = bot.info.open_orders(bot.account_address)

        my_orders = [o for o in orders if o['coin'] == ticker]

        

        # --- FIX ROBUSTEZZA ORDINI ---

        limit_orders = []

        trigger_orders = []

        

        for o in my_orders:

            # Hyperliquid ritorna 'orderType' o 'type'. Cerchiamo di capire cos'è.

            o_type = o.get('orderType', o.get('type', 'Limit'))

            

            # Se è un dizionario (es. {'trigger': ...}), lo convertiamo in stringa per controllo

            if isinstance(o_type, dict):

                if 'trigger' in o_type:

                    trigger_orders.append(o)

                else:

                    limit_orders.append(o) # Assumiamo Limit se non è trigger

            elif 'trigger' in str(o_type).lower():

                trigger_orders.append(o)

            else:

                limit_orders.append(o)

        # -----------------------------



        # --- CASO A: ABBIAMO UNA POSIZIONE APERTA ---

        if my_pos:

            # 1. Pulizia: Non devono esserci ordini Limit (Entry) se siamo già dentro

            if limit_orders:

                print(f"🧹 [{ticker}] In posizione. Cancello ordini Limit superflui.")

                # for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])

            

            # 2. Gestione Take Profit (Trigger)

            entry_px = float(my_pos['entry_price'])

            size = float(my_pos['size'])

            

            # Calcolo Prezzo TP

            if mode == 'LONG':

                target_px = round(entry_px + SUI_TP, 4)

                is_buy_close = False 

            else: # SHORT

                target_px = round(entry_px - SOL_TP, 2) 

                is_buy_close = True 



            # Controlliamo se esiste già il TP corretto

            tp_exists = False

            for o in trigger_orders:

                # Per i trigger orders, il prezzo è in 'triggerPx'

                trig_px = float(o.get('triggerPx', o.get('limitPx', 0)))

                

                if abs(trig_px - target_px) < (target_px * 0.001) and float(o['sz']) == size:

                    tp_exists = True

                else:

                    print(f"♻️ [{ticker}] Aggiorno TP (Vecchio: {trig_px} -> Nuovo: {target_px})")

                    # bot.exchange.cancel(ticker, o['oid'])

            

            if not tp_exists:

                print(f"🛡️ [{ticker}] Piazzo Take Profit Trigger @ {target_px}")

                # Assicurati che place_take_profit esista in hyperliquid_trader.py!

                bot.place_take_profit(ticker, is_buy_close, size, target_px)



        # --- CASO B: SIAMO FLAT ---

        else:

            if trigger_orders:

                print(f"🧹 [{ticker}] Flat. Cancello Trigger orfani.")

                # for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])



            should_enter = True

            

            # Hedge Logic

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

                            print(f"🔄 [{ticker}] Trailing Entry: {current_order_px} -> {target_entry}")

                            bot.exchange.cancel(ticker, limit_orders[0]['oid'])

                

                if not order_ok:

                    print(f"🔫 [{ticker}] Piazzo Limit {mode}: {amount} @ {target_entry}")

                    bot.exchange.order(ticker, is_buy_entry, amount, target_entry, {"limit": {"tif": "Gtc"}})
                    bot.place_take_profit(ticker, is_buy_close, size, target_px)

                    

                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "reason": "Trailing Entry", "agent": AGENT_NAME})



    except Exception as e:

        print(f"Err Manage {ticker}: {e}")

        # traceback.print_exc() # Scommenta per debug profondo



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
