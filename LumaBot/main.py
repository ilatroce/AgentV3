import time
import json
import sys
import os
import warnings
from collections import deque

warnings.simplefilter("ignore")

# --- RAILWAY CONFIGURATION ---
# Checks if we are on Railway (Volume mount) or Local
DATA_DIR = "/app/data" if os.path.exists("/app/data") else "."
ANCHOR_FILE = os.path.join(DATA_DIR, "equity_anchor.json")

BTC_TICKER = "BTC"

FLEET_CONFIG = {
    "SOL":   {"type": "PRINCE", "lev": 10, "risk_mult": 1.0, "stop_loss": 0.03},
    "SUI":   {"type": "PRINCE", "lev": 10, "risk_mult": 1.0, "stop_loss": 0.03},
    "WIF":   {"type": "MEME",   "lev": 5,  "risk_mult": 1.0, "stop_loss": 0.05},
    "kPEPE": {"type": "MEME",   "lev": 5,  "risk_mult": 1.0, "stop_loss": 0.05},
    "DOGE":  {"type": "MEME",   "lev": 5,  "risk_mult": 1.0, "stop_loss": 0.05}
}

STARTING_EQUITY = 0.0

def get_config():
    """Loads settings from Railway Environment Variables"""
    return {
        "wallet_address": os.environ.get("WALLET_ADDRESS"),
        "discord_webhooks": {
            "trades": os.environ.get("DISCORD_TRADES"),
            "errors": os.environ.get("DISCORD_ERRORS"),
            "info": os.environ.get("DISCORD_INFO")
        },
        "risk_level": "AGGRESSIVE"
    }

def load_anchor(current_equity):
    try:
        if os.path.exists(ANCHOR_FILE):
            with open(ANCHOR_FILE, 'r') as f:
                data = json.load(f)
                return float(data.get("start_equity", current_equity))
        else:
            with open(ANCHOR_FILE, 'w') as f:
                json.dump({"start_equity": current_equity}, f)
            return current_equity
    except:
        return current_equity

def normalize_positions(raw_positions):
    clean_pos = []
    if not raw_positions: return []
    for item in raw_positions:
        try:
            p = item['position'] if 'position' in item else item
            coin = p.get('coin') or p.get('symbol') or p.get('asset') or "UNKNOWN"
            if coin == "UNKNOWN": continue
            size = float(p.get('szi') or p.get('size') or p.get('position') or 0)
            entry = float(p.get('entryPx') or p.get('entry_price') or 0)
            pnl = float(p.get('unrealizedPnl') or p.get('unrealized_pnl') or 0)
            if size == 0: continue
            clean_pos.append({"coin": coin, "size": size, "entry": entry, "pnl": pnl})
        except: continue
    return clean_pos

# --- LOAD MODULES ---
try:
    print(">> [1/10] Loading Modules...")
    from vision import Vision
    from hands import Hands
    from xenomorph import Xenomorph
    from smart_money import SmartMoney
    from deep_sea import DeepSea
    from messenger import Messenger
    from chronos import Chronos
    from historian import Historian
    from oracle import Oracle
    from seasonality import Seasonality
    from predator import Predator
    
    print(">> [2/10] Initializing Organs...")
    vision = Vision()
    hands = Hands()
    xeno = Xenomorph()
    whale = SmartMoney()
    ratchet = DeepSea(DATA_DIR) # Pass the storage path
    msg = Messenger()
    chronos = Chronos()
    history = Historian()
    oracle = Oracle()
    season = Seasonality()
    predator = Predator()
    print(">> SYSTEM INTEGRITY: 100%")
except Exception as e:
    print(f"xx CRITICAL LOAD ERROR: {e}")
    sys.exit()

