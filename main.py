# ======================================
# DERIV AI SIGNAL BOT - FULL LIVE ADAPTIVE
# REAL MARKET + SELF-LEARNING + STABLE
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import os
import csv
from river import linear_model, preprocessing, metrics

# --------------------------
# CONFIG
# --------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

MAX_PRICES = 5000
TICK_CONFIRMATION = 2
COOLDOWN_MINUTES = 2
CONFIDENCE_THRESHOLD = 85

prices = {}
tick_confirm = {}
cooldowns = {}
pending = {}
TRADE_LOG = "ai_trades.csv"

# --------------------------
# INIT LOG
# --------------------------
if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        csv.writer(f).writerow(["time","pair","dir","entry","exit","result"])

# --------------------------
# EMA
# --------------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# --------------------------
# FEATURE EXTRACTION
# --------------------------
def extract_features(p):
    if len(p) < 30:
        return None
    returns = (p[-1] - p[-2]) / p[-2]
    volatility = np.std(p[-20:])
    momentum = np.sum(np.diff(p[-10:]))
    trend_strength = abs(ema(p[-20:],5) - ema(p[-50:],13))
    return {
        "returns": returns,
        "volatility": volatility,
        "momentum": momentum,
        "trend_strength": trend_strength
    }

# --------------------------
# ONLINE ML MODEL
# --------------------------
model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
accuracy_metric = metrics.Accuracy()

# --------------------------
# MARKET STATE
# --------------------------
def market_state(p):
    if len(p) < 20:
        return "UNKNOWN"
    vol = np.std(p[-20:])
    if vol < 0.001:
        return "RANGE"
    elif vol > 0.005:
        return "VOLATILE"
    return "NORMAL"

# --------------------------
# TELEGRAM
# --------------------------
def send_notification(pair, direction, prob, stage="ENTRY"):
    arrow = "⬆️" if direction=="BUY" else "⬇️"
    msg = f"""
AI SIGNAL [{stage}]

Asset: {pair}_otc
Direction: {direction}
Confidence: {prob}%
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

# --------------------------
# LOGGING
# --------------------------
def log_trade(pair, direction, entry, exit_price):
    result = "WIN" if (
        (direction == "BUY" and exit_price > entry) or
        (direction == "SELL" and exit_price < entry)
    ) else "LOSS"

    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, entry, exit_price, result
        ])

# --------------------------
# LOAD SYMBOLS
# --------------------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# --------------------------
# MAIN MONITOR LOOP
# --------------------------
async def monitor():
    while True:
        try:
            symbols = await load_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count":0, "dir":None}

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

                        if pair in cooldowns and datetime.now(TIMEZONE) < cooldowns[pair]:
                            continue

                        state = market_state(prices[pair])
                        if state != "NORMAL":
                            continue

                        # FEATURE EXTRACTION
                        features = extract_features(prices[pair])
                        if not features:
                            continue

                        # PREDICTION
                        x = features
                        prob = model.predict_proba_one(x).get("BUY",0)*100
                        direction = "BUY" if prob >= 50 else "SELL"

                        # TICK CONFIRMATION
                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir":direction,"count":1}
                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        # HIGH CONFIDENCE CHECK
                        if prob < CONFIDENCE_THRESHOLD:
                            continue

                        entry = prices[pair][-1]
                        send_notification(pair, direction, prob, stage="PRE-ENTRY")
                        await asyncio.sleep(1)  # small delay before sending actual signal
                        send_notification(pair, direction, prob, stage="ENTRY")

                        cooldowns[pair] = datetime.now(TIMEZONE) + timedelta(minutes=COOLDOWN_MINUTES)

                        # WAIT FOR EXIT (1 min)
                        await asyncio.sleep(60)
                        exit_price = prices[pair][-1]
                        log_trade(pair, direction, entry, exit_price)

                        # UPDATE MODEL
                        y = 1 if (direction=="BUY" and exit_price>entry) or (direction=="SELL" and exit_price<entry) else 0
                        model.learn_one(features, "BUY" if y==1 else "SELL")
                        accuracy_metric.update("BUY" if y==1 else "SELL", direction)

                    except Exception as e:
                        print("Tick Error:", e)

        except Exception as e:
            print("Main Loop Error:", e)
            await asyncio.sleep(5)

asyncio.run(monitor())
