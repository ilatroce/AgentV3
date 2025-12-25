import sys
import os
import time
import pandas as pd
from dotenv import load_dotenv

# Import root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_trader import HyperLiquidTrader
import db_utils

load_dotenv()

# --- CONFIGURATION HARVEST: FUNDING FARMER 🚜 ---
AGENT_NAME = "Harvest"
LOOP_SPEED = 15                 # Check every 15 seconds
MIN_HOURLY_FUNDING = 0.0001     # 0.01% Hourly (Approx 87% APR) to be worth logging
ALERT_ONLY = True               # Set to False if you want to auto-trade (Safe mode for now)

def run_harvest():
    print(f"🚜 [Harvest] Starting High Yield Scanner...")
    
    private_key = os.getenv("PRIVATE_KEY")
    wallet = os.getenv("WALLET_ADDRESS")
    
    # Initialize Trader
    bot = HyperLiquidTrader(private_key, wallet, testnet=False)

    while True:
        try:
            # 1. Get Market Landscape
            opportunities = bot.get_funding_landscape()
            
            if not opportunities:
                time.sleep(5)
                continue

            # 2. Find High Yield Coins
            top_ops = opportunities[:5] # Check top 5
            
            print(f"\n--- 🚜 Harvest Scan ({pd.Timestamp.now().strftime('%H:%M:%S')}) ---")
            
            for op in top_ops:
                coin = op['coin']
                hourly_rate = op['funding_hourly']
                hourly_pct = hourly_rate * 100
                apr = op['funding_apr']
                price = op['price']
                
                # Visual Logic
                is_high_yield = abs(hourly_rate) >= MIN_HOURLY_FUNDING
                
                if is_high_yield:
                    direction = "SHORT" if hourly_rate > 0 else "LONG"
                    emoji = "🔥" if apr > 100 else "✨"
                    
                    print(f"{emoji} {coin:<8} | Rate: {hourly_pct:>.4f}%/hr | APR: {apr:.0f}% | Rec: {direction}")
                    
                    # 3. Log to Database (So you can see it in Dashboard or history)
                    # We use a custom operation type "SCAN_ALERT"
                    payload = {
                        "operation": "SCAN_ALERT",
                        "symbol": coin,
                        "direction": direction,
                        "reason": f"High Funding: {hourly_pct:.4f}%/hr ({apr:.0f}% APR)",
                        "target_portion_of_balance": 0,
                        "leverage": 0,
                        "agent": AGENT_NAME
                    }
                    
                    # Log to DB without executing trade
                    try:
                        db_utils.log_bot_operation(payload)
                    except Exception as e:
                        print(f"DB Log Error: {e}")

            # Separator
            print("-" * 40)

        except Exception as e:
            print(f"Err Harvest: {e}")
            time.sleep(5)
            
        time.sleep(LOOP_SPEED)

if __name__ == "__main__":
    run_harvest()
