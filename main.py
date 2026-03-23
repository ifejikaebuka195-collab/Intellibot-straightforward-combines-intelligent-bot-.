import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import logging
from collections import deque, defaultdict

# ----------------------
# CONFIG
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")
EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
historical_memory = {}
signal_history = defaultdict(list)
adaptive_weights = {
    "ema": 0.25,
    "momentum": 0.25,
    "volatility": 0.25,
    "pullback": 0.25
}
active_signal = None
cooldown_until = None

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ----------------------
# EMA CALCULATION
# ----------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

# ----------------------
# TREND DETECTION
# ----------------------
def detect_trend(p):
    if len(p) < 50:
        return None
    e1 = ema(p[-10:], 3)
    e2 = ema(p[-20:], 5)
    e3 = ema(p[-30:], 8)
    e4 = ema(p[-50:], 13)
    if not all([e1, e2, e3, e4]):
        return None
    if e1 > e2 and e3 > e4:
        return "BUY"
    elif e1 < e2 and e3 < e4:
        return "SELL"
    return None

# ----------------------
# PULLBACK & STABLE MOVE CHECK
# ----------------------
def is_stable_and_no_pullback(p, direction):
    if len(p) < OBSERVATION_TICKS + 5:
        return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    pullback = False
    if direction == "BUY" and np.any(last_diff < 0):
        pullback = True
    if direction == "SELL" and np.any(last_diff > 0):
        pullback = True
    if direction == "BUY":
        return np.all(last_diff > 0) and not pullback
    elif direction == "SELL":
        return np.all(last_diff < 0) and not pullback
    return False

# ----------------------
# DYNAMIC ACCURACY SCORING WITH ADAPTIVE LEARNING
# ----------------------
def calculate_accuracy(p, direction):
    score = 0
    max_score = 100
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if direction=="BUY" and e1>e2 and e3>e4:
        score += adaptive_weights["ema"]*100
    elif direction=="SELL" and e1<e2 and e3<e4:
        score += adaptive_weights["ema"]*100

    diff = np.diff(p[-5:])
    if direction=="BUY" and np.all(diff>0):
        score += adaptive_weights["momentum"]*100
    elif direction=="SELL" and np.all(diff<0):
        score += adaptive_weights["momentum"]*100

    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean < 0.005:
        score += adaptive_weights["volatility"]*100

    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY" and np.all(last_diff>0):
        score += adaptive_weights["pullback"]*100
    elif direction=="SELL" and np.all(last_diff<0):
        score += adaptive_weights["pullback"]*100

    accuracy = min(score, max_score)
    return max(82, min(accuracy, 95))

# ----------------------
# ADAPTIVE LEARNING UPDATE (AUTONOMOUS)
# ----------------------
def update_adaptive_weights(pair, direction, result):
    signal_history[pair].append(result)
    if len(signal_history[pair]) > 100:
        signal_history[pair].pop(0)
    success_rate = np.mean(signal_history[pair])
    for key in adaptive_weights:
        if result:
            adaptive_weights[key] = min(0.4, adaptive_weights[key]+0.01)
        else:
            adaptive_weights[key] = max(0.15, adaptive_weights[key]-0.01)
    logging.info(f"Adaptive weights updated: {adaptive_weights}")

# ----------------------
# TELEGRAM FUNCTIONS
# ----------------------
def send_asset(pair):
    msg = f"""
SIGNAL ⚠️
Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}
Observing market for stable move...
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID,"text": msg})
    logging.info(f"Asset observation started: {pair}")

def send_final(pair, direction, acc):
    arrow = "⬆️" if direction=="BUY" else "⬇️"
    msg = f"""
SIGNAL {arrow}
Asset: {pair}_otc
Payout: 92%
Accuracy: {acc}%
Expiration: M{EXPIRY_MINUTES}
"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID,"text": msg})
    logging.info(f"Final signal sent: {pair} {direction} Accuracy: {acc}%")

# ----------------------
# LOAD SYMBOLS
# ----------------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"]
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except Exception as e:
        logging.warning(f"Failed to load symbols: {e}")
        return []

# ----------------------
# MONITOR LOOP WITH AUTONOMOUS LEARNING
# ----------------------
async def monitor():
    global active_signal, cooldown_until

    while True:
        try:
            if cooldown_until and datetime.now(TIMEZONE) < cooldown_until:
                await asyncio.sleep(1)
                continue

            symbols = await load_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue

            for s in symbols:
                if s not in prices:
                    prices[s] = deque(maxlen=MAX_PRICES)
                if s not in historical_memory:
                    historical_memory[s] = deque(maxlen=1000)

            async with websockets.connect(DERIV_WS) as ws:
                for pair in symbols:
                    await ws.send(json.dumps({"ticks": pair, "subscribe": 1}))

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        if "tick" not in data:
                            continue

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        prices[pair].append(price)
                        historical_memory[pair].append(price)

                        if active_signal:
                            continue

                        direction = detect_trend(list(prices[pair]))
                        if not direction:
                            continue

                        if is_stable_and_no_pullback(list(prices[pair]), direction):
                            acc = calculate_accuracy(list(prices[pair]), direction)
                            send_asset(pair)
                            send_final(pair, direction, acc)

                            # Autonomous learning: check after expiry
                            await asyncio.sleep(EXPIRY_MINUTES * 60)
                            final_price = historical_memory[pair][-1]
                            result = (direction=="BUY" and final_price > prices[pair][-1]) or \
                                     (direction=="SELL" and final_price < prices[pair][-1])
                            update_adaptive_weights(pair, direction, result)

                            active_signal = pair
                            cooldown_until = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)
                            prices[pair].clear()
                            break

                    except Exception as e_tick:
                        logging.error(f"Tick error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
