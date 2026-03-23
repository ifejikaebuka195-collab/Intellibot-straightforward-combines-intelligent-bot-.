# ======================================
# DERIV OTC SIGNAL BOT - FINAL (NO SPAM VERSION)
# REAL MARKET + SINGLE FLOW + TRADE STRENGTH FILTER
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz

BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
MAX_PRICES = 5000
TICK_CONFIRMATION = 3

prices = {}
tick_confirm = {}
active_trade = None
lock_until = None

# ================================
# EMA
# ================================
def ema(data, period):
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# ================================
# TREND
# ================================
def detect_trend(p):
    if len(p) < 100:
        return None
    e1 = ema(p[-20:], 5)
    e2 = ema(p[-50:], 13)
    e3 = ema(p[-100:], 21)
    if e1 > e2 > e3:
        return "BUY"
    if e1 < e2 < e3:
        return "SELL"
    return None

# ================================
# VOLATILITY
# ================================
def volatility(p):
    return np.std(p[-20:]) / np.mean(p[-20:])

# ================================
# TRADE STRENGTH (NEW)
# ================================
def strong_move(p, direction):
    diff = np.diff(p[-15:])
    vol = volatility(p)

    if direction == "BUY":
        return np.sum(diff > 0) >= 10 and vol < 0.006
    if direction == "SELL":
        return np.sum(diff < 0) >= 10 and vol < 0.006
    return False

# ================================
# ENTRY CONFIRM
# ================================
def entry_confirm(p, direction):
    diff = np.diff(p[-10:])
    if direction == "BUY":
        return np.sum(diff > 0) >= 8
    if direction == "SELL":
        return np.sum(diff < 0) >= 8
    return False

# ================================
# TELEGRAM
# ================================
def send_pair(pair):
    msg = f"""
SIGNAL ⚠️

Asset: {pair}_otc
Preparing trade...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

def send_final(pair, direction):
    arrow = "⬆️ BUY" if direction == "BUY" else "⬇️ SELL"
    msg = f"""
SIGNAL {arrow}

Asset: {pair}_otc
Duration: {EXPIRY_MINUTES} minutes
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

# ================================
# LOAD SYMBOLS
# ================================
async def load_symbols():
    async with websockets.connect(DERIV_WS) as ws:
        await ws.send(json.dumps({"active_symbols": "brief"}))
        res = json.loads(await ws.recv())
        return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]

# ================================
# MAIN LOOP
# ================================
async def monitor():
    global active_trade, lock_until

    symbols = await load_symbols()

    for s in symbols:
        prices[s] = []
        tick_confirm[s] = {"dir": None, "count": 0}

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
            if len(prices[pair]) > MAX_PRICES:
                prices[pair].pop(0)

            # LOCK SYSTEM DURING TRADE
            if lock_until and datetime.now(TIMEZONE) < lock_until:
                continue

            if active_trade:
                continue

            # TREND
            direction = detect_trend(prices[pair])
            if not direction:
                continue

            # TICK CONFIRM
            if tick_confirm[pair]["dir"] == direction:
                tick_confirm[pair]["count"] += 1
            else:
                tick_confirm[pair] = {"dir": direction, "count": 1}

            if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                continue

            # STRONG MOVE FILTER
            if not strong_move(prices[pair], direction):
                continue

            # =========================
            # STEP 1: SEND PAIR ONCE
            # =========================
            send_pair(pair)
            active_trade = pair

            # WAIT FOR PERFECT ENTRY
            await asyncio.sleep(30)

            # =========================
            # STEP 2: FINAL SIGNAL
            # =========================
            if entry_confirm(prices[pair], direction):
                send_final(pair, direction)

                # LOCK UNTIL EXPIRY
                lock_until = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)

            # RESET
            active_trade = None

asyncio.run(monitor())
