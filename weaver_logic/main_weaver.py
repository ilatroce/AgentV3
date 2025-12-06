import sys
import os
import time
import traceback
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE WEAVER: LIQUIDITY PROVIDER 🕸️ ---
AGENT_NAME = "Weaver"
TICKER = "SUI"
LOOP_SPEED = 5  # Molto veloce

# Money Management
TOTAL_ALLOCATION = 50.0  
LEVERAGE = 10            # Leva bassa per sicurezza
SIZE_PER_ORDER = 15.0    # Ordini piccoli ma continui

# Strategia Spread
# Quanto vuoi guadagnare tra Buy e Sell?
# 0.2% è conservativo. 0.05% fa tantissimo volume ma rischia di più.
SPREAD_PCT = 0.002 # 0.2% spread totale (0.1% per lato)

def cancel_all_orders(bot):
    try:
        orders = bot.info.open_orders(bot.account.address)
        for o in orders:
            if o['coin'] == TICKER:
                bot.exchange.cancel(TICKER, o['oid'])
    except: pass

def run_weaver():
    print(f"🕸️ [Weaver] Avvio Market Making su {TICKER}.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Pulizia: Il Market Maker deve essere agile. 
            # Cancella i vecchi ordini prima di piazzare i nuovi (così segui il prezzo)
            cancel_all_orders(bot)

            # 2. Dati Mercato
            price = bot.get_market_price(TICKER)
            if price == 0: time.sleep(1); continue

            # 3. Gestione Inventario (Sbilanciamento)
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            
            pos_size = float(my_pos['size']) if my_pos else 0.0
            pos_side = my_pos['side'] if my_pos else "FLAT"
            
            # Calcolo prezzi Bid/Ask neutrali
            my_bid = price * (1 - (SPREAD_PCT / 2))
            my_ask = price * (1 + (SPREAD_PCT / 2))

            # --- SKEWING (Inclinazione) ---
            # Se siamo pieni di Long, vogliamo vendere di più e comprare di meno.
            # Abbassiamo entrambi i prezzi per favorire la vendita.
            skew = 0.0
            MAX_POS_USD = TOTAL_ALLOCATION * LEVERAGE
            current_notional = pos_size * price
            
            if current_notional > 0: # Siamo Long
                # Più siamo Long, più lo skew è negativo (abbassa i prezzi)
                skew = - (current_notional / MAX_POS_USD) * 0.002 
            elif current_notional < 0: # Siamo Short
                # Più siamo Short, più lo skew è positivo (alza i prezzi per ricomprare)
                skew = + (abs(current_notional) / MAX_POS_USD) * 0.002

            final_bid = round(my_bid * (1 + skew), 4)
            final_ask = round(my_ask * (1 + skew), 4)

            # Safety check: Non incrociare il mercato (Ask deve essere > Bid)
            if final_bid >= final_ask:
                final_ask = final_bid + 0.0002

            print(f"🕸️ P: {price:.4f} | Pos: {pos_side} {pos_size:.1f} | Bid: {final_bid} / Ask: {final_ask}")

            # 4. Piazzamento Ordini (Doppia canna)
            # Calcolo quantità
            qty_bid = round(SIZE_PER_ORDER / final_bid, 1)
            qty_ask = round(SIZE_PER_ORDER / final_ask, 1)

            # Se siamo troppo Long, non comprare altro (Quote Only)
            if pos_side == "LONG" and current_notional > (MAX_POS_USD * 0.8):
                print("   ⚠️ Max Long raggiunto. Solo Ask.")
            else:
                bot.exchange.order(TICKER, True, qty_bid, final_bid, {"limit": {"tif": "Alo"}})

            # Se siamo troppo Short, non vendere altro (Bid Only)
            if pos_side == "SHORT" and abs(current_notional) > (MAX_POS_USD * 0.8):
                print("   ⚠️ Max Short raggiunto. Solo Bid.")
            else:
                bot.exchange.order(TICKER, False, qty_ask, final_ask, {"limit": {"tif": "Alo"}})

        except Exception as e:
            print(f"Err Weaver: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_weaver()
