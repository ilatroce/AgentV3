import sys
import os
import time
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Path hack for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- 🕸️ CONFIGURATION ---
CHECK_INTERVAL = 60             # Check every minute
TIMEFRAME = "15m"               # 15 Minute candles
LOOKBACK_CANDLES = 50           # Look at last ~12 hours
MIN_VOLUME_USD = 500000         # High volume only (Liquidity)

# 🎯 STRATEGY FILTERS
MIN_24H_CHANGE = 15.0           # Must be up at least 15% (The "Pump")
MIN_CHOPPINESS = 50.0           # > 50 means ranging (The "Stall")
CONTRACTION_FACTOR = 0.8        # Current volatility must be < 80% of Peak volatility (The "Shrink")

def get_market_stats(bot):
    """Fetch 24h stats for all coins to find the 'Runners'."""
    try:
        # Get raw stats (price, 24h change, volume)
        # Hyperliquid 'metaAndAssetCtxs' is the most efficient endpoint
        import requests
        url = f"{bot.base_url}/info"
        payload = {"type": "metaAndAssetCtxs"}
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        
        if resp.status_code == 200:
            data = resp.json()
            universe = data[0]['universe']
            asset_ctxs = data[1]
            
            stats = {}
            for i, coin_meta in enumerate(universe):
                ctx = asset_ctxs[i]
                
                # Calculate 24h change roughly from current vs day open
                # Note: ctx['dayNtlVlm'] is volume. prevDayPx is close of yesterday.
                current_px = float(ctx['markPx'])
                prev_day_px = float(ctx['prevDayPx'])
                
                if prev_day_px == 0: continue
                
                change_pct = ((current_px - prev_day_px) / prev_day_px) * 100
                volume_usd = float(ctx['dayNtlVlm'])
                
                stats[coin_meta['name']] = {
                    "change_24h": change_pct,
                    "volume": volume_usd,
                    "price": current_px
                }
            return stats
        return {}
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return {}

def analyze_candles(df):
    """Calculate Pump, Chop, and Contraction metrics."""
    if df.empty or len(df) < 20:
        return None

    # 1. Volatility (ATR-like)
    # Candle Size = High - Low
    df['candle_size'] = df['high'] - df['low']
    df['candle_pct'] = (df['candle_size'] / df['low']) * 100
    
    current_vol = df['candle_pct'].iloc[-3:].mean() # Avg of last 3 candles
    peak_vol = df['candle_pct'].max()               # Biggest candle in lookback
    
    # 2. Contraction (Is it cooling off?)
    # Ratio < 1.0 means getting smaller.
    contraction_ratio = current_vol / peak_vol if peak_vol > 0 else 1.0

    # 3. Choppiness (Standard Formula)
    high_low_sum = (df['high'] - df['low']).sum()
    true_range_max = df['high'].max() - df['low'].min()
    
    if true_range_max == 0:
        choppiness = 0
    else:
        choppiness = 100 * np.log10(high_low_sum / true_range_max) / np.log10(len(df))

    return {
        "current_vol_pct": current_vol,
        "peak_vol_pct": peak_vol,
        "contraction": contraction_ratio,
        "choppiness": choppiness
    }

def run_scanner():
    print(f"🕸️ [Grid Scanner] Tracking 'Pump & Consolidation' patterns...")
    
    key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS")
    bot = HyperLiquidTrader(key, wallet, testnet=False)

    while True:
        try:
            # 1. Filter Universe (Find coins up > 15%)
            market_stats = get_market_stats(bot)
            runners = [
                coin for coin, data in market_stats.items() 
                if data['change_24h'] >= MIN_24H_CHANGE and data['volume'] > MIN_VOLUME_USD
            ]
            
            print(f"\n--- 🔍 Scanning {len(runners)} Runners (>{MIN_24H_CHANGE}% 24h) ---")
            
            found_opps = []

            for coin in runners:
                # 2. Deep Dive: Fetch Candles
                df = bot.get_candles(coin, interval=TIMEFRAME, limit=LOOKBACK_CANDLES)
                metrics = analyze_candles(df)
                
                if not metrics: continue

                # 3. Apply "The Setup" Logic
                is_contracting = metrics['contraction'] <= CONTRACTION_FACTOR
                is_choppy = metrics['choppiness'] >= MIN_CHOPPINESS
                
                # Scoring: Higher Chop + Good Contraction = Better
                score = (metrics['choppiness'] / 100) + (1 - metrics['contraction'])
                
                stats = market_stats[coin]
                
                found_opps.append({
                    "coin": coin,
                    "score": score,
                    "change": stats['change_24h'],
                    "chop": metrics['choppiness'],
                    "contraction": metrics['contraction'],
                    "vol": metrics['current_vol_pct']
                })
                
                # Sleep to respect API limits
                time.sleep(0.1)

            # Sort by "Best Grid Setup"
            found_opps.sort(key=lambda x: x['score'], reverse=True)

            # Print Table
            if found_opps:
                print(f"{'COIN':<8} | {'24h %':<8} | {'CHOP':<6} | {'SHRINK':<8} | {'VOL (15m)':<10}")
                print("-" * 55)
                for op in found_opps[:5]:
                    # Shrink: 0.5 means candles are half the size of the peak (Good)
                    shrink_display = f"{op['contraction']:.2f}x" 
                    print(f"🔥 {op['coin']:<6} | +{op['change']:.0f}%    | {op['chop']:.0f}     | {shrink_display:<8} | {op['vol']:.2f}%")
                    
                    # Log Alert
                    if op['score'] > 0.8: # Good setup
                        db_utils.log_bot_operation({
                            "operation": "GRID_ALERT",
                            "symbol": op['coin'],
                            "direction": "NEUTRAL",
                            "reason": f"Pumped +{op['change']:.0f}% & Consolidated ({shrink_display})",
                            "agent": "GridScanner"
                        })
            else:
                print("No 'Pump & Stall' setups found right now.")

        except Exception as e:
            print(f"Scanner Error: {e}")
        
        print(f"\nSleeping {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run_scanner()
