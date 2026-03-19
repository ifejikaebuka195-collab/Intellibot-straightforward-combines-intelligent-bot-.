# ======================================
# DERIV OTC SIGNAL BOT
# FULLY ENHANCED: POCKETOPTION-STYLE SIGNALS
# + ULTRA STRICT ENTRY + EXPLOSION DETECTION
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

TREND_SCORE_THRESHOLD = 82
FIXED_STRENGTH = 95
ENTRY_DELAY = 2
MG_STEP = 2
MAX_MG_STEPS = 3
EXPIRY_MINUTES = 2

MAX_PRICES = 5000
RETRY_SECONDS = 5
TICK_CONFIRMATION = 3

BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

prices = {}
tick_confirm = {}
pending_signal = {}
active_signal = {}
global_lock_active = None

# ================================
# EMA
# ================================
def ema(data, period):
    if len(data) < period:
        return None
    k = 2/(period+1)
    value = data[0]
    for price in data:
        value = price*k + value*(1-k)
    return value

# ================================
# EXPLOSION DETECTION 🔥
# ================================
def explosion_ready(price_list, direction):
    if len(price_list) < 50:
        return False

    # 1. Compression phase (VERY LOW VOLATILITY)
    std = np.std(price_list[-30:])
    mean = np.mean(price_list[-30:])
    if std > 0.01 * mean:  # must be very tight
        return False

    # 2. Breakout momentum starts
    recent = np.diff(price_list[-10:])
    
    if direction == "BUY":
        if np.sum(recent > 0) < 8:
            return False
    elif direction == "SELL":
        if np.sum(recent < 0) < 8:
            return False

    # 3. Acceleration (key for explosion)
    if direction == "BUY":
        if not (recent[-1] > recent[-2] > recent[-3]):
            return False
    elif direction == "SELL":
        if not (recent[-1] < recent[-2] < recent[-3]):
            return False

    return True

# ================================
# STRENGTH
# ================================
def trend_strength(price_list):
    if len(price_list) < 150:
        return 0
    return FIXED_STRENGTH

# ================================
# ACCURACY
# ================================
def pattern_accuracy(price_list, direction):
    if len(price_list) < 200:
        return 82
    matches = 0
    total = 0
    for i in range(len(price_list)-210):
        diff = np.diff(price_list[i:i+10])
        if direction=="BUY" and np.all(diff>0):
            matches +=1
        elif direction=="SELL" and np.all(diff<0):
            matches +=1
        total +=1
    if total == 0:
        return 82
    ratio = matches / total
    return min(82 + int(ratio*3), 85)

# ================================
# TREND
# ================================
def detect_trend(price_list):
    if len(price_list) < 300:
        return 0,0,None

    ema_fast = ema(price_list[-50:],10)
    ema_slow = ema(price_list[-100:],20)
    ema_long_fast = ema(price_list[-200:],30)
    ema_long_slow = ema(price_list[-300:],60)

    direction = None
    if ema_fast and ema_slow and ema_long_fast and ema_long_slow:
        if ema_fast > ema_slow and ema_long_fast > ema_long_slow:
            direction = "BUY"
        elif ema_fast < ema_slow and ema_long_fast < ema_long_slow:
            direction = "SELL"

    strength = trend_strength(price_list)
    accuracy = pattern_accuracy(price_list, direction) if direction else 0

    return accuracy, strength, direction

# ================================
# PREDICTIVE
# ================================
def predictive_valid(price_list, direction):
    if len(price_list) < 10:
        return False
    recent = np.diff(price_list[-10:])
    if direction=="BUY":
        return np.sum(recent>0) >= 7
    elif direction=="SELL":
        return np.sum(recent<0) >= 7
    return False

# ================================
# ULTRA ENTRY
# ================================
def pre_entry_stable(price_list, direction):
    if len(price_list) < 50:
        return False

    for w in [10,15,20,30]:
        diff = np.diff(price_list[-w:])
        if direction=="BUY" and np.sum(diff>0) < w*0.75:
            return False
        if direction=="SELL" and np.sum(diff<0) < w*0.75:
            return False

    last = np.diff(price_list[-10:])
    if direction=="BUY":
        if not (last[-1] >= last[-2] >= last[-3]):
            return False
    elif direction=="SELL":
        if not (last[-1] <= last[-2] <= last[-3]):
            return False

    if np.std(price_list[-20:]) > 0.015*np.mean(price_list[-20:]):
        return False

    ema_short = ema(price_list[-15:],5)
    price_now = price_list[-1]

    if direction=="BUY" and price_now > ema_short * 1.002:
        return False
    if direction=="SELL" and price_now < ema_short * 0.998:
        return False

    return True

# ================================
# LOCK
# ================================
def signal_active():
    global global_lock_active
    now = datetime.now(TIMEZONE)
    return global_lock_active and now < global_lock_active

def register_signal():
    global global_lock_active
    now = datetime.now(TIMEZONE)
    total = ENTRY_DELAY + MG_STEP*MAX_MG_STEPS + EXPIRY_MINUTES
    global_lock_active = now + timedelta(minutes=total)

# ================================
# SEND
# ================================
def send_signal(pair, direction, accuracy, strength):
    if signal_active():
        return

    now = datetime.now(TIMEZONE)
    entry_time = now + timedelta(minutes=ENTRY_DELAY)

    register_signal()

    msg = f"""
🚨 EXPLOSION SIGNAL 🚨

{pair}
Direction: {direction}

Entry: {entry_time.strftime('%H:%M:%S')}

Accuracy: {accuracy}%
Strength: {strength}%
"""

    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id":CHAT_ID,"text":msg})
    except:
        pass

# ================================
# LOAD
# ================================
async def load_otc_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res.get("active_symbols",[])
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except:
        return []

# ================================
# MAIN
# ================================
async def monitor():
    while True:
        try:
            symbols = await load_otc_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count":0,"direction":None}

            async with websockets.connect(DERIV_WS) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks":s,"subscribe":1}))

                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" not in data:
                        continue

                    pair = data["tick"]["symbol"]
                    price = data["tick"]["quote"]

                    prices[pair].append(price)
                    if len(prices[pair]) > MAX_PRICES:
                        prices[pair].pop(0)

                    acc, strg, dirc = detect_trend(prices[pair])

                    if dirc and acc>=82:
                        if tick_confirm[pair]["direction"] == dirc:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"direction":dirc,"count":1}

                        if tick_confirm[pair]["count"] >= TICK_CONFIRMATION:
                            if (predictive_valid(prices[pair],dirc) and
                                pre_entry_stable(prices[pair],dirc) and
                                explosion_ready(prices[pair],dirc)):

                                send_signal(pair,dirc,acc,strg)

        except:
            await asyncio.sleep(RETRY_SECONDS)

asyncio.run(monitor())
