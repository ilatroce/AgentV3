import os
import requests
class Messenger:
    def __init__(self):
        # We try to grab the URL directly from Environment
        self.hooks = {
            "trades": os.environ.get("DISCORD_TRADES"),
            "errors": os.environ.get("DISCORD_ERRORS"),
            "info":   os.environ.get("DISCORD_INFO")
        }

    def send(self, channel, message):
        url = self.hooks.get(channel)
        if url:
            try: requests.post(url, json={"content": message})
            except: pass
            
    def notify_trade(self, coin, signal, price, size):
        self.send("trades", f"🦅 **LUMA:** {signal} {coin} @ {price} (${size})")
