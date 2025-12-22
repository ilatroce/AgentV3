import os
import time
import pandas as pd
from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account.signers.local import LocalAccount

# --- CONFIGURATION ---
SYMBOL = "ETH"           # Coin to trade
TIMEFRAME = "15m"        # 15 Minute Candles
LEVERAGE = 1             # Start safe (1x)
SIZE_USD = 5.0          # Amount to trade per entry (in USD)
RISK_REWARD = 1.5        # Target 1.5x the risk
STOP_LOSS_PCT = 0.01     # 1% Stop Loss distance (adjust based on volatility)

# Load Environment Variables (Set these in Railway)
load_dotenv()
SECRET_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

def get_market_data(info):
    """Fetches 15m candles and calculates EMAs."""
    print(f"Fetching data for {SYMBOL}...")
    # Get 500 candles (enough for 200 EMA)
    candles = info.candles_snapshot(SYMBOL, TIMEFRAME) 
    
    # Convert to DataFrame
    df = pd.DataFrame(candles)
    df['c'] = df['c'].astype(float) # Close price
    df['h'] = df['h'].astype(float) # High
    df['l'] = df['l'].astype(float) # Low
    
    # Calculate Indicators
    df['EMA_200'] = df['c'].ewm(span=200, adjust=False).mean()
    df['EMA_20'] = df['c'].ewm(span=20, adjust=False).mean()
    
    return df

def execute_trade(exchange, side, entry_price):
    """Places a Market Entry + SL/TP Trigger Orders."""
    
    # 1. Calculate Position Size (in ETH, not USD)
    # Note: You might need to adjust precision (rounding) for different coins
    size = round(SIZE_USD / entry_price, 4) 
    
    print(f"🚀 Placing {side} Order: {size} {SYMBOL} at ~${entry_price}")

    # 2. Place Market Entry
    # is_buy: True for Buy, False for Sell
    is_buy = True if side == "BUY" else False
    
    order_result = exchange.market_open(SYMBOL, is_buy, size, None, 0.01) # 1% slippage tolerance
    print(f"Entry Result: {order_result}")

    if order_result['status'] == 'ok':
        # 3. Calculate SL and TP prices
        if is_buy:
            sl_price = entry_price * (1 - STOP_LOSS_PCT)
            tp_price = entry_price * (1 + (STOP_LOSS_PCT * RISK_REWARD))
        else:
            sl_price = entry_price * (1 + STOP_LOSS_PCT)
            tp_price = entry_price * (1 - (STOP_LOSS_PCT * RISK_REWARD))

        # Round prices to suitable precision (usually 2 decimals for ETH/BTC)
        sl_price = round(sl_price, 2)
        tp_price = round(tp_price, 2)

        print(f"🛡️ Setting SL: {sl_price} | 🎯 Setting TP: {tp_price}")

        # 4. Place Stop Loss (Trigger Order)
        exchange.order(SYMBOL, not is_buy, size, sl_price, {"trigger": {"isMarket": True, "triggerPx": sl_price, "tpsl": "sl"}})
        
        # 5. Place Take Profit (Trigger Order)
        exchange.order(SYMBOL, not is_buy, size, tp_price, {"trigger": {"isMarket": True, "triggerPx": tp_price, "tpsl": "tp"}})

def main():
    print("--- Hyperliquid Bot Starting ---")
    
    # Setup Connection
    account = LocalAccount(key=SECRET_KEY, address=WALLET_ADDRESS)
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(account, constants.MAINNET_API_URL, account_address=WALLET_ADDRESS)
    
    # Set Leverage once at start
    print(f"Setting Leverage to {LEVERAGE}x")
    exchange.update_leverage(LEVERAGE, SYMBOL)

    while True:
        try:
            # 1. Get Data
            df = get_market_data(info)
            current_price = df['c'].iloc[-1]
            ema_200 = df['EMA_200'].iloc[-1]
            ema_20 = df['EMA_20'].iloc[-1]
            
            # Previous candles for confirmation
            last_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]

            print(f"Price: {current_price} | EMA200: {round(ema_200,2)} | EMA20: {round(ema_20,2)}")

            # 2. Check Logic
            # BUY SETUP: Price > 200 EMA + Price touched 20 EMA + Green Confirmation
            if current_price > ema_200:
                # Check for pullback (Low touched 20 EMA recently)
                # We check if the LAST candle's low dipped below/near EMA 20
                if last_candle['l'] <= ema_20 * 1.001: 
                    # CONFIRMATION: Close is higher than previous high (Momentum back up)
                    if last_candle['c'] > prev_candle['h']:
                        print("✅ BUY SIGNAL FOUND!")
                        # Check if we already have a position? (Basic check)
                        positions = info.user_state(WALLET_ADDRESS)['assetPositions']
                        has_position = any(p['position']['coin'] == SYMBOL and float(p['position']['szi']) != 0 for p in positions)
                        
                        if not has_position:
                            execute_trade(exchange, "BUY", current_price)
                        else:
                            print("⚠️ Position already open. Skipping.")

            # SELL SETUP: Price < 200 EMA + Price touched 20 EMA + Red Confirmation
            elif current_price < ema_200:
                if last_candle['h'] >= ema_20 * 0.999:
                    if last_candle['c'] < prev_candle['l']:
                        print("✅ SELL SIGNAL FOUND!")
                        positions = info.user_state(WALLET_ADDRESS)['assetPositions']
                        has_position = any(p['position']['coin'] == SYMBOL and float(p['position']['szi']) != 0 for p in positions)
                        
                        if not has_position:
                            execute_trade(exchange, "SELL", current_price)
                        else:
                            print("⚠️ Position already open. Skipping.")

            print("Sleeping for 60 seconds...")
            time.sleep(60)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
