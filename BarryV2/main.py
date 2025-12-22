import os
import time
import pandas as pd
import datetime 
from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account

# --- CONFIGURATION ---
SYMBOL = "ETH"           
TIMEFRAME = "15m"        
LEVERAGE = 1             
SIZE_USD = 20.0          
RISK_REWARD = 1.5        
STOP_LOSS_PCT = 0.01     

load_dotenv()
PRIVATE_KEY = os.getenv("PRIVATE_KEY") 
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

def get_market_data(info):
    """Fetches 15m candles and calculates EMAs."""
    print(f"Fetching data for {SYMBOL}...")
    
    # --- FIX: Calculate Start/End Times (Milliseconds) ---
    # We fetch 5 days of data to ensure we have enough for the 200 EMA
    end_time = int(time.time() * 1000)
    start_time = end_time - (5 * 24 * 60 * 60 * 1000) # 5 days back
    
    # Updated function call with times
    candles = info.candles_snapshot(SYMBOL, TIMEFRAME, start_time, end_time) 
    
    df = pd.DataFrame(candles)
    df['c'] = df['c'].astype(float)
    df['h'] = df['h'].astype(float)
    df['l'] = df['l'].astype(float)
    
    # Calculate Indicators
    df['EMA_200'] = df['c'].ewm(span=200, adjust=False).mean()
    df['EMA_20'] = df['c'].ewm(span=20, adjust=False).mean()
    
    return df

def execute_trade(exchange, side, entry_price):
    size = round(SIZE_USD / entry_price, 4) 
    print(f"🚀 Placing {side} Order: {size} {SYMBOL} at ~${entry_price}")

    is_buy = True if side == "BUY" else False
    
    order_result = exchange.market_open(SYMBOL, is_buy, size, None, 0.01)
    print(f"Entry Result: {order_result}")

    if order_result['status'] == 'ok':
        if is_buy:
            sl_price = entry_price * (1 - STOP_LOSS_PCT)
            tp_price = entry_price * (1 + (STOP_LOSS_PCT * RISK_REWARD))
        else:
            sl_price = entry_price * (1 + STOP_LOSS_PCT)
            tp_price = entry_price * (1 - (STOP_LOSS_PCT * RISK_REWARD))

        sl_price = round(sl_price, 2)
        tp_price = round(tp_price, 2)

        print(f"🛡️ Setting SL: {sl_price} | 🎯 Setting TP: {tp_price}")

        exchange.order(SYMBOL, not is_buy, size, sl_price, {"trigger": {"isMarket": True, "triggerPx": sl_price, "tpsl": "sl"}})
        exchange.order(SYMBOL, not is_buy, size, tp_price, {"trigger": {"isMarket": True, "triggerPx": tp_price, "tpsl": "tp"}})

def main():
    print("--- Hyperliquid Bot Starting ---")
    
    if not PRIVATE_KEY or not WALLET_ADDRESS:
        print("❌ Error: PRIVATE_KEY or WALLET_ADDRESS not found.")
        return

    try:
        account = Account.from_key(PRIVATE_KEY)
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        exchange = Exchange(account, constants.MAINNET_API_URL, account_address=WALLET_ADDRESS)
        
        print(f"Setting Leverage to {LEVERAGE}x")
        exchange.update_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"⚠️ Initialization Error: {e}")
        return

    while True:
        try:
            df = get_market_data(info)
            current_price = df['c'].iloc[-1]
            ema_200 = df['EMA_200'].iloc[-1]
            ema_20 = df['EMA_20'].iloc[-1]
            
            last_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]

            print(f"Price: {current_price} | EMA200: {round(ema_200,2)} | EMA20: {round(ema_20,2)}")

            # BUY Logic
            if current_price > ema_200:
                if last_candle['l'] <= ema_20 * 1.001: 
                    if last_candle['c'] > prev_candle['h']:
                        print("✅ BUY SIGNAL FOUND!")
                        positions = info.user_state(WALLET_ADDRESS)['assetPositions']
                        has_position = any(p['position']['coin'] == SYMBOL and float(p['position']['szi']) != 0 for p in positions)
                        if not has_position:
                            execute_trade(exchange, "BUY", current_price)

            # SELL Logic
            elif current_price < ema_200:
                if last_candle['h'] >= ema_20 * 0.999:
                    if last_candle['c'] < prev_candle['l']:
                        print("✅ SELL SIGNAL FOUND!")
                        positions = info.user_state(WALLET_ADDRESS)['assetPositions']
                        has_position = any(p['position']['coin'] == SYMBOL and float(p['position']['szi']) != 0 for p in positions)
                        if not has_position:
                            execute_trade(exchange, "SELL", current_price)

            print("Sleeping for 60 seconds...")
            time.sleep(60)

        except Exception as e:
            print(f"Error in loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
