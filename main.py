import asyncio
import json
import requests
import websockets
from datetime import datetime, timedelta
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
TICK_CONFIRMATION = 3

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
tick_confirm = defaultdict(lambda: {"count": 0, "dir": None})
last_signal_time = datetime.min.replace(tzinfo=TIMEZONE)
signal_count_hour = 0
last_hour = None
pending_signal = None
signal_ready = False
global_lock = None

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
        logging.error(f"Telegram error: {e}")

# ----------------------
# LOCK
# ----------------------
def locked():
    global global_lock
    return global_lock and datetime.now(TIMEZONE) < global_lock

def set_lock():
    global global_lock
    total = EXPIRY_MINUTES
    global_lock = datetime.now(TIMEZONE) + timedelta(minutes=total)

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
# SYSTEM LOOP WITH ROBUST WEBSOCKET
# ----------------------
async def system_loop():
    global last_signal_time, signal_count_hour, last_hour, pending_signal, signal_ready

    while True:
        now = datetime.now(TIMEZONE)

        # Reset hourly counter
        if last_hour != now.hour:
            signal_count_hour = 0
            last_hour = now.hour

        weekday = now.weekday()
        hour = now.hour

        # Determine symbols to track
        symbols = CRYPTO_PAIRS if (weekday == 4 and hour >= 21) or weekday in [5,6] else await get_symbols()

        while True:
            try:
                async with websockets.connect(DERIV_WS) as ws:
                    # Subscribe to all symbols
                    for s in symbols:
                        await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if "tick" not in data:
                                continue

                            pair = data["tick"]["symbol"]
                            price = data["tick"]["quote"]
                            prices[pair].append(price)

                            if len(prices[pair]) < 60:
                                continue

                            # Trend analysis
                            direction, score = analyze_pair(prices[pair])
                            if not direction or score < 75:
                                pending_signal = None
                                signal_ready = False
                                continue

                            # Tick confirmation
                            if tick_confirm[pair]["dir"] == direction:
                                tick_confirm[pair]["count"] += 1
                            else:
                                tick_confirm[pair] = {"dir": direction, "count": 1}

                            if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                                continue

                            # Only send when consecutive confirmation
                            if pending_signal and pending_signal[0] == pair and pending_signal[1] == direction:
                                signal_ready = True
                            else:
                                pending_signal = (pair, direction, score)
                                signal_ready = False

                            if signal_ready:
                                # Limit signals per hour
                                if signal_count_hour >= 2:
                                    continue

                                # Minimum interval
                                if (now - last_signal_time).total_seconds() < MIN_SIGNAL_INTERVAL:
                                    continue

                                accuracy = min(95, int(score))
                                trend_type = "Stable Trend" if score < 90 else "Strong Breakout"

                                send_signal(pair, direction, accuracy, trend_type)

                                last_signal_time = datetime.now(TIMEZONE)
                                signal_count_hour += 1

                                pending_signal = None
                                signal_ready = False

                                # Lock for expiry
                                set_lock()

                                # Wait for expiry
                                await asyncio.sleep(EXPIRY_MINUTES * 60)

                        except Exception as e_inner:
                            logging.error(f"Tick processing error: {e_inner}")
                            continue

            except Exception as e_outer:
                logging.error(f"WebSocket reconnecting due to: {e_outer}")
                await asyncio.sleep(5)

# ----------------------
# RUN SYSTEM
# ----------------------
asyncio.run(system_loop())
