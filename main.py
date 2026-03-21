import asyncio
import json
import requests
import websockets
from datetime import datetime
from collections import deque, defaultdict
import pytz
import numpy as np
import logging

# ----------------------
# CONFIGURATION
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
MAX_PRICES = 5000
MIN_SIGNAL_INTERVAL = 1800

# CRYPTO SYMBOLS
CRYPTO_PAIRS = [
    "bitcoin","ethereum","litecoin","cardano","dogecoin",
    "ripple","polkadot","binance-coin","stellar","chainlink",
    "uniswap","vechain","tron","monero","tezos"
]

# ----------------------
# STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))
signals_sent_this_hour = defaultdict(int)

logging.basicConfig(level=logging.INFO)

# ----------------------
# EMA
# ----------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# ----------------------
# TREND ENGINE
# ----------------------
def detect_trend(p):
    if len(p) < 50:
        return None
    e1 = ema(list(p)[-10:], 3)
    e2 = ema(list(p)[-20:], 5)
    e3 = ema(list(p)[-30:], 8)
    e4 = ema(list(p)[-50:], 13)
    if not all([e1,e2,e3,e4]):
        return None
    if e1 > e2 and e3 > e4:
        return "BUY"
    if e1 < e2 and e3 < e4:
        return "SELL"
    return None

# ----------------------
# FILTER SYSTEM (STRONG)
# ----------------------
def strong_momentum(p, direction):
    diff = np.diff(list(p)[-6:])
    if direction == "BUY":
        return np.sum(diff > 0) >= 5
    if direction == "SELL":
        return np.sum(diff < 0) >= 5
    return False

def low_noise(p):
    if len(p) < 30:
        return False
    std = np.std(list(p)[-30:])
    mean = np.mean(list(p)[-30:])
    return std / mean < 0.007

def breakout_strength(p):
    if len(p) < 20:
        return False
    move = abs(p[-1] - p[-20])
    noise = np.std(list(p)[-20:])
    return move > noise * 2

# ----------------------
# ACCURACY ENGINE
# ----------------------
def calculate_accuracy(p, direction):
    score = 0
    if detect_trend(p) == direction:
        score += 40
    if strong_momentum(p, direction):
        score += 25
    if low_noise(p):
        score += 20
    if breakout_strength(p):
        score += 15
    return min(score, 95)

# ----------------------
# TELEGRAM
# ----------------------
def send_signal(pair, direction, accuracy):
    arrow = "⬆️" if direction == "BUY" else "⬇️"
    msg = f"SIGNAL {arrow}\nPair: {pair}\nAccuracy: {accuracy}%\nExpiry: {EXPIRY_MINUTES} min"
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
        logging.info(f"{pair} {direction} {accuracy}%")
    except Exception as e:
        logging.error(e)

# ----------------------
# GET FOREX SYMBOLS
# ----------------------
async def get_forex():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except Exception as e:
        logging.error(f"Error fetching forex symbols: {e}")
        return []

# ----------------------
# BEST PAIR SELECTION
# ----------------------
def select_best_pairs():
    scored = []
    for pair, p in prices.items():
        if len(p) < 50:
            continue
        direction = detect_trend(p)
        if not direction:
            continue
        acc = calculate_accuracy(p, direction)
        if acc >= 85:
            scored.append((pair, direction, acc))
    scored.sort(key=lambda x: x[2], reverse=True)
    # Only return pairs that haven’t sent a signal this hour
    return scored[:2]

# ----------------------
# MAIN LOOP
# ----------------------
async def main():
    while True:
        now = datetime.now(TIMEZONE)
        weekday = now.weekday()
        hour = now.hour

        # Reset signals count at start of hour
        if now.minute == 0 and now.second < 10:
            signals_sent_this_hour.clear()

        # Determine symbols
        if (weekday == 4 and hour >= 21) or weekday in [5, 6]:
            symbols = CRYPTO_PAIRS
        else:
            symbols = await get_forex()

        # ----------------------
        # Safe WebSocket connection pattern integrated
        # ----------------------
        while True:
            try:
                async with websockets.connect(DERIV_WS) as ws:
                    for s in symbols:
                        await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                    async for msg in ws:
                        data = json.loads(msg)
                        if "tick" not in data:
                            continue

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]
                        prices[pair].append(price)

                        best = select_best_pairs()

                        for pair, direction, acc in best:
                            if signals_sent_this_hour.get(pair, 0) >= 2:
                                continue
                            last_time = last_signal_times[pair]
                            if (now - last_time).total_seconds() < MIN_SIGNAL_INTERVAL:
                                continue
                            send_signal(pair, direction, acc)
                            last_signal_times[pair] = now
                            signals_sent_this_hour[pair] = signals_sent_this_hour.get(pair, 0) + 1
                            await asyncio.sleep(EXPIRY_MINUTES * 60)

            except Exception as e:
                logging.error(f"Connection error: {e}")
                await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(main())