def main_loop():
    global STARTING_EQUITY
    print("🦅 LUMA SINGULARITY (CLOUD EDITION) ONLINE")
    
    cfg = get_config()
    address = cfg.get('wallet_address')
    if not address:
        print("xx ERROR: WALLET_ADDRESS not found in Environment Variables")
        return

    msg.send("info", "🦅 **LUMA CLOUD:** System Initialized on Railway.")
    
    # Set Leverage at boot
    for coin, rules in FLEET_CONFIG.items():
        try:
            hands.set_leverage_all([coin], leverage=rules['lev'])
            time.sleep(0.2) 
        except: pass

    last_history_check = 0
    cached_history_data = {'regime': 'NEUTRAL', 'multiplier': 1.0}
    
    while True:
        session_data = chronos.get_session()
        
        # Check Bitcoin Regime (Every 4 hours)
        if time.time() - last_history_check > 14400: 
            try:
                btc_daily = vision.get_candles(BTC_TICKER, "1d")
                if btc_daily:
                    cached_history_data = history.check_regime(btc_daily)
                    last_history_check = time.time()
            except: pass
        history_data = cached_history_data
        
        equity = 0.0
        cash = 0.0
        clean_positions = []
        open_orders = [] 
        
        try:
            user_state = vision.get_user_state(address)
            if user_state:
                equity = float(user_state.get('marginSummary', {}).get('accountValue', 0))
                cash = float(user_state.get('withdrawable', 0))
                clean_positions = normalize_positions(user_state.get('assetPositions', []))
                open_orders = user_state.get('openOrders', [])
        except: pass
        
        if STARTING_EQUITY == 0.0 and equity > 0:
            STARTING_EQUITY = load_anchor(equity)
        current_pnl = equity - STARTING_EQUITY if STARTING_EQUITY > 0 else 0.0
        
        risk_mode = "AGGRESSIVE"
        investable_pct = 0.60 
        if current_pnl > 5.00:
            risk_mode = "GOD_MODE"
            investable_pct = 0.70 
        
        total_investable_cash = equity * investable_pct
        prince_margin_target = total_investable_cash * 0.25
        meme_margin_target = total_investable_cash * 0.1666
        
        # Log status to console (Railway Logs)
        print(f">> [SCAN] Eq: ${equity:.2f} | PnL: ${current_pnl:.2f} | Mode: {risk_mode} | Active: {len(clean_positions)}")

        # --- LOOP THROUGH COINS ---
        for coin, rules in FLEET_CONFIG.items():
            ratchet.check_trauma(hands, coin)
            
            existing = next((p for p in clean_positions if p['coin'] == coin), None)
            if existing: continue
            
            pending = next((o for o in open_orders if o.get('coin') == coin), None)
            if pending: continue 

            try: candles = vision.get_candles(coin, "1h") 
            except: candles = []
            if not candles: continue
            
            current_price = float(candles[-1].get('close') or candles[-1].get('c') or 0)
            if current_price == 0: continue

            micro_season = season.get_multiplier(rules['type'])
            macro_mult = session_data['aggression'] * history_data['multiplier']
            total_mult = macro_mult * micro_season['mult']
            
            if total_mult < 1.0: total_mult = 1.0
            if total_mult > 1.0: total_mult = 1.0 
            
            target_margin_usd = prince_margin_target if rules['type'] == "PRINCE" else meme_margin_target
            leverage = rules['lev']
            final_size = target_margin_usd * leverage
            
            if final_size < 60.0: final_size = 60.0
            final_size = round(final_size, 2)
            
            context_str = f"Session: {session_data['name']}, Season: {micro_season['note']}"
            predator_signal = predator.analyze_divergence(candles)
            sm_signal = whale.hunt_turtle(candles) or whale.hunt_ghosts(candles)
            
            # --- EXECUTION LOGIC ---
            if sm_signal:
                if predator_signal != "EXHAUSTION_SELL" or sm_signal['side'] == "SELL":
                     if oracle.consult(coin, sm_signal['type'], sm_signal['price'], context_str):
                        side = sm_signal['side']
                        print(f"!! SIGNAL: {coin} {side} (Smart Money)")
                        hands.place_trap(coin, side, sm_signal['price'], final_size)
                        msg.notify_trade(coin, f"TRAP_{side}", sm_signal['price'], final_size)
            
            elif xeno.hunt(coin, candles) == "ATTACK":
                if predator_signal == "REAL_PUMP" or predator_signal is None:
                    if rules['type'] == "MEME" and session_data['name'] == "ASIA": pass 
                    else:
                        if oracle.consult(coin, "BREAKOUT_BUY", "Market", context_str):
                            coin_size = final_size / current_price
                            print(f"!! SIGNAL: {coin} MARKET BUY (Xenomorph)")
                            hands.place_market_order(coin, "BUY", coin_size)
                            msg.notify_trade(coin, "MARKET_BUY", "Market", final_size)

        # --- MANAGE EXISTING ---
        ratchet_events = ratchet.manage_positions(hands, clean_positions, FLEET_CONFIG)
        if ratchet_events:
            for event in ratchet_events:
                msg.send("info", f"⚙️ **RATCHET:** {event}")

        time.sleep(15)

if __name__ == "__main__":
    try: main_loop()
    except Exception as e:
        print(f"CRASH: {e}")
