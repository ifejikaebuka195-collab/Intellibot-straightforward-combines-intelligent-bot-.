# ======================================
# FULLY UPGRADED REAL-MONEY AI SIGNAL BOT
# READY FOR DEPLOYMENT WITH MARTINGALE
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
PRE_NOTIFY_DELAY = 5
BASE_CONFIDENCE = 80
MAX_VOL = 0.008
MIN_VOL = 0.001
ENTRY_OFFSET = 2  # minutes ahead for entry
MARTINGALE_INTERVAL = 2  # minutes between Martingale levels

TRADE_LOG = "ai_real_money_martingale.csv"

# -------------------
# INIT LOG
# -------------------

if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        csv.writer(f).writerow([
            "time","pair","dir","entry_time","confidence",
            "expiry_time","volatility","market_state","martingale_level","result"
        ])

# -------------------
# GLOBALS
# -------------------

prices = {}
tick_confirm = {}
cooldowns = {}
symbol_confidence = {}
pair_accuracy = {}
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
model.learn_one({"returns":0,"volatility":0,"momentum":0,"trend":0,"vol_spike":0}, 0.5)
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

def predict_probability(p, pair=None):
    features = extract_features(p)
    if not features:
        return None, None
    prob = model.predict_proba_one(features).get(1, 0) * 100
    if pair and pair in pair_accuracy:
        prob += pair_accuracy[pair] * 5
        prob = min(max(prob,1), 99.9)
    direction = "BUY" if prob >= 50 else "SELL"
    return prob, direction

# -------------------
# MARKET STATE FILTER
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

def send_pre_notify(pair, direction, entry_time):
    msg = f"""PRE-NOTIFY: Potential Setup Detected ⏳
Asset: {pair}
Direction: {direction}
Entry Time: {entry_time.strftime('%H:%M:%S')}
Waiting {PRE_NOTIFY_DELAY} seconds before final signal..."""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[PRE] {pair} {direction} Entry at {entry_time.strftime('%H:%M:%S')}")

def send_final_signal(pair, direction, confidence, entry_time, expiry_time):
    # Calculate Martingale levels
    m1 = entry_time + timedelta(minutes=MARTINGALE_INTERVAL)
    m2 = m1 + timedelta(minutes=MARTINGALE_INTERVAL)
    m3 = m2 + timedelta(minutes=MARTINGALE_INTERVAL)

    msg = f"""🚨TRADE NOW!!

Asset: {pair}
Entry Time: {entry_time.strftime('%H:%M:%S')}
Direction: {direction}
Expiry: {expiry_time.strftime('%H:%M:%S')}
Confidence: {confidence:.2f}%

🎯 Martingale Levels:
🔁 Level 1 → {m1.strftime('%H:%M:%S')}
🔁 Level 2 → {m2.strftime('%H:%M:%S')}
🔁 Level 3 → {m3.strftime('%H:%M:%S')}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[SIGNAL] {pair} {direction} Entry {entry_time.strftime('%H:%M:%S')}")

    # Log all levels
    for level, t in enumerate([entry_time, m1, m2, m3]):
        log_signal(pair, direction, t, confidence, expiry_time, np.std(prices[pair][-20:]), market_state(prices[pair]), level+1)

# -------------------
# LOGGING
# -------------------

def log_signal(pair, direction, entry_time, confidence, expiry_time, vol, state, martingale_level, result="PENDING"):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, entry_time.strftime('%H:%M:%S'), confidence,
            expiry_time.strftime('%H:%M:%S'), vol, state, martingale_level, result
        ])

# -------------------
# PERFORMANCE UPDATE
# -------------------

def update_pair_accuracy(pair, entry, exit_price, direction):
    if direction == "BUY":
        result = 1 if exit_price > entry else -1
    else:
        result = 1 if exit_price < entry else -1
    if pair not in pair_accuracy:
        pair_accuracy[pair] = 0
    pair_accuracy[pair] = max(min(pair_accuracy[pair] + result, 5), -5)
    return result

# -------------------
# TRAIN MODEL
# -------------------

def train_model(pair, entry, exit_price, direction):
    features = extract_features(prices[pair])
    if not features:
        return
    if direction == "BUY":
        label = 1 if exit_price > entry else 0
    else:
        label = 1 if exit_price < entry else 0
    model.learn_one(features, label)

# -------------------
# UNLOCK
# -------------------

async def unlock_after(expiry_time, pair=None, entry=None, direction=None):
    global global_lock
    delay = (expiry_time - datetime.now(TIMEZONE)).total_seconds()
    await asyncio.sleep(max(0, delay))
    if pair and entry is not None and direction is not None:
        exit_price = prices[pair][-1] if prices[pair] else entry
        update_pair_accuracy(pair, entry, exit_price, direction)
        train_model(pair, entry, exit_price, direction)
    global_lock = False

# -------------------
# LOAD SYMBOLS
# -------------------

async def load_symbols_ws():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# -------------------
# ADAPTIVE EXPIRY
# -------------------

def dynamic_expiry_seconds(volatility):
    return 120  # fixed 2 minutes for real-money trading

# -------------------
# MAIN LOOP
# -------------------

async def monitor():
    global global_lock, signals_this_hour, current_hour, last_pair_sent
    crypto_pairs = ["BTCUSD","ETHUSD","LTCUSD","XRPUSD","BCHUSD","ADAUSD","DOGEUSD"]

    while True:
        try:
            symbols = await load_symbols_ws()
            if not symbols:
                await asyncio.sleep(5)
                continue

            symbols = list(set(symbols + crypto_pairs))
            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count":0,"dir":None}
                symbol_confidence[s] = BASE_CONFIDENCE
                pair_accuracy[s] = 0

            async with websockets.connect(DERIV_WS) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks": s,"subscribe":1}))

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        if "tick" not in data:
                            continue

                        now = datetime.now(TIMEZONE)
                        if now.hour != current_hour:
                            current_hour = now.hour
                            signals_this_hour = 0
                            last_pair_sent = None
                            print("[RESET]")

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        prices[pair].append(price)
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        if global_lock or signals_this_hour >= MAX_SIGNALS_PER_HOUR:
                            continue
                        if pair in cooldowns and now < cooldowns[pair]:
                            continue

                        state = market_state(prices[pair])
                        if state != "NORMAL":
                            continue

                        prob,direction = predict_probability(prices[pair], pair)
                        if prob is None:
                            continue

                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir":direction,"count":1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue
                        if pair == last_pair_sent:
                            continue

                        # Calculate entry time 2 minutes ahead
                        entry_time = now + timedelta(minutes=ENTRY_OFFSET)
                        expiry_time = entry_time + timedelta(seconds=dynamic_expiry_seconds(np.std(prices[pair][-20:])))

                        # Pre-notify
                        send_pre_notify(pair, direction, entry_time)
                        await asyncio.sleep(PRE_NOTIFY_DELAY)

                        # Final signal
                        send_final_signal(pair, direction, prob, entry_time, expiry_time)

                        signals_this_hour += 1
                        last_pair_sent = pair
                        global_lock = True
                        cooldowns[pair] = expiry_time + timedelta(seconds=1)
                        asyncio.create_task(unlock_after(expiry_time, pair, prices[pair][-1], direction))

                    except Exception as e:
                        print("[ERROR] Tick:",e)
        except Exception as e:
            print("[ERROR] Main:",e)
            await asyncio.sleep(5)

# -------------------
# RUN
# -------------------

asyncio.run(monitor())
