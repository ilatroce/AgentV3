import sys

import os

import time

import traceback

from dotenv import load_dotenv



# Import root modules

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hyperliquid_trader import HyperLiquidTrader

import db_utils



load_dotenv()



# --- CONFIGURAZIONE WEAVER: SMART MM 🕸️ ---

AGENT_NAME = "Weaver"

TICKER = "SUI"

LOOP_SPEED = 5  



# Money Management

TOTAL_ALLOCATION = 50.0  

LEVERAGE = 10            

SIZE_PER_ORDER = 15.0    # Size standard



# Strategia Spread

BASE_SPREAD = 0.0005     # 0.2% Spread base

MIN_SPREAD = 0.0001      # 0.05% Spread minimo (per uscire veloci)



def cancel_all_orders(bot):

    try:

        # Usa account_address

        orders = bot.info.open_orders(bot.account_address)

        for o in orders:

            if o['coin'] == TICKER:

                bot.exchange.cancel(TICKER, o['oid'])

    except: pass



def run_weaver():

    print(f"🕸️ [Weaver Pro] Avvio Market Making su {TICKER}.")

    print(f"   Inventory Rescue: ATTIVO.")

    

    private_key = os.getenv("PRIVATE_KEY")

    wallet = os.getenv("WALLET_ADDRESS").lower()

    bot = HyperLiquidTrader(private_key, wallet, testnet=False)



    while True:

        try:

            # 1. Pulizia Totale (Il MM deve essere sempre fresco)

            cancel_all_orders(bot)



            # 2. Dati Mercato

            price = bot.get_market_price(TICKER)

            if price == 0: time.sleep(1); continue



            # 3. Analisi Inventario

            account = bot.get_account_status()

            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)

            

            pos_size = float(my_pos['size']) if my_pos else 0.0

            pos_side = my_pos['side'] if my_pos else "FLAT"

            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0

            

            # --- CALCOLO PREZZI BID/ASK DINAMICI ---

            

            # Default: Spread simmetrico attorno al prezzo attuale

            bid_price = price * (1 - (BASE_SPREAD / 2))

            ask_price = price * (1 + (BASE_SPREAD / 2))

            

            # LOGICA DI SALVATAGGIO (Skewing)

            # Se siamo esposti, spostiamo i prezzi per favorire l'uscita

            

            if pos_side == "LONG":

                # Siamo Long. Vogliamo VENDERE (Ask).

                # Avviciniamo l'Ask al prezzo attuale per uscire subito.

                # Allontaniamo il Bid per non comprare ancora.

                

                # Se stiamo perdendo soldi, panic mode: spread minimo

                if pnl_usd < 0:

                    ask_price = price * (1 + MIN_SPREAD) # Vendi appena sopra il market

                    bid_price = price * (1 - (BASE_SPREAD * 2)) # Compra molto sotto

                    print(f"🚨 [RESCUE LONG] PnL {pnl_usd:.2f}. Abbasso Ask a {ask_price:.4f}")

                else:

                    # Se siamo in profitto, skew normale

                    ask_price = price * (1 + (BASE_SPREAD / 4))

                    bid_price = price * (1 - BASE_SPREAD)



            elif pos_side == "SHORT":

                # Siamo Short. Vogliamo COMPRARE (Bid).

                # Alziamo il Bid per chiudere subito.

                

                if pnl_usd < 0:

                    bid_price = price * (1 - MIN_SPREAD) # Compra appena sotto il market

                    ask_price = price * (1 + (BASE_SPREAD * 2)) # Vendi molto sopra

                    print(f"🚨 [RESCUE SHORT] PnL {pnl_usd:.2f}. Alzo Bid a {bid_price:.4f}")

                else:

                    bid_price = price * (1 - (BASE_SPREAD / 4))

                    ask_price = price * (1 + BASE_SPREAD)



            # Arrotondamento SUI (4 decimali)

            bid_price = round(bid_price, 4)

            ask_price = round(ask_price, 4)

            

            # Safety: Non incrociare (Ask > Bid)

            if bid_price >= ask_price:

                ask_price = bid_price + 0.0002



            print(f"🕸️ P: {price:.4f} | {pos_side} {pos_size:.1f} (${pnl_usd:.2f}) | B: {bid_price} / A: {ask_price}")



            # 4. Piazzamento Ordini

            

            # Calcolo quantità ordini

            qty_bid = round(SIZE_PER_ORDER / bid_price, 1)

            qty_ask = round(SIZE_PER_ORDER / ask_price, 1)

            

            # Calcolo Limiti Esposizione (Max 80% del budget allocato)

            MAX_POS_USD = TOTAL_ALLOCATION * LEVERAGE

            current_notional = pos_size * price

            

            # Piazza BID (Se non siamo troppo Long)

            if not (pos_side == "LONG" and current_notional > (MAX_POS_USD * 0.8)):

                bot.exchange.order(TICKER, True, qty_bid, bid_price, {"limit": {"tif": "Alo"}})

            

            # Piazza ASK (Se non siamo troppo Short)

            if not (pos_side == "SHORT" and abs(current_notional) > (MAX_POS_USD * 0.8)):

                # Se siamo Long, la size di vendita deve essere almeno pari a quella che abbiamo per chiudere

                # Ma qui stiamo facendo MM, quindi piazziamo size standard. 

                # Se vogliamo chiudere tutto il blocco, aumentiamo la size.

                

                # Se siamo in Rescue Mode, vendiamo tutto quello che abbiamo

                if pos_side == "LONG" and pnl_usd < 0:

                    qty_ask = pos_size # Vendi tutto

                    

                bot.exchange.order(TICKER, False, qty_ask, ask_price, {"limit": {"tif": "Alo"}})

                

            # Caso speciale Rescue Short: Compra tutto per chiudere

            if pos_side == "SHORT" and pnl_usd < 0:

                 # Sovrascriviamo l'ordine bid piazzato sopra (o ne mettiamo uno specifico)

                 cancel_all_orders(bot) # Reset veloce

                 bot.exchange.order(TICKER, True, pos_size, bid_price, {"limit": {"tif": "Alo"}})



        except Exception as e:

            print(f"Err Weaver: {e}")

            time.sleep(5)

            

        time.sleep(LOOP_SPEED)



if __name__ == "__main__":

    run_weaver()
