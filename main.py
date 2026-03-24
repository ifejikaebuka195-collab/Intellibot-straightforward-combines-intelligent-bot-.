# ======================================
# DERIV AI SIGNAL BOT - FULLY ADAPTIVE
# REAL MARKET + SELF-LEARNING + STABLE
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

prices = {}
tick_confirm = {}
cooldowns = {}
pending = {}

TRADE_LOG = "ai_trades.csv"

# ================================
# INIT LOG
# ================================
if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        csv.writer(f).writerow(["time","pair","dir","entry","exit","result"])

# ================================
# EMA UTILITY
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
# RIVER IMPORTS
# ================================
from river import linear_model, preprocessing, metrics

# -------------------
# ONLINE MODEL
# -------------------
model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
model_metric = metrics.LogLoss()

# ================================
# FEATURE ENGINE
# ================================
def extract_features(p):
    if len(p) < 30:
        return None
    returns = (p[-1] - p[-2]) / p[-2]
    volatility = np.std(p[-20:])
    momentum = np.sum(np.diff(p[-10:]))
    trend_strength = abs(ema(p[-20:],5) - ema(p[-50:],13))
    return {"returns": returns, "volatility": volatility, "momentum": momentum, "trend": trend_strength}

# ================================
# AI PROBABILITY PREDICTION
# ================================
def predict_probability(p):
    features = extract_features(p)
    if not features:
        return 0, None

    prob = model.predict_proba_one(features).get(1, 0.5) * 100
    direction = "BUY" if prob > 50 else "SELL"
    return prob, direction

# ================================
# MARKET STATE CHECK
# ================================
def market_state(p):
    if len(p) < 20:
        return "UNKNOWN"
    vol = np.std(p[-20:])
    if vol < 0.001:
        return "RANGE"
    elif vol > 0.005:
        return "VOLATILE"
    return "NORMAL"

# ================================
# TELEGRAM SIGNALS
# ================================
def send_signal(pair, direction, prob):
    msg = f"""
AI SIGNAL READY ✅

Asset: {pair}_otc
Direction: {direction}
Confidence: {prob:.2f}%
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[SIGNAL READY] {pair} | {direction} | {prob:.2f}%")

# ================================
# TRADE LOGGING
# ================================
def log_trade(pair, direction, entry, exit_price):
    result = "WIN" if (
        (direction == "BUY" and exit_price > entry) or
        (direction == "SELL" and exit_price < entry)
    ) else "LOSS"

    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, entry, exit_price, result
        ])

# ================================
# LOAD SYMBOLS
# ================================
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# ================================
# MAIN MONITOR LOOP
# ================================
async def monitor():
    while True:
        try:
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

                        print(f"[LIVE] {pair} {price}")

                        # Skip if cooldown
                        if pair in cooldowns and datetime.now(TIMEZONE) < cooldowns[pair]:
                            continue

                        # Skip if market not normal
                        if market_state(prices[pair]) != "NORMAL":
                            continue

                        # Predict AI probability
                        prob, direction = predict_probability(prices[pair])
                        if prob < 75:
                            continue

                        # Tick confirmation
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir": direction, "count": 1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        entry = prices[pair][-1]

                        # Send Telegram signal
                        send_signal(pair, direction, prob)

                        # Update cooldown
                        cooldowns[pair] = datetime.now(TIMEZONE) + timedelta(minutes=COOLDOWN_MINUTES)

                        # EXIT LOGIC: simulate waiting for duration
                        await asyncio.sleep(60)

                        exit_price = prices[pair][-1]

                        # Log trade
                        log_trade(pair, direction, entry, exit_price)

                        # Online learning: update the model
                        features = extract_features(prices[pair])
                        if features:
                            target = 1 if exit_price > entry else 0
                            model.learn_one(features, target)
                            model_metric.update(target, model.predict_one(features))

                    except Exception as e:
                        print("[ERROR] Tick:", e)

        except Exception as e:
            print("[ERROR] Main loop:", e)
            await asyncio.sleep(5)

# ================================
# RUN
# ================================
asyncio.run(monitor())
