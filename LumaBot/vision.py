import requests
import pandas as pd
import json

class Vision:
    def __init__(self):
        print(">> VISION: Optical Systems Online")

    def get_candles(self, coin, interval="1h"):
        try:
            url = "https://api.hyperliquid.xyz/info"
            headers = {"Content-Type": "application/json"}
            payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": 0}}
            response = requests.post(url, headers=headers, json=payload)
            data = response.json()
            if not data: return []
            return data
        except: return []

    def get_user_state(self, address):
        try:
            url = "https://api.hyperliquid.xyz/info"
            headers = {"Content-Type": "application/json"}
            payload = {"type": "clearinghouseState", "user": address}
            response = requests.post(url, headers=headers, json=payload)
            return response.json()
        except: return None
