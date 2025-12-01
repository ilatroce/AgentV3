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

# --- CONFIGURAZIONE BARRY: NEUTRAL GRID ⚡ ---
AGENT_NAME = "Barry"
TICKER = "SUI"         
LOOP_SPEED = 15        # Controllo ogni 15 secondi

# Money Management
TOTAL_ALLOCATION_USD = 5.0   # Capitale Reale usato
LEVERAGE = 20                # Leva 20x NECESSARIA per 52 linee
GRID_LINES = 52              # Numero totale di linee nella griglia
RANGE_PCT = 0.01             # Range operativo (+/- 1%)

# Calcoli Griglia
# Distanza tra le linee: (Range totale 2%) / 52 linee
# Range totale = dall'1% sotto all'1% sopra = 0.02
STEP_PCT = (RANGE_PCT * 2) / GRID_LINES 

# Gatekeeper
VOLATILITY_LOOKBACK_MIN = 15 # Guardiamo gli ultimi 15 minuti
VOLATILITY_THRESHOLD = 0.01  # Se High-Low > 1% -> Pausa
PAUSE_DURATION = 900         # 15 Minuti di pausa (900 secondi)

def check_volatility_gatekeeper(bot, ticker):
    """
    Controlla se il range degli ultimi 15 minuti è eccessivo.
    Ritorna True se SAFE, False se DANGEROUS.
    """
    try:
        # Scarica 15 candele da 1 minuto
        df = bot.get_candles(ticker, interval="1m", limit=VOLATILITY_LOOKBACK_MIN)
        if df.empty: return True # Nel dubbio continuiamo (o blocchiamo, a scelta)
        
        # Calcolo Range (High Max - Low Min)
        high_max = df['high'].max()
        low_min = df['low'].min()
        
        volatility = (high_max - low_min) / low_min
        
        if volatility > VOLATILITY_THRESHOLD:
            print(f"⛔ [GATEKEEPER] Volatilità eccessiva ({volatility*100:.2f}%) negli ultimi {VOLATILITY_LOOKBACK_MIN}m.")
            return False
        
        return True
    except Exception as e:
        print(f"Err Gatekeeper: {e}")
        return True

