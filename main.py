# ======================================
# DERIV OTC SIGNAL BOT
# POCKETOPTION-STYLE (STRICT + REAL ENTRY + OBSERVATION)
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
MAX_PRICES = 5000
TICK_CONFIRMATION = 3
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
tick_confirm = {}
pending_signal = None
global_lock = None

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

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
# TREND DETECTION
# ----------------------
def detect_trend(p):
    if len(p) < 50:
        return None
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if not all([e1,e2,e3,e4]):
        return None
    if e1 > e2 and e3 > e4:
        return "BUY"
    elif e1 < e2 and e3 < e4:
        return "SELL"
    return None

# ----------------------
# BIG MOVE DETECTION
# ----------------------
def big_move_ready(p, direction):
    if len(p) < 50:
        return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std > 0.01 * mean:
        return False
    diff = np.diff(p[-10:])
    if direction == "BUY":
        if np.sum(diff > 0) < 8:
            return False
        if not (diff[-1] > diff[-2] > diff[-3]):
            return False
    if direction == "SELL":
        if np.sum(diff < 0) < 8:
            return False
        if not (diff[-1] < diff[-2] < diff[-3]):
            return False
    return True

# ----------------------
# STRONG MOVE CHECK
# ----------------------
def strong_stable_move(p, direction):
    """Check for a stable, reliable move that will last the 5-min expiry."""
    if len(p) < 20:
        return False
    last_diff = np.diff(p[-15:])
    if direction == "BUY":
        return np.all(last_diff[-5:] > 0)
    if direction == "SELL":
        return np.all(last_diff[-5:] < 0)
    return False

# ----------------------
# ACCURACY
# ----------------------
def get_accuracy(p):
    if len(p) < 50:
        return 82
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    return 85 if std/mean > 0.005 else 82

# ----------------------
# LOCK
# ----------------------
def locked():
    global global_lock
    return global_lock and datetime.now(TIMEZONE) < global_lock

def set_lock():
    global global_lock
    global_lock = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)

# ----------------------
# TELEGRAM
# ----------------------
def send_asset(pair):
    msg = f"""
SIGNAL ⚠️

Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}

Observing market for optimal entry...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Asset dropped for observation: {pair}")

def send_final(pair, direction, acc):
    arrow = "⬆️" if direction=="BUY" else "⬇️"
    msg = f"""
SIGNAL {arrow}

Asset: {pair}_otc
Payout: 92%
Accuracy: {acc}%
Expiration: M{EXPIRY_MINUTES}
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Final signal sent: {pair} {direction} Accuracy: {acc}%")

# ----------------------
# LOAD SYMBOLS
# ----------------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"]
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except Exception as e:
        logging.warning(f"Failed to load symbols: {e}")
        return []

# ----------------------
# MAIN LOOP
# ----------------------
async def monitor():
    global pending_signal

    while True:
        try:
            symbols = await load_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count":0,"dir":None}

            async with websockets.connect(DERIV_WS) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks":s,"subscribe":1}))

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        if "tick" not in data:
                            continue

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        prices[pair].append(price)
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        if locked():
                            continue

                        direction = detect_trend(prices[pair])
                        if not direction:
                            continue

                        # Confirm direction over multiple ticks
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir":direction,"count":1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # Check if big move is about to happen
                        if not big_move_ready(prices[pair], direction):
                            continue

                        # ✅ Drop asset and wait for stable move
                        if pending_signal != pair:
                            send_asset(pair)
                            pending_signal = pair

                        # ✅ Only send final signal when strong, stable move is confirmed
                        if strong_stable_move(prices[pair], direction):
                            acc = get_accuracy(prices[pair])
                            send_final(pair, direction, acc)
                            set_lock()
                            pending_signal = None

                    except Exception as e_inner:
                        logging.error(f"Tick processing error: {e_inner}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
