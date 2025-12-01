import sys
import os
import time
import pandas as pd
import traceback
import math
from dotenv import load_dotenv

# Import root modules (per trovare db_utils e trader)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE BARRY: MACHINE GUN MODE 🔫 ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 5         # Controllo ogni 5 secondi (Alta Frequenza)

# Money Management
TOTAL_ALLOCATION_USD = 5.0   # Capitale Reale usato dal wallet
LEVERAGE = 20                # LEVA 20x (Impostala su Hyperliquid!)
GRID_LEVELS = 50             # 50 Linee di acquisto
GRID_RANGE_PCT = 0.04        # Copriamo il 4% di discesa

# Calcolo Step Fisso: 4% / 50 livelli = 0.08% a scalino (ogni ~0.001$)
STEP_PCT = GRID_RANGE_PCT / GRID_LEVELS 

# Gatekeeper (Sicurezza Volatilità)
MAX_RVOL = 3.0           # Stop se volume > 3x la media
MAX_CANDLE_SIZE = 0.008  # Stop se candela > 0.8% in 1 minuto

def get_grid_levels(center_price):
    """Genera i 50 livelli di prezzo sotto il centro."""
    levels = []
    for i in range(1, GRID_LEVELS + 1):
        price = center_price * (1 - (STEP_PCT * i))
        levels.append({"id": i, "price": price})
    return levels

def check_market_conditions(df):
    """
    Ritorna True se il mercato è SAFE.
    Ritorna False se c'è un crollo/pump violento.
    """
    if df.empty or len(df) < 20: return True, "Dati insuff."

    # 1. Filtro Volume (RVOL)
    avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
    curr_vol = df['volume'].iloc[-1]
    rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
    
    if rvol > MAX_RVOL:
        return False, f"Volume Extreme ({rvol:.1f}x)"

    # 2. Filtro Velocity (Dimensione Candela)
    open_p = df['open'].iloc[-1]
    close_p = df['close'].iloc[-1]
    pct_move = abs(close_p - open_p) / open_p
    
    if pct_move > MAX_CANDLE_SIZE:
        return False, f"Impulse Move ({pct_move*100:.2f}%)"

    return True, "Safe"

def run_barry():
    print(f"🔫 [Barry MachineGun] Avvio su {TICKER}. {GRID_LEVELS} Livelli (Step {STEP_PCT*100:.2f}%).")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    active_grid_orders = [] 
    
    while True:
        try:
            # 1. Dati Veloci (1m per reattività massima)
            candles = bot.get_candles(TICKER, interval="1m", limit=25)
            if candles.empty:
                time.sleep(2); continue
            
            current_price = float(candles.iloc[-1]['close'])
            
            # --- GATEKEEPER CHECK 🛡️ ---
            is_safe, market_status = check_market_conditions(candles)
            
            # Se è Safe, permettiamo nuovi acquisti. Se no, solo vendite/chiusure.
            trading_is_allowed = True if is_safe else False
            
            if not is_safe: 
                print(f"⛔ [GATEKEEPER] PAUSA BUY: {market_status}")

            # 2. Gestione Posizioni
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # --- LOGICA CENTRO GRIGLIA ---
            if not my_pos:
                # Se siamo Flat, resettiamo il centro se il mercato è calmo (trading allowed)
                # Oppure se il prezzo si è spostato troppo dal vecchio centro vuoto
                if trading_is_allowed:
                    if center_price is None or abs(current_price - center_price) / center_price > STEP_PCT:
                        center_price = current_price
                        active_grid_orders = [] 
            else:
                # Se abbiamo posizione, il centro è ANCORATO all'entry price
                if center_price is None: center_price = float(my_pos['entry_price'])

            # Calcolo PnL per logica
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0

            # --- AZIONE 1: GRID BUY (Accumulo) ---
            # Eseguiamo solo se il Gatekeeper dice che è sicuro
            if trading_is_allowed and center_price:
                levels = get_grid_levels(center_price)
                
                for lvl in levels:
                    # Se il prezzo tocca il livello E non l'abbiamo comprato
                    if current_price <= lvl['price'] and lvl['id'] not in active_grid_orders:
                        print(f"🔫 [BUY] Lvl {lvl['id']} @ {lvl['price']:.4f}")
                        
                        # Size del Proiettile (con Leva)
                        bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                        
                        # ESECUZIONE REALE (Scommenta quando pronto)
                        # bot.execute_order(TICKER, "LONG", bullet_size_usd) 
                        
                        active_grid_orders.append(lvl['id'])
                        
                        payload = {
                            "operation": "OPEN", "symbol": TICKER, "direction": "LONG",
                            "reason": f"Grid Lvl {lvl['id']}", 
                            "agent": AGENT_NAME,
                            # Calcoliamo % allocazione reale per info
                            "target_portion_of_balance": (bullet_size_usd/LEVERAGE)/float(account.get('balance_usd', 1))
                        }
                        db_utils.log_bot_operation(payload)
                        # Niente sleep lungo, vogliamo velocità a raffica se serve

            # --- AZIONE 2: GRID SELL (Scalping Micro) ---
            # Sempre attivo (anche durante tempesta per prendere profitto sui rimbalzi)
            if my_pos and center_price:
                levels = get_grid_levels(center_price)
                for lvl_id in active_grid_orders[:]: 
                    # Troviamo il prezzo originale di acquisto di quel livello
                    lvl_price = next((l['price'] for l in levels if l['id'] == lvl_id), None)
                    
                    if lvl_price:
                        # Take Profit: Appena risale di 1 Step sopra il prezzo di acquisto
                        take_profit_price = lvl_price * (1 + STEP_PCT)
                        
                        if current_price >= take_profit_price:
                            print(f"💎 [PROFIT] Lvl {lvl_id} incassato!")
                            
                            bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                            
                            # ESECUZIONE REALE (Scommenta quando pronto)
                            # bot.execute_order(TICKER, "SHORT", bullet_size_usd) 
                            
                            active_grid_orders.remove(lvl_id)
                            
                            # Profitto stimato dello scalino
                            step_profit = bullet_size_usd * STEP_PCT
                            payload = {
                                "operation": "CLOSE_PARTIAL", "symbol": TICKER, "agent": AGENT_NAME,
                                "reason": "Micro Scalp", 
                                "pnl": step_profit # Fondamentale per Dashboard
                            }
                            db_utils.log_bot_operation(payload)

            # --- AZIONE 3: SAFETY NET (Stop Loss Totale) ---
            # Se il prezzo esce dal range massimo (4% + 1% buffer)
            if my_pos and center_price:
                stop_price = center_price * (1 - GRID_RANGE_PCT - 0.01) 
                if current_price < stop_price:
                    print("💀 [STOP] Fuori Range massimo. CHIUDO TUTTO.")
                    
                    # ESECUZIONE REALE (Scommenta quando pronto)
                    # bot.close_position(TICKER) 
                    
                    payload = {
                        "operation": "CLOSE", "symbol": TICKER, 
                        "reason": "Grid Broken - Stop Loss", 
                        "pnl": pnl_usd, # Registra la perdita reale
                        "agent": AGENT_NAME
                    }
                    db_utils.log_bot_operation(payload)
                    
                    # Reset Totale
                    center_price = None
                    active_grid_orders = []
                    time.sleep(10) # Pausa respiro
            
            # Reset logico se la posizione è stata chiusa esternamente (o TP totale)
            if not my_pos and len(active_grid_orders) > 0:
                active_grid_orders = []
                center_price = None

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(2)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
