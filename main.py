# ======================================
# DERIV OTC SIGNAL BOT - PRO VERSION
# POCKETOPTION STYLE (BALANCED ENGINE)
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import logging

# ---------------- CONFIG ----------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
COOLDOWN_MINUTES = 5
MAX_PRICES = 1000

# ---------------- STATE ----------------
prices = {}
last_signal_time = None
active_pair = None
observing = False
observation_start = None

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)

# ---------------- EMA ----------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2/(period+1)
    val = data[0]
    for p in data:
        val = p*k + val*(1-k)
    return val

# ---------------- TREND ----------------
def trend_direction(p):
    if len(p) < 120:
        return None
    
    e1 = ema(p[-30:], 5)
    e2 = ema(p[-60:], 10)
    e3 = ema(p[-120:], 20)

    if not all([e1, e2, e3]):
        return None

    if e1 > e2 > e3:
        return "BUY"
    if e1 < e2 < e3:
        return "SELL"
    return None

# ---------------- STABILITY ----------------
def is_stable(p):
    std = np.std(p[-40:])
    mean = np.mean(p[-40:])
    return (std / mean) < 0.0045

# ---------------- MOMENTUM ----------------
def momentum_strength(p, direction):
    diff = np.diff(p[-20:])
    if direction == "BUY":
        return np.sum(diff > 0)
    else:
        return np.sum(diff < 0)

# ---------------- PULLBACK ----------------
def pullback_valid(p, direction):
    diff = np.diff(p[-12:])
    
    if direction == "BUY":
        return diff[-4] < 0 and diff[-3] < 0 and diff[-2] > 0 and diff[-1] > 0
    else:
        return diff[-4] > 0 and diff[-3] > 0 and diff[-2] < 0 and diff[-1] < 0

# ---------------- PROBABILITY SCORE ----------------
def score_pair(p, direction):
    score = 0
    
    momentum = momentum_strength(p, direction)
    if momentum >= 14:
        score += 30
    elif momentum >= 10:
        score += 20

    std = np.std(p[-40:])
    mean = np.mean(p[-40:])
    
    if std/mean < 0.003:
        score += 30
    elif std/mean < 0.005:
        score += 20

    diff = np.diff(p[-25:])
    if direction == "BUY":
        consistency = np.sum(diff > 0)
    else:
        consistency = np.sum(diff < 0)

    score += consistency * 2

    return min(score, 100)

# ---------------- TELEGRAM ----------------
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

# ---------------- SYMBOLS ----------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# ---------------- MAIN ----------------
async def monitor():
    global last_signal_time, active_pair, observing, observation_start

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
            if last_signal_time and (now - last_signal_time).total_seconds() < COOLDOWN_MINUTES*60:
                continue

            direction = trend_direction(prices[pair])
            if not direction:
                continue

            if not is_stable(prices[pair]):
                continue

            score = score_pair(prices[pair], direction)

            # PICK BEST PAIR
            if not observing and score >= 70:
                active_pair = pair
                observing = True
                observation_start = now
                send_asset(pair)
                continue

            # OBSERVATION PHASE
            if observing and pair == active_pair:

                # wait at least some seconds before entry
                if (now - observation_start).total_seconds() < 20:
                    continue

                if score < 75:
                    continue

                if not pullback_valid(prices[pair], direction):
                    continue

                # 5-minute alignment
                if now.minute % 5 != 0:
                    continue

                acc = max(82, min(88, int(score)))

                send_signal(pair, direction, acc)

                last_signal_time = now
                observing = False
                active_pair = None

# ---------------- RUN ----------------
asyncio.run(monitor())
