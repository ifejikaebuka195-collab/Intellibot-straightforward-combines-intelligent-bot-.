# ======================================
# FINAL REAL-MONEY NO-MARTINGALE AI SIGNAL BOT
# FULLY DEPLOYABLE TO LIVE MARKET
# TELEGRAM SIGNAL FORMAT MATCHING SAMPLE
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
TICK_CONFIRMATION = 3
BASE_CONFIDENCE = 80
MAX_SIGNALS_PER_HOUR = 2

TRADE_LOG = "ai_no_martingale_signals.csv"

# -------------------
# INIT LOG
# -------------------
if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        csv.writer(f).writerow([
            "time","pair","direction","confidence","duration_min",
            "duration_sec","expiry_time","volatility","market_state","result"
        ])

# -------------------
# GLOBALS
# -------------------
prices = {}
tick_confirm = {}
symbol_confidence = {}
global_lock = False
signals_this_hour = 0
current_hour = datetime.now(TIMEZONE).hour
last_pair_sent = None

# -------------------
# EMA FUNCTION
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
# PREDICTION LOGIC
# -------------------
def predict_direction(p):
    features = extract_features(p)
    if not features:
        return 0, None
    trend_score = features["returns"] + features["momentum"] * 0.5
    prob = min(max((trend_score + 0.5) * 100, 1), 99)  # Scale 0-100%
    direction = "BUY" if prob > 50 else "SELL"
    return prob, direction

# -------------------
# MARKET STATE FILTER
# -------------------
MIN_VOL = 0.001
MAX_VOL = 0.008
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
# TELEGRAM MESSAGE FORMATTING
# -------------------
def format_signal(pair, direction, confidence, duration_min, duration_sec, volatility):
    arrow = "↗️" if direction == "BUY" else "↘️"
    signal_text = f"""🖇 Signal information:
{pair} — {duration_min} minutes

📰 Market Setting:
Info context: None
Volatility: {'Low' if volatility<0.002 else 'Moderate' if volatility<0.004 else 'High'}

🖥 Technical overview:
Only for stock quotes

💷 Probabilities:
Signal reliability: {confidence:.2f}%

🧨 Bot signal:
{direction} {arrow}"""
    return signal_text

def send_final_signal(pair, direction, confidence, duration_min, duration_sec, expiry_time, volatility):
    msg = format_signal(pair, direction, confidence, duration_min, duration_sec, volatility)
    msg = f"AI SIGNAL ✅\n{msg}\nExpiry Time: {expiry_time.strftime('%H:%M:%S')}"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})
    print(f"[SIGNAL] {pair} {direction} {confidence:.2f}%")

# -------------------
# LOGGING
# -------------------
def log_signal(pair, direction, confidence, duration_min, duration_sec, expiry_time, vol, state, result="PENDING"):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(TIMEZONE), pair, direction, confidence,
            duration_min, duration_sec, expiry_time.strftime('%H:%M:%S'), vol, state, result
        ])

# -------------------
# NEWS/PRICE SPIKE DETECTION
# -------------------
def is_price_spike(p):
    """
    Detects a price spike using sudden large movement relative to recent prices.
    If last return > 3x recent std dev, consider it a spike → skip.
    """
    if len(p) < 20:
        return False
    recent = p[-20:]
    std = np.std(recent)
    if std == 0:
        return False
    move = abs(p[-1] - p[-2])
    if move > 3 * std:
        return True
    return False

# -------------------
# UNLOCK AFTER SIGNAL
# -------------------
async def unlock_after(expiry_time):
    global global_lock
    delay = (expiry_time - datetime.now(TIMEZONE)).total_seconds()
    await asyncio.sleep(max(0, delay))
    global_lock = False

# -------------------
# DYNAMIC EXPIRY
# -------------------
def dynamic_expiry_seconds(volatility):
    if volatility < 0.002:
        return 180
    elif volatility < 0.004:
        return 120
    else:
        return 75

# -------------------
# MAIN LOOP
# -------------------
async def monitor():
    global global_lock, signals_this_hour, current_hour, last_pair_sent
    crypto_pairs = ["BTCUSD","ETHUSD","LTCUSD","XRPUSD","BCHUSD","ADAUSD","DOGEUSD"]

    while True:
        try:
            async with websockets.connect(DERIV_WS) as ws:
                await ws.send(json.dumps({"active_symbols":"brief"}))
                res = json.loads(await ws.recv())
                symbols = [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
                symbols = list(set(symbols + crypto_pairs))

                for s in symbols:
                    prices[s] = []
                    tick_confirm[s] = {"count": 0, "dir": None}
                    symbol_confidence[s] = BASE_CONFIDENCE

                for s in symbols:
                    await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

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
                            print("[RESET HOUR]")

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        prices[pair].append(price)
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        if global_lock:
                            continue
                        if signals_this_hour >= MAX_SIGNALS_PER_HOUR:
                            continue
                        if pair in tick_confirm and now < tick_confirm[pair].get("cooldown", now):
                            continue

                        # -------------------
                        # NEWS/PRICE SPIKE IMMUNITY
                        # -------------------
                        if is_price_spike(prices[pair]):
                            # Skip trading during extreme sudden move
                            print(f"[SPIKE] Skipping due to spike {pair}")
                            continue

                        state = market_state(prices[pair])
                        if state != "NORMAL":
                            continue

                        prob, direction = predict_direction(prices[pair])
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

                        vol = np.std(prices[pair][-20:])
                        total_seconds = dynamic_expiry_seconds(vol)
                        duration_min = total_seconds // 60
                        duration_sec = total_seconds % 60
                        expiry_time = now + timedelta(seconds=total_seconds)

                        send_final_signal(pair, direction, prob, duration_min, duration_sec, expiry_time, vol)
                        log_signal(pair, direction, prob, duration_min, duration_sec, expiry_time, vol, state)

                        signals_this_hour += 1
                        last_pair_sent = pair
                        global_lock = True
                        tick_confirm[pair]["cooldown"] = expiry_time
                        asyncio.create_task(unlock_after(expiry_time))

                    except Exception as e:
                        print("[ERROR] Tick:", e)
        except Exception as e:
            print("[ERROR] Main Loop:", e)
            await asyncio.sleep(5)

# -------------------
# RUN
# -------------------
asyncio.run(monitor())
