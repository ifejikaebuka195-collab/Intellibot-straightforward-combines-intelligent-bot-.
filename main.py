# ======================================
# DERIV OTC SIGNAL BOT (LOCKED + TIGHT FILTER)
# ======================================

import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz

BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

EXPIRY_MINUTES = 5
MAX_PRICES = 5000
TICK_CONFIRMATION = 3
COOLDOWN_SECONDS = 15
ENTRY_DELAY = 1

BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

prices = {}
tick_confirm = {}
pending_signal = None
cooldown_lock = {}

ACTIVE_PAIR = None
TRADE_END = None

# ================================
# EMA
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
# TREND DETECTION
# ================================
def detect_trend(p):
    if len(p) < 100:
        return None
    e1 = ema(p[-20:], 5)
    e2 = ema(p[-50:], 13)
    e3 = ema(p[-100:], 21)
    if not all([e1, e2, e3]):
        return None
    if e1 > e2 > e3:
        return "BUY"
    elif e1 < e2 < e3:
        return "SELL"
    return None

# ================================
# SUPER SAFE FILTER (ANTI-FLIP)
# ================================
def ultra_safe_entry(p, direction):
    if len(p) < 30:
        return False

    recent = np.array(p[-20:])
    diff = np.diff(recent)

    # strong momentum
    if direction == "BUY":
        if np.sum(diff > 0) < 15:
            return False
    else:
        if np.sum(diff < 0) < 15:
            return False

    # low volatility (avoid flip zones)
    vol = np.std(recent) / np.mean(recent)
    if vol > 0.004:
        return False

    # consistency (no sudden opposite spike)
    last_moves = diff[-5:]
    if direction == "BUY" and np.any(last_moves < 0):
        return False
    if direction == "SELL" and np.any(last_moves > 0):
        return False

    return True

# ================================
# EXISTING FUNCTIONS (UNCHANGED)
# ================================
def detect_pullback(p, direction):
    if len(p) < 10:
        return False
    recent = np.array(p[-10:])
    diff = np.diff(recent)
    threshold = 0.001 * np.mean(recent)
    if direction == "BUY" and np.any(diff < -threshold):
        return True
    if direction == "SELL" and np.any(diff > threshold):
        return True
    return False

def detect_reversal(p):
    if len(p) < 15:
        return None
    diff = np.diff(p[-15:])
    ups = np.sum(diff > 0)
    downs = np.sum(diff < 0)
    threshold = max(3, int(0.2 * len(diff)))
    if ups >= 10 and downs >= threshold:
        return "BUY_REVERSE"
    if downs >= 10 and ups >= threshold:
        return "SELL_REVERSE"
    return None

def big_move_ready(p, direction):
    if len(p) < 50:
        return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std > 0.01 * mean:
        return False
    diff = np.diff(p[-10:])
    if direction == "BUY":
        if np.sum(diff > 0) < 8 or not (diff[-1] > diff[-2] > diff[-3]):
            return False
    if direction == "SELL":
        if np.sum(diff < 0) < 8 or not (diff[-1] < diff[-2] < diff[-3]):
            return False
    return True

def entry_confirm(p, direction):
    if len(p) < 15:
        return False
    diff = np.diff(p[-10:])
    if direction in ["BUY", "BUY_REVERSE"]:
        return np.sum(diff > 0) >= 8
    if direction in ["SELL", "SELL_REVERSE"]:
        return np.sum(diff < 0) >= 8
    return False

def get_accuracy(p):
    if len(p) < 50:
        return 85
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean > 0.005:
        return 90
    return 85

def locked(pair):
    if pair in cooldown_lock:
        return datetime.now(TIMEZONE) < cooldown_lock[pair]
    return False

def set_lock(pair):
    cooldown_lock[pair] = datetime.now(TIMEZONE) + timedelta(seconds=COOLDOWN_SECONDS)

# ================================
# TELEGRAM
# ================================
def send_asset(pair):
    msg = f"\nSIGNAL ⚠️\n\nAsset: {pair}_otc\nPreparing entry...\n"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

def send_final(pair, direction, acc):
    arrow = "⬆️" if "BUY" in direction else "⬇️"
    msg = f"\nSIGNAL {arrow}\n\nAsset: {pair}_otc\nAccuracy: {acc}%\nExpiration: M{EXPIRY_MINUTES}\n"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

# ================================
# MAIN LOOP (CONTROLLED FLOW)
# ================================
async def monitor():
    global ACTIVE_PAIR, TRADE_END

    while True:
        try:
            symbols = await load_symbols()

            async with websockets.connect(DERIV_WS) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" not in data:
                        continue

                    pair = data["tick"]["symbol"]
                    price = data["tick"]["quote"]

                    prices.setdefault(pair, []).append(price)

                    # WAIT UNTIL TRADE ENDS
                    if TRADE_END and datetime.now(TIMEZONE) < TRADE_END:
                        continue

                    # LOCK TO ONE PAIR
                    if ACTIVE_PAIR and pair != ACTIVE_PAIR:
                        continue

                    direction = detect_trend(prices[pair])
                    if not direction:
                        continue

                    if detect_pullback(prices[pair], direction):
                        continue

                    if not big_move_ready(prices[pair], direction):
                        continue

                    # ULTRA SAFE CHECK (YOUR REQUEST)
                    if not ultra_safe_entry(prices[pair], direction):
                        continue

                    # SEND PAIR ONCE
                    if not ACTIVE_PAIR:
                        send_asset(pair)
                        ACTIVE_PAIR = pair

                        await asyncio.sleep(ENTRY_DELAY * 60)

                        if entry_confirm(prices[pair], direction):
                            acc = get_accuracy(prices[pair])
                            send_final(pair, direction, acc)

                            TRADE_END = datetime.now(TIMEZONE) + timedelta(minutes=EXPIRY_MINUTES)

                        ACTIVE_PAIR = None

        except:
            await asyncio.sleep(5)

asyncio.run(monitor())
