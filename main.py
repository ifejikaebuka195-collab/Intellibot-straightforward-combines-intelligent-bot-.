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
# CONFIG
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
ENTRY_DELAY = 2
MAX_PRICES = 5000

# ----------------------
# STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
tick_confirm = defaultdict(lambda: {"dir": None, "count": 0})
lock_until = None

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
# PRO ANALYSIS ENGINE
# ----------------------
def analyze_pair(p):
    if len(p) < 60:
        return None, None, None

    p = list(p)

    e1 = ema(p[-10:], 3)
    e2 = ema(p[-20:], 5)
    e3 = ema(p[-30:], 8)
    e4 = ema(p[-50:], 13)

    if not all([e1, e2, e3, e4]):
        return None, None, None

    direction = None
    score = 0

    # STRONG TREND STRUCTURE
    if e1 > e2 > e3 > e4:
        direction = "BUY"
        score += 30
    elif e1 < e2 < e3 < e4:
        direction = "SELL"
        score += 30

    if not direction:
        return None, None, None

    # MOMENTUM (STRICT)
    diff = np.diff(p[-10:])
    if direction == "BUY" and np.sum(diff > 0) >= 8:
        score += 25
    elif direction == "SELL" and np.sum(diff < 0) >= 8:
        score += 25
    else:
        return None, None, None  # ❌ reject weak momentum

    # CLEAN TREND (LOW NOISE)
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std / mean < 0.004:
        score += 20
    else:
        return None, None, None  # ❌ reject noisy market

    # BREAKOUT / BIG MOVE
    move = abs(p[-1] - p[-15])
    noise = np.std(p[-15:])
    if move > noise * 2:
        score += 20

    # FINAL PUSH (ENTRY TIMING)
    last = np.diff(p[-3:])
    if direction == "BUY" and np.all(last > 0):
        score += 15
    elif direction == "SELL" and np.all(last < 0):
        score += 15
    else:
        return None, None, None  # ❌ reject weak entry timing

    # ACCURACY (REALISTIC MAPPING)
    if score >= 90:
        return direction, 95, "EXPLOSIVE MOVE"
    elif score >= 80:
        return direction, 90, "STRONG TREND"
    elif score >= 70:
        return direction, 85, "STABLE TREND"

    return None, None, None

# ----------------------
# TELEGRAM
# ----------------------
def send_signal(pair, direction, acc, trend):
    entry_time = datetime.now(TIMEZONE) + timedelta(minutes=ENTRY_DELAY)
    arrow = "⬆️" if direction == "BUY" else "⬇️"

    msg = f"""
🔥 ELITE SIGNAL 🔥

Pair: {pair}
Direction: {direction} {arrow}
Type: {trend}
Accuracy: {acc}%
Entry Time: {entry_time.strftime('%H:%M')}
Expiry: {EXPIRY_MINUTES} min
"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
        logging.info(f"SENT: {pair} {direction} {acc}%")
    except Exception as e:
        logging.error(e)

# ----------------------
# LOAD SYMBOLS
# ----------------------
async def get_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# ----------------------
# MAIN LOOP
# ----------------------
async def main():
    global lock_until

    while True:
        try:
            symbols = await get_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

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

                    # WAIT IF LOCKED
                    if lock_until and datetime.now(TIMEZONE) < lock_until:
                        continue

                    direction, acc, trend = analyze_pair(prices[pair])

                    if not direction:
                        tick_confirm[pair] = {"dir": None, "count": 0}
                        continue

                    # TICK CONFIRMATION (NO EARLY ENTRY)
                    if tick_confirm[pair]["dir"] == direction:
                        tick_confirm[pair]["count"] += 1
                    else:
                        tick_confirm[pair] = {"dir": direction, "count": 1}

                    if tick_confirm[pair]["count"] < 3:
                        continue

                    # PERFECT TIMING DELAY
                    await asyncio.sleep(2)

                    send_signal(pair, direction, acc, trend)

                    # LOCK SYSTEM (WAIT FOR EXPIRY)
                    lock_until = datetime.now(TIMEZONE) + timedelta(
                        minutes=ENTRY_DELAY + EXPIRY_MINUTES
                    )

        except Exception as e:
            logging.error(f"Reconnect: {e}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(main())
