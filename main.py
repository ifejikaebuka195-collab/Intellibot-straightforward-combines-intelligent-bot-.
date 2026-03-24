# ======================================
# FINAL REAL-MONEY OPTIONS AI SIGNAL BOT
# PRECISE TIME DURATION + GLOBAL LOCK + HOURLY GUARANTEE + VOLATILITY DYNAMIC
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import csv
import os
from river import linear_model, preprocessing, metrics

# -------------------
# CONFIG
# -------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

MAX_PRICES = 5000
TICK_CONFIRMATION = 2
COOLDOWN_MINUTES = 2
PRE_NOTIFY_DELAY = 5
BASE_CONFIDENCE = 75
MAX_VOL = 0.008
MIN_VOL = 0.001

TRADE_LOG = "ai_options_final.csv"

# -------------------
# INIT LOG
# -------------------
if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        csv.writer(f).writerow([
            "time","pair","dir","entry","confidence","duration_min",
            "duration_sec","expiry_time","volatility","market_state","result"
        ])

# -------------------
# GLOBALS
# -------------------
prices = {}
tick_confirm = {}
cooldowns = {}
pending_signal = {}
symbol_confidence = {}
global_lock = False  # prevents multiple signals at the same time

# -------------------
# EMA UTILITY
# -------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# -------------------
# ONLINE AI MODEL
# -------------------
model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
model_metric = metrics.LogLoss()

# -------------------
# FEATURE EXTRACTION
# -------------------
def extract_features(p):
    if len(p) < 30:
        return None
    returns = (p[-1] - p[-2]) / p[-2]
    volatility = np.std(p[-20:])
    momentum = np.sum(np.diff(p[-10:]))
    trend_strength = abs(ema(p[-20:],5) - ema(p[-50:],13) if len(p) >= 50 else 0)
    vol_spike = (p[-1] - np.mean(p[-10:])) / (np.std(p[-10:]) + 1e-9)
    return {
        "returns": returns,
        "volatility": volatility,
        "momentum": momentum,
        "trend": trend_strength,
        "vol_spike": vol_spike
    }

# -------------------
# PREDICTION
# -------------------
def predict_probability(p):
    features = extract_features(p)
    if not features:
        return 0, None
    prob = model.predict_proba_one(features).get(1, 0.5) * 100
    direction = "BUY" if prob > 50 else "SELL"
    return prob, direction

# -------------------
# MARKET STATE CHECK
# -------------------
def market_state(p):
    if len(p) < 20:
        return "UNKNOWN"
    vol = np.std(p[-20:])
    if vol < MIN_VOL:
        return "LOW_VOL"
    elif vol > MAX_VOL:
        return "HIGH_VOL"
    return "NORMAL"

# -------------------
# TELEGRAM SIGNALS
# -------------------
def send_pre_notify(pair, direction, duration_min, duration_sec):
    msg = f"""PRE-NOTIFY: Potential Setup Detected ⏳
Asset: {pair}
Direction: {direction}
Duration: {duration_min} min {duration_sec} sec
Waiting {PRE_NOTIFY_DELAY} seconds before final signal..."""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[PRE-NOTIFY] {pair} | {direction} | Duration: {duration_min}m {duration_sec}s")

