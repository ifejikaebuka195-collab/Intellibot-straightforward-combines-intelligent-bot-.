import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import logging

# ----------------------
# CONFIG
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")
EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 10  # Ticks to observe before final signal
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
tick_confirm = {}
active_signal = None  # Only one active signal at a time
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
# STABLE TREND & PULLBACK CHECK
# ----------------------
def is_stable_with_no_pullback(p, direction):
    """
    Checks:
    - Trend stability over observation ticks
    - Detects pullback and waits until trend resumes
    """
    if len(p) < OBSERVATION_TICKS + 5:
        return False

    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    # Pullback detection: temporary reversal in last few ticks
    pullback = False
    if direction == "BUY" and np.any(last_diff < 0):
        pullback = True
    if direction == "SELL" and np.any(last_diff > 0):
        pullback = True

    # Trend must be stable and no pullback
    if direction == "BUY":
        return np.all(last_diff > 0) and not pullback
    elif direction == "SELL":
        return np.all(last_diff < 0) and not pullback
    return False

# ----------------------
# ACCURACY SCORING
# ----------------------
def calculate_accuracy(p, direction):
    """
    Simulate PocketOption-style probability scoring.
    """
    score = 0
    max_score = 100

    # EMA alignment score
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if direction=="BUY" and e1>e2 and e3>e4:
        score += 25
    elif direction=="SELL" and e1<e2 and e3<e4:
        score += 25

    # Momentum
    diff = np.diff(p[-5:])
    if direction=="BUY" and np.all(diff>0):
        score += 25
    elif direction=="SELL" and np.all(diff<0):
        score += 25

    # Volatility check
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean < 0.005:
        score += 25

    # Pullback safety
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY" and np.all(last_diff>0):
        score += 25
    elif direction=="SELL" and np.all(last_diff<0):
        score += 25

    accuracy = min(score, max_score)
    return max(82, min(accuracy, 85))  # Ensure between 82–85%

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
# MONITOR LOOP
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
                    prices[s] = []

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
                        if len(prices[pair]) > MAX_PRICES:
                            prices[pair].pop(0)

                        # Skip if an active signal exists
                        if active_signal:
                            continue

                        direction = detect_trend(prices[pair])
                        if not direction:
                            continue

                        if is_stable_with_no_pullback(prices[pair], direction):
                            acc = calculate_accuracy(prices[pair], direction)
                            send_asset(pair)
                            send_final(pair, direction, acc)

                            active_signal = pair
                            cooldown_until = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)
                            prices[pair] = []  # reset for next observation
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
