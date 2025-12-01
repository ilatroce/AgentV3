import sys
import os
import time
import pandas as pd
import traceback
import math
from dotenv import load_dotenv

# Import root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURAZIONE MM BARRY ---
AGENT_NAME = "Barry"
TICKER = "SOL"         
LOOP_SPEED = 15        

# Money Management
TOTAL_ALLOCATION_USD = 5.0  
LEVERAGE = 10               
GRID_LEVELS = 4             
GRID_STEP_PCT = 0.006       
STOP_LOSS_GRID_PCT = 0.04   

# --- CONFIGURAZIONE FILTRI VOLATILITÀ (GATEKEEPER) ---
# Se succede una di queste cose, Barry si ferma:
MAX_RVOL = 2.0         # Se il volume è > 2.0x (200%) della media -> STOP
MAX_CANDLE_SIZE = 0.01 # Se una candela si muove più dell'1% in 15m -> STOP

def get_grid_levels(center_price):
    levels = []
    for i in range(1, GRID_LEVELS + 1):
        price = center_price * (1 - (GRID_STEP_PCT * i))
        levels.append({"id": i, "price": price, "type": "BUY"})
    return levels

def check_market_conditions(df):
    """
    Ritorna True se il mercato è CALMO (Safe).
    Ritorna False se c'è Volatilità/Trend (Danger).
    """
    if df.empty or len(df) < 20: return True, "Dati insufficienti"

    # 1. Controllo Volume (RVOL)
    # Media volume ultime 20 candele
    avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
    curr_vol = df['volume'].iloc[-1]
    
    rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
    
    if rvol > MAX_RVOL:
        return False, f"Volume Spike rilevato (RVOL: {rvol:.2f}x)"

    # 2. Controllo Esplosione Prezzo (Big Candle)
    open_p = df['open'].iloc[-1]
    close_p = df['close'].iloc[-1]
    pct_move = abs(close_p - open_p) / open_p
    
    if pct_move > MAX_CANDLE_SIZE:
        return False, f"Movimento Impulsivo ({pct_move*100:.2f}%)"

    return True, "Mercato Consolidato (Safe)"

def run_barry():
    print(f"⚡ [Barry MM] Inizializzazione Market Maker su {TICKER}...")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    active_grid_orders = [] 

    while True:
        try:
            # 1. Scarica Dati
            candles = bot.get_candles(TICKER, interval="15m", limit=25)
            if candles.empty:
                time.sleep(5)
                continue
            
            current_price = float(candles.iloc[-1]['close'])
            
            # --- GATEKEEPER CHECK 🛡️ ---
            is_safe, market_status = check_market_conditions(candles)
            
            # Qui sta la differenza: NON usiamo 'continue'. Usiamo una variabile (flag).
            trading_is_allowed = True
            
            if not is_safe:
                print(f"⛔ [GATEKEEPER] Market ALERT: {market_status}. Blocco nuove entrate.")
                trading_is_allowed = False # Impediamo nuovi acquisti, ma il codice prosegue!
            
            # 2. Inizializzazione (Recupero posizione attuale)
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # Setup Centro Griglia (Solo se trading è permesso o abbiamo già posizioni da gestire)
            if not my_pos:
                if trading_is_allowed: # Resetta il centro solo se il mercato è calmo
                    if center_price is None or abs(current_price - center_price) / center_price > 0.01:
                        center_price = current_price
                        active_grid_orders = [] 
                        print(f"⚡ [Barry MM] Griglia resettata. Nuovo Centro: ${center_price:.4f}")
            else:
                if center_price is None:
                    center_price = float(my_pos['entry_price'])

            # Se siamo in PAUSA e non abbiamo posizioni, saltiamo il resto e dormiamo
            if not trading_is_allowed and not my_pos:
                print(f"   Prezzo: {current_price:.4f} | Nessuna posizione aperta. Attendo la calma.")
                time.sleep(15)
                continue

            # Se siamo qui, o il mercato è Safe, O abbiamo una posizione da gestire (anche se Unsafe)
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            print(f"\n⚡ [Barry MM] Safe: {is_safe} | P: {current_price:.4f} | PnL: ${pnl_usd:.2f}")

            # --- AZIONE 1: GRID BUY (Accumulo) ---
            # Questo lo facciamo SOLO se il Gatekeeper dice che è Safe
            if trading_is_allowed:
                levels = get_grid_levels(center_price)
                for lvl in levels:
                    if current_price <= lvl['price'] and lvl['id'] not in active_grid_orders:
                        print(f"⚡ [GRID] Buy Level {lvl['id']}")
                        bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                        
                        # bot.execute_order(TICKER, "LONG", bullet_size_usd) # Scommenta per LIVE
                        
                        active_grid_orders.append(lvl['id'])
                        payload = {
                            "operation": "OPEN", "symbol": TICKER, "direction": "LONG",
                            "reason": f"Grid Level {lvl['id']} Hit", "agent": AGENT_NAME,
                            "target_portion_of_balance": (bullet_size_usd/LEVERAGE)/float(account['balance_usd'])
                        }
                        db_utils.log_bot_operation(payload)
                        time.sleep(1)
            else:
                # Se il mercato è pericoloso, non compriamo nulla.
                pass

            # --- AZIONE 2: GRID SELL (Take Profit) ---
            # Questo lo lasciamo SEMPRE attivo. Se il prezzo rimbalza durante la tempesta, vendiamo!
            if my_pos: # Solo se abbiamo roba da vendere
                levels = get_grid_levels(center_price) # Ricalcoliamo i livelli basati sul centro vecchio
                for lvl_id in active_grid_orders[:]: 
                    # ... (codice identico a prima per la vendita) ...
                    # Qui copio la logica di vendita che avevamo:
                    lvl_price = next((l['price'] for l in levels if l['id'] == lvl_id), None)
                    if lvl_price:
                        take_profit_price = lvl_price * (1 + GRID_STEP_PCT)
                        if current_price >= take_profit_price:
                            print(f"⚡ [GRID] Profit Level {lvl_id} (Anche durante storm)!")
                            bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                            # bot.execute_order(TICKER, "SHORT", bullet_size_usd) 
                            active_grid_orders.remove(lvl_id)
                            # Log...

            # --- AZIONE 3: SAFETY STOP (CRUCIALE) ---
            # Questo DEVE essere eseguito SEMPRE, specialmente se il Gatekeeper è attivo!
            if my_pos and center_price:
                levels = get_grid_levels(center_price)
                stop_price = center_price * (1 - STOP_LOSS_GRID_PCT)
                
                # Se Gatekeeper è attivo (Tempesta), magari stringiamo lo stop loss?
                # Per ora lasciamolo standard:
                if current_price < stop_price:
                    print("⚡ [CRITICAL] STOP LOSS TOTALE ATTIVATO.")
                    # bot.close_position(TICKER) # CHIUDI TUTTO
                    
                    payload = {"operation": "CLOSE", "symbol": TICKER, "reason": "Grid Broken - Stop Loss", "pnl": pnl_usd, "agent": AGENT_NAME}
                    db_utils.log_bot_operation(payload)
                    center_price = None
                    active_grid_orders = []
                    time.sleep(60)

        except Exception as e:
            print(f"Errore MM: {e}")
            traceback.print_exc()
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
