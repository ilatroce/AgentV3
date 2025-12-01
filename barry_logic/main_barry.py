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

# --- CONFIGURAZIONE MM BARRY (HYPER-ACTIVE MODE) ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 10        # Controllo ogni 10 secondi (Più veloce!)

# Money Management
TOTAL_ALLOCATION_USD = 5.0  
LEVERAGE = 10               
GRID_LEVELS = 5        # Aumentiamo a 5 livelli per coprire più range
STOP_LOSS_GRID_PCT = 0.03   # Stop Loss più stretto (3%) dato che facciamo scalping veloce

# Gatekeeper (Sicurezza)
MAX_RVOL = 2.5         # Tolleranza leggermente più alta per lasciarlo lavorare

def calculate_dynamic_step(df):
    """
    Calcola lo step della griglia basandosi sulla volatilità recente (ATR).
    Se il mercato è piatto, stringe la griglia per fare scalping.
    """
    if df.empty or len(df) < 15: return 0.003 # Default 0.3%

    # Calcolo ATR Semplificato su 14 periodi
    high_low = df['high'] - df['low']
    atr = high_low.rolling(window=14).mean().iloc[-1]
    current_price = df['close'].iloc[-1]
    
    # ATR in percentuale rispetto al prezzo
    atr_pct = atr / current_price
    
    # Lo step ideale è spesso metà dell'ATR per catturare il rumore
    dynamic_step = atr_pct * 0.8
    
    # Limiti di sicurezza (Clamp)
    # Minimo 0.15% (Scalping estremo) - Massimo 1.0% (Mercato volatile)
    return max(0.0015, min(dynamic_step, 0.01))

def get_grid_levels(center_price, step_pct):
    levels = []
    for i in range(1, GRID_LEVELS + 1):
        price = center_price * (1 - (step_pct * i))
        levels.append({"id": i, "price": price, "type": "BUY"})
    return levels

def check_market_conditions(df):
    if df.empty or len(df) < 20: return True, "Dati insuff."
    
    # RVOL Check
    avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
    curr_vol = df['volume'].iloc[-1]
    rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
    
    if rvol > MAX_RVOL:
        return False, f"Volume Spike ({rvol:.1f}x)"
        
    return True, "Safe"

def run_barry():
    print(f"⚡ [Barry Hyper] Avvio su {TICKER}. Modalità Dinamica ATR.")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    active_grid_orders = [] 
    
    # Variabile per ricordare lo step attuale (per non cambiarlo mentre siamo in posizione)
    current_grid_step = 0.003 

    while True:
        try:
            # 1. Scarica Dati (15m per analisi macro, 1m per prezzo veloce potrebbe servire ma ATR su 15m è più stabile)
            candles = bot.get_candles(TICKER, interval="15m", limit=30)
            if candles.empty:
                time.sleep(5)
                continue
            
            current_price = float(candles.iloc[-1]['close'])
            
            # Calcolo Step Dinamico
            calculated_step = calculate_dynamic_step(candles)
            
            # Gatekeeper
            is_safe, market_status = check_market_conditions(candles)
            trading_is_allowed = True if is_safe else False
            
            if not is_safe:
                print(f"⛔ [GATEKEEPER] PAUSA: {market_status}")

            # 2. Gestione Posizioni
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # --- LOGICA CENTRO GRIGLIA ---
            if not my_pos:
                # Se siamo Flat, aggiorniamo lo step alla volatilità attuale
                current_grid_step = calculated_step
                
                # Resettiamo il centro se il prezzo si è mosso troppo dal vecchio centro
                if center_price is None or abs(current_price - center_price) / center_price > (current_grid_step * 0.5):
                    # Reset Aggressivo: Il centro diventa quasi il prezzo attuale per entrare subito
                    # Mettiamo il centro leggermente sopra il prezzo attuale così il Livello 1 è vicinissimo
                    center_price = current_price * (1 + (current_grid_step * 0.2))
                    active_grid_orders = [] 
                    # print(f"⚡ [RESET] Nuovo Centro: {center_price:.4f} | Step Dinamico: {current_grid_step*100:.2f}%")
            else:
                if center_price is None: center_price = float(my_pos['entry_price'])
                # Nota: NON cambiamo lo step mentre siamo in posizione per coerenza matematica

            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            
            # Stampa Stato Compatta
            print(f"⚡ P: {current_price:.4f} | C: {center_price:.4f} | Step: {current_grid_step*100:.2f}% | Lvl Attivi: {len(active_grid_orders)}")

            # --- AZIONE 1: GRID BUY ---
            if trading_is_allowed:
                levels = get_grid_levels(center_price, current_grid_step)
                
                for lvl in levels:
                    # Logica Aggressiva: Se tocchiamo il livello O siamo sotto
                    if current_price <= lvl['price'] and lvl['id'] not in active_grid_orders:
                        print(f"⚡ [BUY] Livello {lvl['id']} @ {lvl['price']:.4f}")
                        
                        bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                        # bot.execute_order(TICKER, "LONG", bullet_size_usd) # Scommenta per LIVE
                        
                        active_grid_orders.append(lvl['id'])
                        
                        payload = {
                            "operation": "OPEN", "symbol": TICKER, "direction": "LONG",
                            "reason": f"Grid Lvl {lvl['id']} (Step {current_grid_step*100:.2f}%)", 
                            "agent": AGENT_NAME,
                            "target_portion_of_balance": (bullet_size_usd/LEVERAGE)/float(account['balance_usd'])
                        }
                        db_utils.log_bot_operation(payload)
                        time.sleep(1)

            # --- AZIONE 2: GRID SELL (Scalping Uscita) ---
            if my_pos:
                levels = get_grid_levels(center_price, current_grid_step)
                for lvl_id in active_grid_orders[:]: 
                    lvl_price = next(l['price'] for l in levels if l['id'] == lvl_id)
                    
                    # Take Profit: Appena risale di 1 Step
                    take_profit_price = lvl_price * (1 + current_grid_step)
                    
                    if current_price >= take_profit_price:
                        print(f"⚡ [PROFIT] Livello {lvl_id} incassato!")
                        
                        bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LEVELS
                        # bot.execute_order(TICKER, "SHORT", bullet_size_usd) # Scommenta per LIVE
                        
                        active_grid_orders.remove(lvl_id)
                        
                        step_profit = bullet_size_usd * current_grid_step
                        payload = {
                            "operation": "CLOSE_PARTIAL", "symbol": TICKER, "agent": AGENT_NAME,
                            "reason": "Grid Scalp Profit", "pnl": step_profit
                        }
                        db_utils.log_bot_operation(payload)

            # --- AZIONE 3: SAFETY STOP ---
            if my_pos and center_price:
                stop_price = center_price * (1 - STOP_LOSS_GRID_PCT)
                if current_price < stop_price:
                    print("⚡ [STOP] Chiusura emergenza.")
                    # bot.close_position(TICKER) 
                    
                    payload = {"operation": "CLOSE", "symbol": TICKER, "reason": "Stop Loss", "pnl": pnl_usd, "agent": AGENT_NAME}
                    db_utils.log_bot_operation(payload)
                    center_price = None
                    active_grid_orders = []
                    time.sleep(30)
            
            # Reset se posizione chiusa esternamente
            if not my_pos and len(active_grid_orders) > 0:
                active_grid_orders = []
                center_price = None

        except Exception as e:
            print(f"Errore: {e}")
            traceback.print_exc()
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
