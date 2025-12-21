import time
import json
import os

class DeepSea:
    def __init__(self, data_path="."):
        print(">> Deep Sea (Shield & Ratchet) Loaded")
        self.state_file = os.path.join(data_path, "ratchet_state.json")
        self.ratchet_state = self._load_state()
        self.secured_coins = list(self.ratchet_state.keys())

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except: pass
        return {}

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.ratchet_state, f)
            self.secured_coins = list(self.ratchet_state.keys())
        except: pass

    def check_trauma(self, hands, coin):
        return False

    def manage_positions(self, hands, positions, fleet_config):
        if not positions: return []
        events = []
        
        active_coins = [p['coin'] for p in positions]
        # Clean up old states for closed coins
        for coin in list(self.ratchet_state.keys()):
            if coin not in active_coins:
                del self.ratchet_state[coin]
                self._save_state()
        
        for pos in positions:
            coin = pos['coin']
            size_coins = pos['size']
            entry = pos['entry']
            pnl = pos['pnl']
            
            coin_conf = fleet_config.get(coin, {})
            lev = coin_conf.get('lev', 10)
            coin_type = coin_conf.get('type', 'PRINCE')
            stop_loss_pct = coin_conf.get('stop_loss', 0.05)
            activation_trigger = 0.25 if coin_type == "MEME" else 0.50

            margin = (abs(size_coins) * entry) / lev
            roe = 0.0
            if margin > 0: roe = (pnl / margin) * 100
            
            max_roe_loss = -(stop_loss_pct * lev * 100)
            if max_roe_loss < -50.0: max_roe_loss = -50.0
            
            # STOP LOSS LOGIC
            if roe < max_roe_loss:
                msg = f"🛡️ SHIELD: Stopping {coin} at ${pnl:.2f} (Hit {stop_loss_pct*100}% Limit)"
                print(msg)
                events.append(msg)
                side = "SELL" if size_coins > 0 else "BUY"
                hands.place_market_order(coin, side, abs(size_coins))
                continue

            # RATCHET (PROFIT LOCK) LOGIC
            if coin not in self.ratchet_state:
                if pnl > activation_trigger:
                    msg = f"🔒 RATCHET: Locking {coin} (Starts at ${pnl:.2f})"
                    events.append(msg)
                    self.ratchet_state[coin] = {"highest_pnl": pnl}
                    self._save_state()
            else:
                saved_high = self.ratchet_state[coin]["highest_pnl"]
                if pnl > saved_high:
                    self.ratchet_state[coin]["highest_pnl"] = pnl
                    self._save_state()
                    if pnl > saved_high + 1.0:
                        events.append(f"📈 {coin} New High: ${pnl:.2f}")
                
                allowed_pullback = 0.40 if coin_type == "MEME" else 0.20
                if roe > 10.0: allowed_pullback = 0.05 if coin_type == "MEME" else 0.10
                
                cutoff_value = self.ratchet_state[coin]["highest_pnl"] * (1.0 - allowed_pullback)
                if cutoff_value < 0.20: cutoff_value = 0.20
                
                if pnl < cutoff_value:
                    msg = f"💰 BANKING: {coin} ${pnl:.2f}"
                    events.append(msg)
                    side = "SELL" if size_coins > 0 else "BUY"
                    hands.place_market_order(coin, side, abs(size_coins))
                    del self.ratchet_state[coin]
                    self._save_state()

        return events
