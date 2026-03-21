import asyncio
import json
import requests
import websockets
from collections import deque, defaultdict
from datetime import datetime, timedelta
import pytz
import numpy as np
import logging

# ----------------------
# CONFIG
# ----------------------
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
COINCAP_WS = "wss://ws.coincap.io/trades/binance"
TIMEZONE = pytz.timezone("Africa/Lagos")
EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
SIGNALS_PER_HOUR = 2
MIN_SIGNAL_INTERVAL = 1800  # 30 min between signals
BLOCKED_PAIRS = []

# ----------------------
# GLOBAL STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
signal_history = defaultdict(list)
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))
active_signals = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ----------------------
# EMA & TREND
# ----------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

def detect_trend(p):
    if len(p) < 50: return None
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if not all([e1,e2,e3,e4]): return None
    if e1>e2 and e3>e4: return "BUY"
    if e1<e2 and e3<e4: return "SELL"
    return None

def is_stable_and_no_pullback(p,direction):
    if len(p)<OBSERVATION_TICKS+5: return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY": return np.all(last_diff>0)
    if direction=="SELL": return np.all(last_diff<0)
    return False

def is_market_stable(p):
    if len(p)<30: return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    return std/mean<0.005

def calculate_accuracy(p,direction):
    score=0
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if direction=="BUY" and e1>e2 and e3>e4: score+=25
    if direction=="SELL" and e1<e2 and e3<e4: score+=25
    diff = np.diff(p[-5:])
    if direction=="BUY" and np.all(diff>0): score+=25
    if direction=="SELL" and np.all(diff<0): score+=25
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean<0.005: score+=25
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY" and np.all(last_diff>0): score+=25
    if direction=="SELL" and np.all(last_diff<0): score+=25
    return min(score,100)

# ----------------------
# TELEGRAM
# ----------------------
def send_signal(pair,direction,accuracy):
    arrow = "⬆️" if direction=="BUY" else "⬇️"
    msg=f"""SIGNAL {arrow}
Asset: {pair}
Accuracy: {accuracy}%
Expiration: M{EXPIRY_MINUTES}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Signal sent: {pair} {direction} Accuracy {accuracy}%")

# ----------------------
# STREAM HANDLER
# ----------------------
async def stream_deriv(pairs):
    async with websockets.connect(DERIV_WS) as ws:
        for pair in pairs:
            await ws.send(json.dumps({"ticks":pair,"subscribe":1}))
        async for msg in ws:
            data = json.loads(msg)
            if "tick" not in data: continue
            pair = data["tick"]["symbol"]
            price = data["tick"]["quote"]
            prices[pair].append(price)
            now=datetime.now(TIMEZONE)
            seconds_since_last = (now-last_signal_times[pair]).total_seconds()
            if seconds_since_last < MIN_SIGNAL_INTERVAL: continue
            direction = detect_trend(list(prices[pair]))
            if not direction: continue
            if not is_stable_and_no_pullback(list(prices[pair]),direction): continue
            if not is_market_stable(list(prices[pair])): continue
            accuracy = calculate_accuracy(list(prices[pair]),direction)
            send_signal(pair,direction,accuracy)
            last_signal_times[pair] = now
            active_signals.append(pair)
            await asyncio.sleep(EXPIRY_MINUTES*60)
            active_signals.remove(pair)

# ----------------------
# MAIN LOOP
# ----------------------
async def main():
    pairs = ["frxEURUSD","frxGBPUSD","BTC/USD","ETH/USD","LTC/USD"]  # Top-ranked pairs
    while True:
        try:
            await stream_deriv(pairs)
        except Exception as e:
            logging.error(f"Stream error: {e}")
            await asyncio.sleep(5)

# ----------------------
# RUN SYSTEM
# ----------------------
asyncio.run(main())
