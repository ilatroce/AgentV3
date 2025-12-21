import json
import time
import os
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

class Hands:
    def __init__(self):
        print(">> HANDS ARMED: Exchange Connected")
        self.address = os.environ.get("WALLET_ADDRESS")
        # Supports PRIVATE_KEY or SECRET_KEY variable names
        self.key = os.environ.get("PRIVATE_KEY") or os.environ.get("SECRET_KEY")
        
        if not self.key or not self.address:
            print("xx CRITICAL: Credentials missing from Environment Variables.")
            return

        self.account = Account.from_key(self.key)
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL)
        
    def set_leverage_all(self, coins, leverage):
        print(f">> HANDS: Enforcing {leverage}x Leverage on Fleet...")
        for coin in coins:
            try:
                self.exchange.update_leverage(leverage, coin)
            except: pass

    def cancel_all_orders(self, coin):
        try:
            open_orders = self.info.open_orders(self.address)
            for order in open_orders:
                if order['coin'] == coin:
                    print(f"🧹 SWEEPING: Canceling old order for {coin}")
                    self.exchange.cancel(coin, order['oid'])
                    time.sleep(0.5) 
        except Exception as e:
            print(f"xx CLEANUP FAILED: {e}")

    def _get_precision(self, coin):
        if coin == "SOL":   return (2, 2)
        if coin == "SUI":   return (4, 1)
        if coin == "BTC":   return (1, 3)
        if coin == "ETH":   return (2, 3)
        if coin == "kPEPE": return (6, 0)
        if coin == "WIF":   return (4, 1)
        if coin == "DOGE":  return (5, 0)
        return (4, 1)

    def place_trap(self, coin, side, price, size_usd):
        self.cancel_all_orders(coin)
        px_prec, sz_prec = self._get_precision(coin)
        final_price = round(price, px_prec)
        raw_size = size_usd / final_price
        if sz_prec == 0: final_size = int(raw_size)
        else: final_size = round(raw_size, sz_prec)
        
        if final_size == 0: return

        print(f">> SETTING TRAP: {side} {coin} @ ${final_price} (Size: {final_size})")
        try:
            is_buy = True if side == "BUY" else False
            result = self.exchange.order(coin, is_buy, final_size, final_price, {"limit": {"tif": "Gtc"}})
            if result['status'] == 'err': print(f"xx EXCHANGE REJECTED: {result['response']}")
        except Exception as e:
            print(f"xx ORDER REJECTED (SDK): {e}")

    def place_market_order(self, coin, side, size_coins):
        is_buy = True if side == "BUY" else False
        try:
            _, sz_prec = self._get_precision(coin)
            if sz_prec == 0: sz = int(size_coins)
            else: sz = round(float(size_coins), sz_prec)
            if sz == 0: return 
            print(f"⚡ CASTING SPELL: MARKET {side} {sz} {coin}")
            self.exchange.market_open(coin, is_buy, sz)
        except Exception as e:
            print(f"xx MARKET EXECUTION FAILED: {e}")
