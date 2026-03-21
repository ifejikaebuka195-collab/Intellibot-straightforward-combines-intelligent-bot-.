import asyncio
import json
import requests
import websockets
from datetime import datetime, timedelta
from collections import deque, defaultdict
import pytz
import numpy as np
import logging

# ----------------------
# CONFIGURATION
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
COINCAP_WS = "wss://ws.coincap.io/prices?assets=ALL"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
TOP_PAIRS = 2
FILTER_BAD_PERCENT = 0.95
SIGNALS_PER_HOUR = 2
MIN_SIGNAL_INTERVAL = 1800  # 30 minutes between signals

# Weekend crypto pairs to stream automatically
CRYPTO_PAIRS = ["bitcoin", "ethereum", "litecoin", "cardano", "dogecoin",
                "ripple","polkadot","binance-coin","stellar","chainlink",
                "uniswap","vechain","tron","monero","tezos"]

# ----------------------
# GLOBAL STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
historical_memory = defaultdict(lambda: deque(maxlen=MAX_PRICES))
signal_history = defaultdict(list)
pair_losses = defaultdict(int)
adaptive_weights = {"ema": 0.25, "momentum": 0.25, "volatility": 0.25, "pullback": 0.25}
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))
active_signals = []

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ----------------------
# EMA FUNCTION
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
    if len(p) < 50: return None
    e1 = ema(list(p)[-10:], 3)
    e2 = ema(list(p)[-20:], 5)
    e3 = ema(list(p)[-30:], 8)
    e4 = ema(list(p)[-50:], 13)
    if not all([e1, e2, e3, e4]): return None
    if e1 > e2 and e3 > e4:
        return "BUY"
    if e1 < e2 and e3 < e4:
        return "SELL"
    return None

# ----------------------
# MARKET STABILITY
# ----------------------
def is_stable(p, direction):
    if len(p) < OBSERVATION_TICKS + 5: return False
    last_diff = np.diff(list(p)[-OBSERVATION_TICKS:])
    if direction == "BUY": return np.all(last_diff > 0)
    if direction == "SELL": return np.all(last_diff < 0)
    return False

def is_market_stable(p):
    if len(p) < 30: return False
    std = np.std(list(p)[-30:])
    mean = np.mean(list(p)[-30:])
    return std / mean < 0.005

# ----------------------
# ACCURACY
# ----------------------
def calculate_accuracy(p, direction):
    score = 0
    e1 = ema(list(p)[-10:], 3)
    e2 = ema(list(p)[-20:], 5)
    e3 = ema(list(p)[-30:], 8)
    e4 = ema(list(p)[-50:], 13)
    if direction == "BUY" and e1 > e2 and e3 > e4: score += adaptive_weights["ema"] * 100
    if direction == "SELL" and e1 < e2 and e3 < e4: score += adaptive_weights["ema"] * 100
    diff = np.diff(list(p)[-5:])
    if direction == "BUY" and np.all(diff > 0): score += adaptive_weights["momentum"] * 100
    if direction == "SELL" and np.all(diff < 0): score += adaptive_weights["momentum"] * 100
    std = np.std(list(p)[-30:])
    mean = np.mean(list(p)[-30:])
    if std / mean < 0.005: score += adaptive_weights["volatility"] * 100
    last_diff = np.diff(list(p)[-OBSERVATION_TICKS:])
    if direction == "BUY" and np.all(last_diff > 0): score += adaptive_weights["pullback"] * 100
    if direction == "SELL" and np.all(last_diff < 0): score += adaptive_weights["pullback"] * 100
    return min(score, 100)

# ----------------------
# TELEGRAM NOTIFICATIONS
# ----------------------
def send_signal(pair, direction, accuracy, trend_type):
    arrow = "⬆️" if direction == "BUY" else "⬇️"
    msg = f"SIGNAL {arrow}\nPair: {pair}\nTrend: {trend_type}\nAccuracy: {accuracy}%\nExpiration: {EXPIRY_MINUTES} min"
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
        logging.info(f"Signal sent: {pair} {direction} Accuracy: {accuracy}% Trend: {trend_type}")
    except Exception as e:
        logging.error(f"Telegram send error: {e}")

# ----------------------
# ADAPTIVE WEIGHTS
# ----------------------
def update_weights(pair, direction, result):
    signal_history[pair].append(result)
    if len(signal_history[pair]) > 100: signal_history[pair].pop(0)
    for k in adaptive_weights:
        if result: adaptive_weights[k] = min(0.4, adaptive_weights[k] + 0.01)
        else: adaptive_weights[k] = max(0.15, adaptive_weights[k] - 0.01)
    if not result: pair_losses[pair] += 1
    else: pair_losses[pair] = 0
    logging.info(f"Adaptive weights updated: {adaptive_weights}")

# ----------------------
# GET ACTIVE SYMBOLS (Deriv)
# ----------------------
async def get_deriv_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except Exception as e:
        logging.warning(f"Failed to load symbols from Deriv: {e}")
        return []

# ----------------------
# SYSTEM MAIN LOOP
# ----------------------
async def system_loop():
    global last_signal_times, active_signals

    while True:
        now = datetime.now(TIMEZONE)
        weekday = now.weekday()
        hour = now.hour

        # Determine source: Deriv Mon-Fri, CoinCap Fri 21:00 - Sun 00:00
        use_deriv = True
        if (weekday == 4 and hour >= 21) or weekday == 5 or weekday == 6:
            use_deriv = False

        symbols = await get_deriv_symbols() if use_deriv else CRYPTO_PAIRS

        for s in symbols:
            if s not in prices: prices[s] = deque(maxlen=MAX_PRICES)
            if s not in historical_memory: historical_memory[s] = deque(maxlen=MAX_PRICES)

        ws_url = DERIV_WS if use_deriv else COINCAP_WS

        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                # Subscribe ticks
                if use_deriv:
                    for s in symbols:
                        await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        if use_deriv and "tick" in data:
                            pair = data["tick"]["symbol"]
                            price = data["tick"]["quote"]
                        elif not use_deriv:
                            pair = list(data.keys())[0]
                            price = float(data[pair])
                        else:
                            continue

                        prices[pair].append(price)
                        historical_memory[pair].append(price)

                        seconds_since_last = (now - last_signal_times[pair]).total_seconds()
                        if seconds_since_last < MIN_SIGNAL_INTERVAL: continue

                        direction = detect_trend(prices[pair])
                        if not direction: continue
                        if not is_stable(prices[pair], direction): continue
                        if not is_market_stable(prices[pair]): continue

                        accuracy = calculate_accuracy(prices[pair], direction)
                        trend_type = "Stable Trend" if np.std(list(prices[pair])[-5:]) < 0.005 else "Massive Breakout"
                        send_signal(pair, direction, accuracy, trend_type)
                        last_signal_times[pair] = now

                        await asyncio.sleep(EXPIRY_MINUTES * 60)

                    except Exception as e_tick:
                        logging.error(f"Tick processing error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop connection error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN SYSTEM
# ----------------------
asyncio.run(system_loop())