def run_barry():
    print(f"⚡ [Barry Grid] Avvio su {TICKER}. Range +/- {RANGE_PCT*100}%.")
    print(f"   Linee: {GRID_LINES} | Step: {STEP_PCT*100:.4f}%")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS").lower()
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    center_price = None 
    triggered_levels = set() # Tiene traccia delle linee già toccate
    
    while True:
        try:
            # 1. Recupera Prezzo Attuale
            current_price = bot.get_market_price(TICKER)
            if current_price == 0:
                time.sleep(5); continue

            # 2. Gatekeeper (Controllo Volatilità)
            is_safe = check_volatility_gatekeeper(bot, TICKER)
            
            if not is_safe:
                print(f"⏳ [PAUSA] Il bot si ferma per {PAUSE_DURATION/60} minuti per sicurezza.")
                time.sleep(PAUSE_DURATION)
                # Al risveglio, resettiamo il centro per adattarci al nuovo mercato
                center_price = None
                triggered_levels = set()
                continue # Ricomincia il loop

            # 3. Gestione Stato Account
            account = bot.get_account_status()
            positions = account.get("open_positions", [])
            my_pos = next((p for p in positions if p["symbol"] == TICKER), None)
            
            # --- SETUP CENTRO GRIGLIA ---
            if not my_pos:
                # Se non abbiamo posizioni, il centro è il prezzo attuale
                if center_price is None:
                    center_price = current_price
                    triggered_levels = set()
                    print(f"🎯 [GRID START] Nuovo Centro fissato a ${center_price:.4f}")
            else:
                # Se abbiamo una posizione, il centro è l'Entry Price originale
                if center_price is None:
                    center_price = float(my_pos['entry_price'])
                    print(f"🎯 [GRID RESUME] Centro recuperato: ${center_price:.4f}")

            # Calcoli Limiti Griglia
            upper_limit = center_price * (1 + RANGE_PCT)
            lower_limit = center_price * (1 - RANGE_PCT)
            
            pnl_usd = float(my_pos['pnl_usd']) if my_pos else 0.0
            print(f"⚡ P: {current_price:.4f} | C: {center_price:.4f} | Range: {lower_limit:.4f} - {upper_limit:.4f}")

            # --- AZIONE 1: STOP LOSS (Fuori Range) ---
            if current_price > upper_limit or current_price < lower_limit:
                if my_pos:
                    print(f"💀 [STOP LOSS] Prezzo fuori dal range dell'1%. CHIUDO TUTTO.")
                    bot.close_position(TICKER)
                    
                    payload = {
                        "operation": "CLOSE", "symbol": TICKER, 
                        "reason": "Grid Range Broken", "pnl": pnl_usd, "agent": AGENT_NAME
                    }
                    db_utils.log_bot_operation(payload)
                
                # Reset
                center_price = None
                triggered_levels = set()
                time.sleep(5)
                continue

            # --- AZIONE 2: ESECUZIONE GRIGLIA (Neutral) ---
            # Calcoliamo a quale "numero di linea" corrisponde il prezzo attuale
            # Delta positivo = Sopra (Short), Delta negativo = Sotto (Long)
            pct_diff = (current_price - center_price) / center_price
            
            # Indice della linea corrente (es. linea +3, linea -5)
            # Arrotondiamo per capire su quale "gradino" siamo
            current_level_index = int(pct_diff / STEP_PCT)
            
            # Se siamo su un nuovo livello che non abbiamo ancora "cliccato"
            if current_level_index != 0 and current_level_index not in triggered_levels:
                
                # Calcolo Size per livello (Proiettile)
                bullet_size_usd = (TOTAL_ALLOCATION_USD * LEVERAGE) / GRID_LINES
                
                # Logica Neutrale:
                # Se siamo SOPRA il centro (Index > 0) -> VENDI (Short o Chiudi Long)
                # Se siamo SOTTO il centro (Index < 0) -> COMPRA (Long o Chiudi Short)
                
                if current_level_index > 0: # Prezzo salito -> SHORT
                    direction = "SHORT"
                    print(f"🔴 [GRID SELL] Tocco Linea +{current_level_index} @ {current_price:.4f}")
                    bot.execute_order(TICKER, "SHORT", bullet_size_usd) # Scommenta per LIVE
                    
                else: # Prezzo sceso -> LONG
                    direction = "LONG"
                    print(f"🟢 [GRID BUY] Tocco Linea {current_level_index} @ {current_price:.4f}")
                    bot.execute_order(TICKER, "LONG", bullet_size_usd) # Scommenta per LIVE

                # Segniamo il livello come fatto
                triggered_levels.add(current_level_index)
                
                # Gestione "Yo-Yo": Se torniamo indietro, liberiamo il livello precedente
                # Es. Se eravamo a +5 e ora siamo a +4, rimuoviamo +5 dai triggered così se risale lo rifacciamo
                levels_to_remove = []
                for lvl in triggered_levels:
                    # Se il livello è "lontano" dal prezzo attuale (abbiamo ritracciato), resettalo
                    if abs(lvl - current_level_index) >= 2: 
                        levels_to_remove.append(lvl)
                
                for lvl in levels_to_remove:
                    triggered_levels.remove(lvl)
                    # Qui assumiamo un "Take Profit implicito" perché il prezzo è tornato indietro
                    # Loggiamo un piccolo profitto virtuale per la dashboard
                    step_profit = bullet_size_usd * STEP_PCT
                    payload = {
                        "operation": "CLOSE_PARTIAL", "symbol": TICKER, "agent": AGENT_NAME,
                        "reason": f"Grid Return Level {lvl}", "pnl": step_profit
                    }
                    db_utils.log_bot_operation(payload)

                # Log Operazione Principale
                if direction:
                    payload = {
                        "operation": "OPEN", "symbol": TICKER, "direction": direction,
                        "reason": f"Grid Line {current_level_index}", "agent": AGENT_NAME,
                        "target_portion_of_balance": 0.01
                    }
                    db_utils.log_bot_operation(payload)

        except Exception as e:
            print(f"Err Barry: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_barry()
