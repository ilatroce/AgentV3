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

# --- CONFIGURAZIONE BARRY: SIMPLE MAKER ACCUMULATOR ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        # Controllo ogni 15 secondi

# Money Management
TOTAL_ALLOCATION = 50.0       # Budget Totale
MAX_POSITIONS = 10            # Numero massimo di "slot" (posizioni contemporanee)
SIZE_PER_TRADE = TOTAL_ALLOCATION / MAX_POSITIONS # 5$ a trade

# Strategia di Prezzo (Valori Assoluti)
BUY_OFFSET = 0.01   # Compra 1 centesimo SOTTO il prezzo attuale
TP_TARGET = 0.02    # Vendi 2 centesimi SOPRA il prezzo di entrata

def get_open_orders(bot, ticker):
    """Recupera gli ordini Limit aperti su Hyperliquid"""
    try:
        orders = bot.info.open_orders(bot.account.address)
        return [o for o in orders if o['coin'] == ticker]
    except: return []

def run_barry():
    print(f"⚡ [Barry Accumulator] Avvio su {TICKER}.")
    print(f"   Budget: ${TOTAL_ALLOCATION} ({MAX_POSITIONS} slots da ${SIZE_PER_TRADE})")
    print(f"   Strat: Buy @ -{BUY_OFFSET}$ | Sell @ +{TP_TARGET}$")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Recupera Prezzo e Stato
            current_price = bot.get_market_price(TICKER)
            if current_price == 0: time.sleep(5); continue
            
            # Recupera posizioni e ordini pendenti
            account = bot.get_account_status()
            # La posizione su HL è aggregata (netta). 
            # Barry deve gestire "virtualmente" i suoi slot se HL aggrega tutto.
            # MA, se usiamo ordini Limit di TP, HL li gestisce nel book.
            
            # Per semplificare la logica "10 slot", guardiamo quanti ordini di BUY sono aperti
            # e quanta posizione abbiamo già in pancia.
            
            my_pos = next((p for p in account["open_positions"] if p["symbol"] == TICKER), None)
            open_orders = get_open_orders(bot, TICKER)
            
            # Conta gli ordini di acquisto pendenti
            buy_orders = [o for o in open_orders if o['side'] == 'B']
            sell_orders = [o for o in open_orders if o['side'] == 'A']
            
            # Calcola quanti slot sono occupati
            # Slot occupati = (Soldi investiti nella posizione / 5$) + (Ordini di acquisto pendenti)
            current_position_usd = (float(my_pos['size']) * current_price) if my_pos else 0
            
            # Arrotondiamo per capire quanti "pacchetti" da 5$ abbiamo
            filled_slots = round(current_position_usd / SIZE_PER_TRADE)
            pending_buy_slots = len(buy_orders)
            
            total_busy_slots = filled_slots + pending_buy_slots
            
            print(f"\n⚡ P: {current_price:.4f} | Slots: {total_busy_slots}/{MAX_POSITIONS} (Pos: {filled_slots}, Pending Buy: {pending_buy_slots})")

            action_taken = False # Flag per fare solo 1 azione a giro

            # --- FASE 1: PIAZZARE TAKE PROFIT (Priorità assoluta) ---
            # Se abbiamo una posizione aperta, dobbiamo assicurarci che ci sia un ordine di vendita (TP).
            # Se la posizione è grande (es. 3 slot), dobbiamo avere ordini di vendita equivalenti.
            
            # Calcolo semplice: Se abbiamo posizione ma NON abbiamo abbastanza ordini di vendita, piazziamo TP.
            if my_pos and not action_taken:
                pos_size = float(my_pos['size'])
                # Somma della size di tutti gli ordini di vendita aperti
                sell_orders_size = sum(float(o['sz']) for o in sell_orders)
                
                # Se c'è della posizione "scoperta" (senza TP)
                uncovered_size = pos_size - sell_orders_size
                
                # Tolleranza minima (per evitare ordini di polvere)
                if uncovered_size > (SIZE_PER_TRADE / current_price * 0.5):
                    print(f"🛡️ [DEFENSE] Trovata posizione scoperta di {uncovered_size:.2f} {TICKER}.")
                    
                    # Calcolo prezzo TP: Entry Price medio + 0.02$
                    # Nota: Entry Price medio cambia se compriamo a prezzi diversi (DCA).
                    # Per uscire in profitto globale, usiamo Entry Price + TP.
                    entry_px = float(my_pos['entry_price'])
                    tp_price = round(entry_px + TP_TARGET, 4)
                    
                    # Se il prezzo attuale è già sopra il TP (improbabile ma possibile), vendi subito un po' sopra
                    if tp_price <= current_price:
                        tp_price = current_price * 1.005 # +0.5% sopra market
                    
                    # Arrotonda quantità
                    amount = round(uncovered_size, 1)
                    
                    if amount > 0:
                        print(f"   Piazzo TP LIMIT SELL: {amount} @ {tp_price}")
                        res = bot.exchange.order(TICKER, False, amount, tp_price, {"limit": {"tif": "Gtc"}})
                        
                        if res['status'] == 'ok':
                            payload = {"operation": "CLOSE_PARTIAL", "symbol": TICKER, "reason": "TP Placement", "agent": AGENT_NAME}
                            db_utils.log_bot_operation(payload)
                            action_taken = True

            # --- FASE 2: PIAZZARE NUOVI ACQUISTI (Accumulo) ---
            # Solo se abbiamo slot liberi e non abbiamo fatto altre azioni
            if total_busy_slots < MAX_POSITIONS and not action_taken:
                
                # Calcolo Prezzo Maker: Attuale - 0.01$
                # Per essere sicuri di essere Maker e non Taker, stiamo un filo sotto il Bid.
                target_buy_price = round(current_price - BUY_OFFSET, 4)
                
                # Controllo anti-spam: C'è già un ordine vicino a questo prezzo?
                # Se ho già un ordine a 1.50 e il prezzo è 1.51 (target 1.50), non ne metto un altro uguale.
                too_close = False
                for o in buy_orders:
                    open_px = float(o['limitPx'])
                    if abs(open_px - target_buy_price) < 0.005: # Se c'è un ordine entro mezzo centesimo
                        too_close = True
                        break
                
                if not too_close:
                    amount = round(SIZE_PER_TRADE / target_buy_price, 1)
                    print(f"🔫 [ATTACK] Slot libero! Piazzo LIMIT BUY: {amount} @ {target_buy_price}")
                    
                    res = bot.exchange.order(TICKER, True, amount, target_buy_price, {"limit": {"tif": "Gtc"}})
                    
                    if res['status'] == 'ok':
                        payload = {"operation": "OPEN", "symbol": TICKER, "direction": "LONG", "reason": "Maker Accumulation", "agent": AGENT_NAME}
                        db_utils.log_bot_operation(payload)
                        action_taken = True
                else:
                    print(f"   Attesa: Ordine di acquisto già presente in zona ${target_buy_price}.")

            # --- FASE 3: PULIZIA (Opzionale) ---
            # Se il prezzo è scappato via (es. è salito molto), i vecchi ordini di acquisto sono inutili e occupano slot?
            # Per ora teniamoli ("Fishing"), magari crolla e li prende.
            # Se però il prezzo sale di 10 centesimi, quegli ordini sono lontanissimi.
            
            # Se non abbiamo fatto nulla, dormiamo.
            if not action_taken:
                print("   Nessuna azione necessaria.")

        except Exception as e:
            print(f"Err Barry: {e}")
            traceback.print_exc()
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
