# ======================================
# FINAL REAL-MONEY OPTIONS AI SIGNAL BOT
# FULLY OPTIMIZED FOR MAX PROFITABILITY
# UPGRADED: 7 CRYPTO PAIRS + LIVE TICKS DISPLAY
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
TICK_CONFIRMATION = 3
COOLDOWN_MINUTES = 2
PRE_NOTIFY_DELAY = 5
BASE_CONFIDENCE = 80
MAX_VOL = 0.008
MIN_VOL = 0.001

TRADE_LOG = "ai_options_final_max_profit.csv"

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
global_lock = False

signals_this_hour = 0
MAX_SIGNALS_PER_HOUR = 2
current_hour = datetime.now(TIMEZONE).hour
last_pair_sent = None

# -------------------
# EMA
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
# MODEL
# -------------------
model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
model_metric = metrics.LogLoss()

# -------------------
# FEATURES
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
# PREDICT
# -------------------
def predict_probability(p):
    features = extract_features(p)
    if not features:
        return 0, None
    prob = model.predict_proba_one(features).get(1, 0.5) * 100
    direction = "BUY" if prob > 50 else "SELL"
    return prob, direction

# -------------------
# MARKET STATE
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
# TELEGRAM
# -------------------
def send_pre_notify(pair, direction, duration_min, duration_sec):
    msg = f"""PRE-NOTIFY: Potential Setup Detected ⏳
Asset: {pair}
Direction: {direction}
Duration: {duration_min} min {duration_sec} sec
Waiting {PRE_NOTIFY_DELAY} seconds before final signal..."""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[PRE] {pair} {direction}")

def send_final_signal(pair, direction, confidence, duration_min, duration_sec, expiry_time):
    msg = f"""AI SIGNAL ✅
Asset: {pair}
Direction: {direction}
Confidence: {confidence:.2f}%
Duration: {duration_min} min {duration_sec} sec
Expiry Time: {expiry_time.strftime('%H:%M:%S')}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[SIGNAL] {pair} {direction} {confidence:.2f}%")

# -------------------
# LOG
# -------------------
def log_signal(pair, direction, entry, confidence, duration_min, duration_sec, expiry_time, vol, state, result="PENDING"):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, entry, confidence,
            duration_min, duration_sec, expiry_time.strftime('%H:%M:%S'), vol, state, result
        ])

# -------------------
# UNLOCK
# -------------------
async def unlock_after(expiry_time):
    global global_lock
    delay = (expiry_time - datetime.now(TIMEZONE)).total_seconds()
    await asyncio.sleep(max(0, delay))
    global_lock = False

# -------------------
# CRYPTO SYMBOLS (7 POPULAR)
# -------------------
CRYPTO_PAIRS = ["frxBTCUSD","frxETHUSD","frxLTCUSD","frxXRPUSD","frxBCHUSD","frxADAUSD","frxDOGEUSD"]

# -------------------
# MAIN LOOP
# -------------------
async def monitor():
    global global_lock, signals_this_hour, current_hour, last_pair_sent

    last_hour_signal = datetime.now() - timedelta(hours=1)

    for s in CRYPTO_PAIRS:
        prices[s] = []
        tick_confirm[s] = {"count": 0, "dir": None}
        symbol_confidence[s] = BASE_CONFIDENCE

    async with websockets.connect(DERIV_WS) as ws:
        for s in CRYPTO_PAIRS:
            await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

        async for msg in ws:
            try:
                data = json.loads(msg)
                if "tick" not in data:
                    continue

                now = datetime.now(TIMEZONE)
                pair = data["tick"]["symbol"]
                price = data["tick"]["quote"]

                prices[pair].append(price)
                if len(prices[pair]) > 2:  # only keep last 2 ticks for display
                    prices[pair].pop(0)

                # -------------------
                # DISPLAY LIVE TICKS
                # -------------------
                ticks_str = ", ".join([f"{p:.2f}" for p in prices[pair]])
                print(f"[TICKS] {pair}: {ticks_str}")

                # -------------------
                # SIGNAL LOGIC (UNCHANGED)
                # -------------------
                if global_lock:
                    continue

                if signals_this_hour >= MAX_SIGNALS_PER_HOUR:
                    continue

                state = market_state(prices[pair])
                if state != "NORMAL":
                    continue

                prob, direction = predict_probability(prices[pair])
                print(f"[READY] {pair} {direction} {prob:.2f}%")

                if prob < symbol_confidence[pair]:
                    continue

                if tick_confirm[pair]["dir"] == direction:
                    tick_confirm[pair]["count"] += 1
                else:
                    tick_confirm[pair] = {"dir": direction, "count": 1}

                if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                    continue

                if pair == last_pair_sent:
                    continue

                vol = np.std(prices[pair][-2:])
                total_seconds = 120  # fixed 2-min duration for crypto signals
                duration_min = total_seconds // 60
                duration_sec = total_seconds % 60
                expiry_time = now + timedelta(seconds=total_seconds)

                send_pre_notify(pair, direction, duration_min, duration_sec)
                await asyncio.sleep(PRE_NOTIFY_DELAY)

                entry = prices[pair][-1]
                send_final_signal(pair, direction, prob, duration_min, duration_sec, expiry_time)
                log_signal(pair, direction, entry, prob, duration_min, duration_sec, expiry_time, vol, state)

                signals_this_hour += 1
                last_pair_sent = pair

                global_lock = True
                asyncio.create_task(unlock_after(expiry_time))
                last_hour_signal = now

            except Exception as e:
                print("[ERROR] Tick:", e)

# -------------------
# RUN
# -------------------
asyncio.run(monitor())
