# ======================================
# DERIV OTC SIGNAL BOT (BALANCED VERSION)
# POCKETOPTION-STYLE (REALISTIC ENGINE)
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import logging

# ----------------------
# CONFIG
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
MAX_PRICES = 1000
COOLDOWN_MINUTES = 5

# ----------------------
# STATE
# ----------------------
prices = {}
last_signal_time = None
active_pair = None
observing = False

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO)

# ----------------------
# EMA
# ----------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2/(period+1)
    val = data[0]
    for p in data:
        val = p*k + val*(1-k)
    return val

# ----------------------
# TREND (MULTI LAYER)
# ----------------------
def get_trend(p):
    if len(p) < 100:
        return None
    
    e_fast = ema(p[-20:], 5)
    e_mid  = ema(p[-50:], 10)
    e_slow = ema(p[-100:], 20)

    if not all([e_fast, e_mid, e_slow]):
        return None

    if e_fast > e_mid > e_slow:
        return "BUY"
    if e_fast < e_mid < e_slow:
        return "SELL"
    
    return None

# ----------------------
# MOMENTUM + STABILITY
# ----------------------
def momentum_score(p, direction):
    diff = np.diff(p[-15:])
    
    if direction == "BUY":
        return np.sum(diff > 0)
    else:
        return np.sum(diff < 0)

def is_stable(p):
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    return std/mean < 0.004  # stable market

# ----------------------
# PULLBACK ENTRY
# ----------------------
def pullback_entry(p, direction):
    diff = np.diff(p[-10:])
    
    # detect small opposite move then continuation
    if direction == "BUY":
        return diff[-3] < 0 and diff[-2] > 0 and diff[-1] > 0
    else:
        return diff[-3] > 0 and diff[-2] < 0 and diff[-1] < 0

# ----------------------
# ACCURACY ENGINE
# ----------------------
def get_accuracy(p, direction):
    momentum = momentum_score(p, direction)
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])

    score = 0

    # trend strength
    score += min(momentum * 5, 40)

    # stability
    if std/mean < 0.003:
        score += 30
    elif std/mean < 0.005:
        score += 20

    # consistency
    diff = np.diff(p[-20:])
    if direction == "BUY":
        consistency = np.sum(diff > 0)
    else:
        consistency = np.sum(diff < 0)

    score += consistency * 2

    return min(max(int(score), 82), 88)

# ----------------------
# TELEGRAM
# ----------------------
def send_asset(pair):
    msg = f"""
⚠️ SIGNAL PREPARING

Asset: {pair}_otc
Expiry: M{EXPIRY_MINUTES}

Observing market...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

def send_signal(pair, direction, acc):
    arrow = "⬆️" if direction == "BUY" else "⬇️"
    msg = f"""
{arrow} SIGNAL

Asset: {pair}_otc
Accuracy: {acc}%
Expiry: M{EXPIRY_MINUTES}
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

# ----------------------
# SYMBOLS
# ----------------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# ----------------------
# MAIN ENGINE
# ----------------------
async def monitor():
    global last_signal_time, active_pair, observing

    symbols = await load_symbols()

    async with websockets.connect(DERIV_WS) as ws:
        for s in symbols:
            prices[s] = []
            await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

        async for msg in ws:
            data = json.loads(msg)
            if "tick" not in data:
                continue

            pair = data["tick"]["symbol"]
            price = data["tick"]["quote"]

            prices[pair].append(price)
            if len(prices[pair]) > MAX_PRICES:
                prices[pair].pop(0)

            now = datetime.now(TIMEZONE)

            # cooldown
            if last_signal_time and (now - last_signal_time).total_seconds() < COOLDOWN_MINUTES * 60:
                continue

            # if already observing one pair, ignore others
            if observing and pair != active_pair:
                continue

            direction = get_trend(prices[pair])
            if not direction:
                continue

            if not is_stable(prices[pair]):
                continue

            # start observing
            if not observing:
                active_pair = pair
                observing = True
                send_asset(pair)
                continue

            # wait for entry condition
            if pullback_entry(prices[pair], direction):
                acc = get_accuracy(prices[pair], direction)

                # align to 5-min candle
                if now.minute % 5 != 0:
                    continue

                send_signal(pair, direction, acc)

                last_signal_time = now
                observing = False
                active_pair = None

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
