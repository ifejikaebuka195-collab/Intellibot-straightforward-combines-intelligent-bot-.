# ======================================
# PRO SNIPER OTC SIGNAL BOT (UPGRADED)
# ======================================

import asyncio
import json
import requests
import websockets
import logging
import numpy as np
from datetime import datetime, timedelta
import pytz

BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

ENTRY_DELAY = 1
EXPIRY_MINUTES = 2
TICK_CONFIRMATION = 2

MAX_PRICES = 500
RETRY_SECONDS = 5

prices = {}
tick_confirm = {}
active_signal = {"expiry_time": None}

# ================================
# EMA
# ================================
def ema(data, period):
    if len(data) < period:
        return None
    k = 2/(period+1)
    val = data[0]
    for p in data:
        val = p*k + val*(1-k)
    return val

# ================================
# MOMENTUM (STRONG MOVE)
# ================================
def strong_momentum(price_list):
    if len(price_list) < 20:
        return False
    recent = price_list[-10:]
    moves = np.diff(recent)
    strength = np.sum(np.abs(moves))
    return strength > np.std(price_list[-50:]) * 2

# ================================
# BREAK OF STRUCTURE (BOS)
# ================================
def break_of_structure(price_list):
    if len(price_list) < 30:
        return None
    recent_high = max(price_list[-20:])
    recent_low = min(price_list[-20:])
    current = price_list[-1]

    if current > recent_high:
        return "BUY"
    elif current < recent_low:
        return "SELL"
    return None

# ================================
# FAIR VALUE GAP (IMBALANCE)
# ================================
def imbalance(price_list):
    if len(price_list) < 10:
        return False
    gap = abs(price_list[-1] - price_list[-3])
    avg = np.mean(np.abs(np.diff(price_list[-20:])))
    return gap > avg * 2

# ================================
# TREND
# ================================
def detect_trend(price_list):
    if len(price_list) < 100:
        return None,0,0

    ema_fast = ema(price_list,10)
    ema_slow = ema(price_list,20)

    if not ema_fast or not ema_slow:
        return None,0,0

    direction = "BUY" if ema_fast > ema_slow else "SELL"

    strength = abs(ema_fast - ema_slow) / np.std(price_list[-50:]) * 100
    strength = min(strength, 100)

    score = 98 if strength > 80 else 99 if strength > 100 else 0

    return direction,score,strength

# ================================
# SIGNAL FILTER (YOUR MAIN LOGIC)
# ================================
def sniper_entry(price_list):

    direction,score,strength = detect_trend(price_list)

    if direction is None:
        return None,None,None

    bos = break_of_structure(price_list)
    mom = strong_momentum(price_list)
    fvg = imbalance(price_list)

    if bos != direction:
        return None,None,None

    if not mom:
        return None,None,None

    if not fvg:
        return None,None,None

    # FINAL CONFIRMATION (STRONG DURATION)
    recent = np.diff(price_list[-5:])
    if direction == "BUY" and not np.all(recent >= 0):
        return None,None,None
    if direction == "SELL" and not np.all(recent <= 0):
        return None,None,None

    # REAL 98/99
    final_score = 99 if strength > 85 else 98

    return direction,final_score,strength

# ================================
# TELEGRAM
# ================================
def send_signal(pair,direction,score,strength):

    if active_signal["expiry_time"] and datetime.now(TIMEZONE) < active_signal["expiry_time"]:
        return

    now = datetime.now(TIMEZONE)
    entry = now + timedelta(minutes=ENTRY_DELAY)

    active_signal["expiry_time"] = now + timedelta(minutes=3)

    msg = f"""
🚨 SNIPER SIGNAL

PAIR: {pair}
DIRECTION: {direction}
ENTRY: {entry.strftime('%I:%M:%S %p')}
EXPIRY: {EXPIRY_MINUTES}M

CONFIDENCE: {score}%
STRENGTH: {int(strength)}%

⚡ Strong Move Confirmed
⚡ BOS + Imbalance Confirmed
"""

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# ================================
# LOAD SYMBOLS
# ================================
async def load_symbols():
    async with websockets.connect(DERIV_WS) as ws:
        await ws.send(json.dumps({"active_symbols":"brief"}))
        res = json.loads(await ws.recv())
        return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]

# ================================
# MAIN
# ================================
async def main():

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

            direction,score,strength = sniper_entry(prices[pair])

            if direction:
                send_signal(pair,direction,score,strength)

# ================================
# START
# ================================
asyncio.run(main())
