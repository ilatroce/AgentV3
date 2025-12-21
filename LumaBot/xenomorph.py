import pandas as pd
class Xenomorph:
    def hunt(self, coin, candles):
        try:
            df = pd.DataFrame(candles)
            if 'c' in df.columns: close = pd.to_numeric(df['c'])
            else: close = pd.to_numeric(df['close'])
            
            # Simple Breakout Logic for Safety
            current = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            
            pct_change = (current - prev) / prev
            if pct_change > 0.02: return "ATTACK" # 2% pump detection
            return "WAIT"
        except: return "WAIT"