def send_final_signal(pair, direction, confidence, duration_min, duration_sec, expiry_time):
    msg = f"""AI SIGNAL ✅
Asset: {pair}
Direction: {direction}
Confidence: {confidence:.2f}%
Duration: {duration_min} min {duration_sec} sec
Expiry Time: {expiry_time.strftime('%H:%M:%S')}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[SIGNAL SENT] {pair} | {direction} | Confidence: {confidence:.2f}% | Duration: {duration_min}m {duration_sec}s | Expiry: {expiry_time.strftime('%H:%M:%S')}")

# -------------------
# LOGGING
# -------------------
def log_signal(pair, direction, entry, confidence, duration_min, duration_sec, expiry_time, vol, state, result="PENDING"):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, entry, confidence,
            duration_min, duration_sec, expiry_time.strftime('%H:%M:%S'), vol, state, result
        ])

# -------------------
# UNLOCK FUNCTION
# -------------------
async def unlock_after(expiry_time):
    global global_lock
    now = datetime.now(TIMEZONE)
    delay = (expiry_time - now).total_seconds()
    await asyncio.sleep(max(0, delay))
    global_lock = False

# -------------------
# LOAD SYMBOLS
# -------------------
async def load_symbols_ws():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# -------------------
# DYNAMIC EXPIRY MAPPING BASED ON VOLATILITY
# -------------------
def dynamic_expiry_seconds(volatility):
    """
    Map volatility to optimal expiry seconds for options:
    - Low volatility → longer expiry (e.g., 2m30s)
    - High volatility → shorter expiry (e.g., 1m15s)
    """
    if volatility < 0.002:
        return 150  # 2m30s
    elif volatility < 0.004:
        return 105  # 1m45s
    else:
        return 75   # 1m15s

# -------------------
# MAIN MONITOR LOOP
# -------------------
async def monitor():
    global global_lock
    last_hour_signal = datetime.now() - timedelta(hours=1)

    while True:
        try:
            symbols = await load_symbols_ws()
            if not symbols:
                await asyncio.sleep(5)
                continue
            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count": 0, "dir": None}
                pending_signal[s] = None
                symbol_confidence[s] = BASE_CONFIDENCE

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

                        if global_lock:
                            continue
                        if pair in cooldowns and datetime.now(TIMEZONE) < cooldowns[pair]:
                            continue

                        state = market_state(prices[pair])
                        if state != "NORMAL":
                            continue

                        prob, direction = predict_probability(prices[pair])
                        if prob < symbol_confidence[pair]:
                            continue

                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir": direction, "count": 1}
                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # Calculate precise dynamic duration
                        vol = np.std(prices[pair][-20:])
                        total_seconds = dynamic_expiry_seconds(vol)
                        duration_min = total_seconds // 60
                        duration_sec = total_seconds % 60
                        expiry_time = datetime.now(TIMEZONE) + timedelta(seconds=total_seconds)

                        send_pre_notify(pair, direction, duration_min, duration_sec)
                        await asyncio.sleep(PRE_NOTIFY_DELAY)

                        entry = prices[pair][-1]
                        send_final_signal(pair, direction, prob, duration_min, duration_sec, expiry_time)
                        log_signal(pair, direction, entry, prob, duration_min, duration_sec, expiry_time, vol, state)

                        global_lock = True
                        cooldowns[pair] = expiry_time + timedelta(seconds=1)
                        asyncio.create_task(unlock_after(expiry_time))
                        last_hour_signal = datetime.now(TIMEZONE)

                        features = extract_features(prices[pair])
                        if features:
                            target = 1 if direction == "BUY" else 0
                            model.learn_one(features, target)
                            model_metric.update(target, model.predict_one(features))

                        # Hourly signal guarantee
                        if (datetime.now() - last_hour_signal).seconds > 3600 and not global_lock:
                            top_pair = max(symbol_confidence, key=symbol_confidence.get)
                            top_prices = prices[top_pair]
                            if len(top_prices) < 10:
                                continue
                            prob, direction = predict_probability(top_prices)
                            vol = np.std(top_prices[-20:])
                            total_seconds = dynamic_expiry_seconds(vol)
                            duration_min = total_seconds // 60
                            duration_sec = total_seconds % 60
                            expiry_time = datetime.now(TIMEZONE) + timedelta(seconds=total_seconds)
                            send_final_signal(top_pair, direction, prob, duration_min, duration_sec, expiry_time)
                            log_signal(top_pair, direction, top_prices[-1], prob, duration_min, duration_sec, expiry_time, vol, "NORMAL")
                            global_lock = True
                            asyncio.create_task(unlock_after(expiry_time))
                            last_hour_signal = datetime.now(TIMEZONE)

                    except Exception as e:
                        print("[ERROR] Tick:", e)

        except Exception as e:
            print("[ERROR] Main loop:", e)
            await asyncio.sleep(5)

# -------------------
# RUN
# -------------------
asyncio.run(monitor())
