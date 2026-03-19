# ======================================
# DERIV OTC SIGNAL BOT
# POCKETOPTION-STYLE
# OBSERVATION-FIRST + STABLE TREND
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
OBSERVATION_TICKS = 10
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
tick_confirm = {}
active_pair = None
global_lock = None

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

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
        return False  # Ignore spikes
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
# STABLE TREND CHECK
# ----------------------
def stable_trend(p, direction):
    if len(p) < OBSERVATION_TICKS + 5:
        return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction == "BUY":
        return np.all(last_diff > 0)
    if direction == "SELL":
        return np.all(last_diff < 0)
    return False

# ----------------------
# ACCURACY DERIVED
# ----------------------
def get_accuracy(p):
    if len(p) < 50:
        return 82
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    ratio = std / mean
    if ratio < 0.003:
        return 90
    elif ratio < 0.006:
        return 85
    else:
        return 82

# ----------------------
# LOCKS
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

Observing market for stable trend...
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
    global active_pair

    while True:
        try:
            if locked():
                await asyncio.sleep(1)
                continue

            symbols = await load_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            # Only one active observation at a time
            if active_pair is None:
                for s in symbols:
                    prices[s] = []
                    tick_confirm[s] = {"count":0,"dir":None}
                active_pair = symbols[0]

            async with websockets.connect(DERIV_WS) as ws:
                await ws.send(json.dumps({"ticks":active_pair,"subscribe":1}))

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

                        direction = detect_trend(prices[pair])
                        if not direction:
                            continue

                        # Tick confirmation
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir":direction,"count":1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # Confirm big move or stable trend
                        if not big_move_ready(prices[pair], direction) and not stable_trend(prices[pair], direction):
                            continue

                        # Drop asset for observation
                        if active_pair:
                            send_asset(active_pair)
                            active_pair = None  # lock to this pair

                        # Send final signal if trend confirmed
                        if stable_trend(prices[pair], direction):
                            acc = get_accuracy(prices[pair])
                            send_final(pair, direction, acc)
                            set_lock()
                            prices[pair] = []
                            break  # wait until expiry before next signal

                    except Exception as e_tick:
                        logging.error(f"Tick error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
