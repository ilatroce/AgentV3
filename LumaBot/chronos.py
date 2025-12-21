import time
class Chronos:
    def get_session(self):
        h = int(time.strftime("%H"))
        if 0 <= h < 8: return {"name": "ASIA", "aggression": 0.8}
        if 8 <= h < 16: return {"name": "LONDON", "aggression": 1.2}
        return {"name": "NY", "aggression": 1.5}
