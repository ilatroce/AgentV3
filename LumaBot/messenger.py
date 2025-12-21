import json
import requests
class Messenger:
    def __init__(self):
        try:
            with open("server_config.json") as f:
                self.hooks = json.load(f).get("discord_webhooks", {})
        except: self.hooks = {}

    def send(self, channel, message):
        url = self.hooks.get(channel)
        if url:
            try: requests.post(url, json={"content": message})
            except: pass
            
    def notify_trade(self, coin, signal, price, size):
        self.send("trades", f"🦅 **LUMA:** {signal} {coin} @ {price} (${size})")
