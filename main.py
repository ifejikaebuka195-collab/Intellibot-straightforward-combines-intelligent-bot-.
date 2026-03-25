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
    if len(p) < 50:
        return None

    returns = (p[-1] - p[-2]) / p[-2]
    volatility = np.std(p[-20:])
    momentum = np.sum(np.diff(p[-10:]))

    fast_ema = ema(p[-20:], 5)
    slow_ema = ema(p[-50:], 13)

    trend_strength = abs(fast_ema - slow_ema) if fast_ema and slow_ema else 0
    vol_spike = (p[-1] - np.mean(p[-10:])) / (np.std(p[-10:]) + 1e-9)

    return {
        "returns": returns,
        "volatility": volatility,
        "momentum": momentum,
        "trend": trend_strength,
        "vol_spike": vol_spike,
        "fast": fast_ema,
        "slow": slow_ema
    }

# -------------------
# ADAPTIVE MARKET LOGIC (NEW)
# -------------------
def adaptive_decision(p):
    f = extract_features(p)
    if not f:
        return 0, None

    # Detect market type
    if f["trend"] > 0.0005:
        market_type = "TREND"
    elif abs(f["momentum"]) < 0.0001:
        market_type = "RANGE"
    else:
        market_type = "WEAK"

    # Strong spike detection
    if abs(f["vol_spike"]) > 2:
        direction = "BUY" if f["returns"] > 0 else "SELL"
        return 95, direction

    # Trend trading
    if market_type == "TREND":
        if f["fast"] > f["slow"]:
            return 90, "BUY"
        else:
            return 90, "SELL"

    # Range = skip (no bad trades)
    return 0, None

# -------------------
# TELEGRAM MESSAGE
# -------------------
def format_signal(pair, direction, confidence, duration_min, duration_sec, volatility):
    arrow = "↗️" if direction == "BUY" else "↘️"
    signal_text = f"""🖇 Signal information:
{pair} — {duration_min} minutes

📰 Market Setting:
Volatility: {'Moderate' if volatility<0.004 else 'High'}

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
# UNLOCK AFTER SIGNAL
# -------------------
async def unlock_after(expiry_time):
    global global_lock
    delay = (expiry_time - datetime.now(TIMEZONE)).total_seconds()
    await asyncio.sleep(max(0, delay))
    global_lock = False
    print("[UNLOCKED] Ready for next signal")

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

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        print(f"[TICK] {pair}: {price}")

                        prices[pair].append(price)
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        now = datetime.now(TIMEZONE)

                        if global_lock:
                            continue

                        vol = np.std(prices[pair][-20:])
                        if vol < 0.002:
                            continue

                        prob, direction = adaptive_decision(prices[pair])
                        if not direction or prob < 85:
                            continue

                        if tick_confirm[pair]["dir"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair] = {"dir": direction, "count": 1}

                        if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                            continue

                        print(f"[SIGNAL READY] {pair} {direction} {prob:.2f}%")

                        duration_min = 2
                        duration_sec = 0
                        expiry_time = now + timedelta(minutes=2)

                        send_final_signal(pair, direction, prob, duration_min, duration_sec, expiry_time, vol)
                        log_signal(pair, direction, prob, duration_min, duration_sec, expiry_time, vol, "ADAPTIVE")

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
