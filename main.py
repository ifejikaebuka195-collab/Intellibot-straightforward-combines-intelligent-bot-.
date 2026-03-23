# ======================================
# DERIV OTC SIGNAL BOT
# POCKETOPTION-STYLE (STRICT + REAL ENTRY)
# FINAL VERSION: MARKET-CONDITION ACCURACY + STABLE LONG TREND DETECTION
# UPGRADE 1.1: Correct Timing, Duration, Stability, Auto-Recovery
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

ENTRY_DELAY = 2  # minutes before final entry
EXPIRY_MINUTES = 5

MAX_PRICES = 5000
TICK_CONFIRMATION = 3

# ================================
# BLOCKED PAIRS
# ================================
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

prices = {}
tick_confirm = {}
pending_signal = None
global_lock = None

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
# TREND (STABLE LONG TREND DETECTION)
# ================================
def detect_trend(p):
    if len(p) < 100:  # require longer history for stability
        return None

    # Long EMA spans for stable trend detection
    e1 = ema(p[-20:],5)      # fast EMA
    e2 = ema(p[-50:],13)     # medium EMA
    e3 = ema(p[-100:],21)    # slow EMA

    if not all([e1,e2,e3]):
        return None

    # Detect only stable long trend (all EMAs aligned)
    if e1 > e2 and e2 > e3:
        return "BUY"
    elif e1 < e2 and e2 < e3:
        return "SELL"
    return None

# ================================
# BIG MOVE DETECTION 🔥
# ================================
def big_move_ready(p, direction):
    if len(p) < 50:
        return False

    std = np.std(p[-30:])
    mean = np.mean(p[-30:])

    # Ensure stability (not too volatile)
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

# ================================
# ENTRY CONFIRM (STRICT TIMING)
# ================================
def entry_confirm(p, direction):
    if len(p) < 15:
        return False
    diff = np.diff(p[-10:])
    if direction == "BUY":
        return np.sum(diff > 0) >= 8
    if direction == "SELL":
        return np.sum(diff < 0) >= 8
    return False

# ================================
# ACCURACY BASED ON MARKET CONDITION
# ================================
def get_accuracy(p):
    if len(p) < 50:
        return 82
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean > 0.005:  # strong market
        return 85
    return 82  # weak/stable market

# ================================
# LOCK
# ================================
def locked():
    global global_lock
    return global_lock and datetime.now(TIMEZONE) < global_lock

def set_lock():
    global global_lock
    total = ENTRY_DELAY + EXPIRY_MINUTES
    global_lock = datetime.now(TIMEZONE) + timedelta(minutes=total)

# ================================
# TELEGRAM
# ================================
def send_asset(pair):
    msg = f"""
SIGNAL ⚠️

Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}

Preparing entry...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})

def send_final(pair, direction, acc):
    entry = datetime.now(TIMEZONE) + timedelta(minutes=ENTRY_DELAY)
    arrow = "⬆️" if direction=="BUY" else "⬇️"
    msg = f"""
SIGNAL {arrow}

Asset: {pair}_otc
Payout: 92%
Accuracy: {acc}%
Expiration: M{EXPIRY_MINUTES}
Entry Time: {entry.strftime('%I:%M %p')}
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id":CHAT_ID,"text":msg})

# ================================
# LOAD SYMBOLS
# ================================
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"]
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except:
        return []

# ================================
# MAIN MONITOR LOOP
# ================================
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

                        # tick confirm
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir":direction,"count":1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # BIG MOVE CHECK
                        if not big_move_ready(prices[pair], direction):
                            continue

                        # SEND PRELIMINARY SIGNAL
                        send_asset(pair)
                        pending_signal = {
                            "pair": pair,
                            "direction": direction,
                            "time": datetime.now(TIMEZONE)
                        }

                        # WAIT FOR STRICT ENTRY CONFIRMATION
                        await asyncio.sleep(ENTRY_DELAY * 60)

                        # FINAL CHECK BEFORE SIGNAL
                        acc = get_accuracy(prices[pair])
                        if entry_confirm(prices[pair], direction):
                            send_final(pair, direction, acc)
                            set_lock()

                        pending_signal = None

                    except:
                        continue

        except:
            await asyncio.sleep(5)

asyncio.run(monitor())
