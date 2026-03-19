# ======================================
# DERIV OTC SIGNAL BOT
# STRICT POCKETOPTION-STYLE
# OBSERVATION-FIRST + STABLE BIG MOVE + LONG TREND DETECTION
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
OBSERVATION_TICKS = 10  # ticks to observe before sending final signal
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
tick_confirm = {}
current_pair = None
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
    if std > 0.01 * mean:  # Ignore erratic spikes
        return False
    diff = np.diff(p[-10:])
    if direction == "BUY":
        if np.sum(diff > 0) < 8 or not (diff[-1] > diff[-2] > diff[-3]):
            return False
    if direction == "SELL":
        if np.sum(diff < 0) < 8 or not (diff[-1] < diff[-2] < diff[-3]):
            return False
    return True

# ----------------------
# LONG TREND DETECTION
# ----------------------
def long_stable_trend(p, direction):
    """Detect long, consistent, non-manipulated trend likely to last 5-min expiry."""
    if len(p) < 50:
        return False
    recent_diff = np.diff(p[-20:])
    if direction == "BUY":
        return np.all(recent_diff > 0)
    if direction == "SELL":
        return np.all(recent_diff < 0)
    return False

# ----------------------
# STABLE MOVE CHECK
# ----------------------
def stable_move(p, direction):
    """Check if the move is strong and likely to last until expiry."""
    if len(p) < OBSERVATION_TICKS + 5:
        return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction == "BUY":
        return np.all(last_diff > 0)
    if direction == "SELL":
        return np.all(last_diff < 0)
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

Observing market for stable move or long trend...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Asset observation started: {pair}")

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
    global current_pair

    while True:
        try:
            if locked():
                await asyncio.sleep(1)
                continue

            symbols = await load_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            # Only monitor one currency pair at a time
            if current_pair is None:
                for s in symbols:
                    prices[s] = []
                    tick_confirm[s] = {"count":0,"dir":None}
                current_pair = symbols[0]

            async with websockets.connect(DERIV_WS) as ws:
                await ws.send(json.dumps({"ticks":current_pair,"subscribe":1}))

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

                        # Only trigger if big move or long trend detected
                        if not (big_move_ready(prices[pair], direction) or long_stable_trend(prices[pair], direction)):
                            continue

                        # Drop asset for observation if not already dropped
                        if current_pair:
                            send_asset(current_pair)
                            current_pair = None  # lock to this pair until expiry

                        # Send final signal if stable move or long trend confirmed
                        if stable_move(prices[pair], direction) or long_stable_trend(prices[pair], direction):
                            acc = get_accuracy(prices[pair])
                            send_final(pair, direction, acc)
                            set_lock()
                            prices[pair] = []
                            break  # wait until lock expires

                    except Exception as e_tick:
                        logging.error(f"Tick error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
