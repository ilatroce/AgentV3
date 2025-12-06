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
    print(f"🕸️ [Weaver Pro] Avvio Market Making Smart su {TICKER}.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    # Variabili per tracciare gli ordini locali ed evitare chiamate API inutili
    # (In una versione avanzata useremmo i websocket, qui semplifichiamo)
    
    while True:
        try:
            # 1. Dati Mercato (Li prendiamo PRIMA di decidere se cancellare)
            price = bot.get_market_price(TICKER)
            if price == 0: 
                time.sleep(1)
                continue

            # 2. Analisi Inventario
            account = bot.get_account_status()
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            
            pos_size = float(my_pos['size']) if my_pos else 0.0
            pos_side = my_pos['side'] if my_pos else "FLAT"
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            entry_price = float(my_pos['entry_px']) if my_pos else 0.0

            # --- CALCOLO PREZZI TARGET ---
            
            # Default
            target_bid = price * (1 - (BASE_SPREAD / 2))
            target_ask = price * (1 + (BASE_SPREAD / 2))

            # SKEWING LOGIC (Migliorata per il profitto)
            if pos_side == "LONG":
                # Se siamo in profitto, NON stringere troppo lo spread altrimenti l'ordine scappa.
                # Mantieni un spread sano per farti fillare.
                if pnl_usd > 0:
                    # Logica: Vendi a Entry + Spread desiderato, oppure Market + Spread
                    # Qui usiamo Market + Spread intero (non diviso per 4) per dare tempo al fill
                    target_ask = price * (1 + (BASE_SPREAD * 0.8)) 
                    target_bid = price * (1 - BASE_SPREAD) # Comprane altri solo molto più in basso
                else:
                    # Panic Mode (Perdita): Uscita rapida
                    target_ask = price * (1 + MIN_SPREAD)
                    target_bid = price * (1 - (BASE_SPREAD * 2))
                    print(f"🚨 [RESCUE LONG] PnL {pnl_usd:.2f}. Ask stretto.")

            elif pos_side == "SHORT":
                if pnl_usd > 0:
                    target_bid = price * (1 - (BASE_SPREAD * 0.8))
                    target_ask = price * (1 + BASE_SPREAD)
                else:
                    # Panic Mode
                    target_bid = price * (1 - MIN_SPREAD)
                    target_ask = price * (1 + (BASE_SPREAD * 2))
                    print(f"🚨 [RESCUE SHORT] PnL {pnl_usd:.2f}. Bid stretto.")

            # Arrotondamento
            target_bid = round(target_bid, 4)
            target_ask = round(target_ask, 4)
            
            # Safety anti-incrocio
            if target_bid >= target_ask:
                target_ask = target_bid + 0.0002

            print(f"🕸️ P: {price:.4f} | {pos_side} {pos_size:.1f} (${pnl_usd:.2f}) | Target B: {target_bid} / A: {target_ask}")

            # --- 3. SMART ORDER MANAGEMENT (Il cuore della modifica) ---
            
            current_orders = bot.info.open_orders(bot.account_address)
            my_ticker_orders = [o for o in current_orders if o['coin'] == TICKER]
            
            # Flag per sapere se dobbiamo piazzare nuovi ordini
            place_bid = True
            place_ask = True
            
            # Tolleranza: se il prezzo vecchio è entro lo 0.05% del nuovo target, NON cancellare
            TOLERANCE = 0.0005 

            for o in my_ticker_orders:
                o_price = float(o['limit_px'])
                o_side = o['side'] # 'B' o 'A'
                o_oid = o['oid']

                if o_side == 'B': # Ordine BUY esistente
                    # Se il prezzo è simile al target, tienilo (risparmi API e tieni priorità)
                    if abs(o_price - target_bid) / target_bid < TOLERANCE:
                        place_bid = False # Abbiamo già un ordine buono
                    else:
                        # Prezzo troppo diverso, cancella questo ordine vecchio
                        bot.exchange.cancel(TICKER, o_oid)
                
                elif o_side == 'A': # Ordine SELL esistente
                    # Se siamo LONG e vogliamo uscire, siamo meno tolleranti se il prezzo scende,
                    # ma se il prezzo sale (target_ask sale), vogliamo aggiornare.
                    if abs(o_price - target_ask) / target_ask < TOLERANCE:
                        place_ask = False
                    else:
                        bot.exchange.cancel(TICKER, o_oid)

            # --- 4. PIAZZAMENTO ORDINI (Solo se necessario) ---
            
            # Calcolo Limiti
            MAX_POS_USD = TOTAL_ALLOCATION * LEVERAGE
            current_notional = pos_size * price

            # Piazza BID solo se non ne abbiamo già uno valido
            if place_bid:
                qty_bid = round(SIZE_PER_ORDER / target_bid, 1)
                # Filtro esposizione Long
                if not (pos_side == "LONG" and current_notional > (MAX_POS_USD * 0.8)):
                    # Rescue Short: compra tutto
                    if pos_side == "SHORT" and pnl_usd < 0: qty_bid = pos_size
                    
                    bot.exchange.order(TICKER, True, qty_bid, target_bid, {"limit": {"tif": "Alo"}})
            
            # Piazza ASK solo se non ne abbiamo già uno valido
            if place_ask:
                qty_ask = round(SIZE_PER_ORDER / target_ask, 1)
                # Filtro esposizione Short
                if not (pos_side == "SHORT" and abs(current_notional) > (MAX_POS_USD * 0.8)):
                    # Rescue Long: vendi tutto
                    if pos_side == "LONG" and pnl_usd < 0: qty_ask = pos_size
                    
                    bot.exchange.order(TICKER, False, qty_ask, target_ask, {"limit": {"tif": "Alo"}})

        except Exception as e:
            print(f"Err Weaver: {e}")
            traceback.print_exc() # Utile per vedere l'errore completo
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_weaver()
