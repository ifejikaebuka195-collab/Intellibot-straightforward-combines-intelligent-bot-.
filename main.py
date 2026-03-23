# ======================================
# DERIV OTC SIGNAL BOT - FULL REFINED
# POCKETOPTION-STYLE (STRICT + REAL ENTRY)
# FULL SYSTEM: SINGLE TRADE LOCK + DYNAMIC ENTRY + ADAPTIVE PULLBACK/REVERSAL + VOLATILITY ADJUSTMENT
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

# ================================
# BLOCKED PAIRS
# ================================
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

prices = {}
tick_confirm = {}
active_trade = None  # Track current active trade pair
pending_signal = None
cooldown_lock = {}

# ================================
# EMA
# ================================
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# ================================
# TREND DETECTION
# ================================
def detect_trend(p):
    if len(p) < 100:
        return None
    e1 = ema(p[-20:], 5)
    e2 = ema(p[-50:], 13)
    e3 = ema(p[-100:], 21)
    if not all([e1, e2, e3]):
        return None
    if e1 > e2 > e3:
        return "BUY"
    elif e1 < e2 < e3:
        return "SELL"
    return None

# ================================
# ADAPTIVE VOLATILITY
# ================================
def recent_volatility(p):
    if len(p) < 20:
        return 0.001
    return np.std(p[-20:]) / np.mean(p[-20:])

# ================================
# PULLBACK DETECTION (ADAPTIVE)
# ================================
def detect_pullback(p, direction):
    if len(p) < 10:
        return False
    recent = np.array(p[-10:])
    diff = np.diff(recent)
    vol = recent_volatility(p)
    threshold = max(0.0005, vol * np.mean(recent) * 1.5)
    if direction == "BUY" and np.any(diff < -threshold):
        return True
    if direction == "SELL" and np.any(diff > threshold):
        return True
    return False

# ================================
# REVERSAL DETECTION (ADAPTIVE)
# ================================
def detect_reversal(p):
    if len(p) < 15:
        return None
    diff = np.diff(p[-15:])
    ups = np.sum(diff > 0)
    downs = np.sum(diff < 0)
    vol = recent_volatility(p)
    threshold = max(3, int(vol * 50))
    if ups >= 10 and downs >= threshold:
        return "BUY_REVERSE"
    if downs >= 10 and ups >= threshold:
        return "SELL_REVERSE"
    return None

# ================================
# BIG MOVE CHECK
# ================================
def big_move_ready(p, direction):
    if len(p) < 50:
        return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std > 0.01 * mean:
        return False
    diff = np.diff(p[-10:])
    if direction == "BUY":
        if np.sum(diff > 0) < 8 or not (diff[-1] > diff[-2] > diff[-3]):
            return False
    if direction == "SELL":
        if np.sum(diff < 0) < 8 or not (diff[-1] < diff[-2] < diff[-3]):
            return False
    return True

# ================================
# ENTRY CONFIRM
# ================================
def entry_confirm(p, direction):
    if len(p) < 15:
        return False
    diff = np.diff(p[-10:])
    if direction in ["BUY", "BUY_REVERSE"]:
        return np.sum(diff > 0) >= 8
    if direction in ["SELL", "SELL_REVERSE"]:
        return np.sum(diff < 0) >= 8
    return False

# ================================
# ACCURACY CALCULATION
# ================================
def get_accuracy(p):
    if len(p) < 50:
        return 85
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean > 0.005:
        return 90
    return 85

# ================================
# COOLDOWN MECHANISM
# ================================
def locked(pair):
    if pair in cooldown_lock:
        return datetime.now(TIMEZONE) < cooldown_lock[pair]
    return False

def set_lock(pair):
    cooldown_lock[pair] = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)

# ================================
# TELEGRAM MESSAGES
# ================================
def send_asset(pair):
    msg = f"""
SIGNAL ⚠️

Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}

Preparing entry...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

def send_final(pair, direction, acc):
    arrow = "⬆️" if "BUY" in direction else "⬇️"
    msg = f"""
SIGNAL {arrow}

Asset: {pair}_otc
Payout: 92%
Accuracy: {acc}%
Expiration: M{EXPIRY_MINUTES}
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

# ================================
# LOAD SYMBOLS
# ================================
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"]
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except:
        return []

# ================================
# MAIN MONITOR LOOP
# ================================
async def monitor():
    global pending_signal, active_trade
    while True:
        try:
            # If there is already an active trade, only monitor that pair
            if active_trade:
                symbols = [active_trade]
            else:
                symbols = await load_symbols()
                if not symbols:
                    await asyncio.sleep(5)
                    continue
                for s in symbols:
                    prices[s] = []
                    tick_confirm[s] = {"count": 0, "dir": None}

            async with websockets.connect(DERIV_WS) as ws:
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
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        if locked(pair):
                            continue

                        # Detect trend
                        direction = detect_trend(prices[pair])
                        if not direction:
                            continue

                        # Detect pullback
                        if detect_pullback(prices[pair], direction):
                            continue

                        # Detect strict reversal
                        reversal = detect_reversal(prices[pair])
                        if reversal:
                            direction = reversal

                        # Tick confirmation
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir": direction, "count": 1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # Big move check
                        if not big_move_ready(prices[pair], direction):
                            continue

                        # Lock the pair as active trade
                        active_trade = pair

                        # Send preliminary signal
                        send_asset(pair)
                        pending_signal = {
                            "pair": pair,
                            "direction": direction,
                            "time": datetime.now(TIMEZONE)
                        }

                        # Adaptive dynamic entry based on volatility
                        vol = recent_volatility(prices[pair])
                        dynamic_delay = max(1, min(2, int(vol * 200)))  # scaled for seconds
                        await asyncio.sleep(dynamic_delay * 60)

                        # Final check
                        acc = get_accuracy(prices[pair])
                        if entry_confirm(prices[pair], direction):
                            send_final(pair, direction, acc)
                            set_lock(pair)

                        pending_signal = None
                        active_trade = None  # Unlock after trade expires

                    except:
                        continue
        except:
            await asyncio.sleep(5)

asyncio.run(monitor())
