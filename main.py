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
MIN_SIGNAL_INTERVAL = 60  # frequent scanning

# Crypto (weekend)
CRYPTO_PAIRS = [
    "cryBTCUSD","cryETHUSD","cryLTCUSD","cryXRPUSD","cryBCHUSD",
    "cryEOSUSD","cryTRXUSD","cryADAUSD","cryBNBUSD","cryDOTUSD",
    "cryLINKUSD","cryXLMUSD","cryDOGEUSD","cryUNIUSD","crySOLUSD"
]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
last_signal_time = datetime.min.replace(tzinfo=TIMEZONE)
signal_count_hour = 0
last_hour = None
pending_signal = None
signal_ready = False

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO)

# ----------------------
# EMA FUNCTION
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
# TREND ANALYSIS
# ----------------------
def analyze_pair(p):
    if len(p) < 60:
        return None, 0

    p = list(p)

    e1 = ema(p[-10:], 3)
    e2 = ema(p[-20:], 5)
    e3 = ema(p[-30:], 8)
    e4 = ema(p[-50:], 13)

    if not all([e1, e2, e3, e4]):
        return None, 0

    direction = None
    score = 0

    # Trend alignment
    if e1 > e2 > e3 > e4:
        direction = "BUY"
        score += 30
    elif e1 < e2 < e3 < e4:
        direction = "SELL"
        score += 30

    if not direction:
        return None, 0

    # Momentum filter
    diff = np.diff(p[-6:])
    if direction == "BUY" and np.all(diff > 0):
        score += 25
    if direction == "SELL" and np.all(diff < 0):
        score += 25

    # Stability filter
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std / mean < 0.004:
        score += 20

    # Strong push (timing)
    last = np.diff(p[-3:])
    if direction == "BUY" and np.all(last > 0):
        score += 25
    if direction == "SELL" and np.all(last < 0):
        score += 25

    return direction, score

# ----------------------
# TELEGRAM SIGNAL
# ----------------------
def send_signal(pair, direction, accuracy, trend_type):
    arrow = "⬆️" if direction == "BUY" else "⬇️"
    msg = f"""🔥 ELITE SIGNAL 🔥

Pair: {pair}
Direction: {direction} {arrow}
Type: {trend_type}
Accuracy: {accuracy}%
Expiry: {EXPIRY_MINUTES} min
"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
        logging.info(f"SENT: {pair} {direction} {accuracy}%")
    except Exception as e:
        logging.error(e)

# ----------------------
# GET FOREX SYMBOLS
# ----------------------
async def get_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except Exception as e:
        logging.error(f"Error fetching forex symbols: {e}")
        return []

# ----------------------
# RESILIENT WEBSOCKET LOOP
# ----------------------
async def websocket_loop(symbols):
    global last_signal_time, signal_count_hour, pending_signal, signal_ready

    while True:
        try:
            async with websockets.connect(DERIV_WS, ping_interval=15, ping_timeout=10) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" not in data:
                        continue

                    pair = data["tick"]["symbol"]
                    price = data["tick"]["quote"]
                    prices[pair].append(price)

                    if len(prices[pair]) < 60:
                        continue

                    # Analyze trend
                    direction, score = analyze_pair(prices[pair])
                    if not direction or score < 75:
                        pending_signal = None
                        signal_ready = False
                        continue

                    # Require consecutive tick alignment
                    if pending_signal and pending_signal[0] == pair and pending_signal[1] == direction:
                        signal_ready = True
                    else:
                        pending_signal = (pair, direction, score)
                        signal_ready = False

                    # Send signal only when ready
                    if signal_ready:
                        if signal_count_hour >= 2:
                            continue
                        now = datetime.now(TIMEZONE)
                        if (now - last_signal_time).total_seconds() < EXPIRY_MIN_INTERVAL := MIN_SIGNAL_INTERVAL:
                            continue

                        accuracy = min(95, int(score))
                        trend_type = "Stable Trend" if score < 90 else "Strong Breakout"

                        send_signal(pair, direction, accuracy, trend_type)
                        last_signal_time = datetime.now(TIMEZONE)
                        signal_count_hour += 1

                        pending_signal = None
                        signal_ready = False

                        # Wait for expiry before next signal
                        await asyncio.sleep(EXPIRY_MINUTES * 60)

        except (websockets.ConnectionClosed, websockets.InvalidStatusCode, asyncio.TimeoutError, AttributeError) as e:
            logging.error(f"WebSocket error, reconnecting: {e}")
            await asyncio.sleep(3)  # reconnect after short delay

# ----------------------
# MAIN LOOP
# ----------------------
async def system_loop():
    global last_hour
    while True:
        now = datetime.now(TIMEZONE)
        if last_hour != now.hour:
            signal_count_hour = 0
            last_hour = now.hour

        weekday = now.weekday()
        hour = now.hour

        if (weekday == 4 and hour >= 21) or weekday in [5,6]:
            symbols = CRYPTO_PAIRS
        else:
            symbols = await get_symbols()

        await websocket_loop(symbols)

# ----------------------
# RUN SYSTEM
# ----------------------
asyncio.run(system_loop())
