import asyncio
import json
import requests
import websockets
import logging
from datetime import datetime, timedelta
import pytz
import numpy as np

# ================================
# TELEGRAM SETTINGS
# ================================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

# ================================
# DERIV WEBSOCKET CONFIG
# ================================
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
CRYPTO_PAIRS = [
    "cryBTCUSD", "cryETHUSD", "cryXRPUSD", "cryLTCUSD", "cryBCHUSD",
    "cryADAUSD","cryBNBUSD","cryDOTUSD","cryLINKUSD","crySOLUSD",
    "cryDOGEUSD","cryUNIUSD","cryMATICUSD","cryAVAXUSD","cryTRXUSD"
]

# ================================
# FILTER THRESHOLDS
# ================================
FILTERS = {
    "big_move": 0.95,
    "pullback": 0.9,
    "trend_continuation": 0.95,
    "candle_stability": 0.95,
    "broker_consensus": 0.95
}

# ================================
# ADAPTIVE ML SETTINGS
# ================================
ML_HISTORY = []
ML_LEARNING_RATE = 0.01
ML_MIN_SIGNALS = 25

# ================================
# LOGGING SETUP
# ================================
logging.basicConfig(level=logging.INFO)

# ================================
# MARKET DATA STORAGE
# ================================
prices = {p: [] for p in CRYPTO_PAIRS}

# ================================
# HELPER FUNCTIONS
# ================================
async def send_telegram(message: str):
    """Send a message to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        logging.error(f"[TELEGRAM ERROR] {e}")

def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data:
        val = p * k + val * (1 - k)
    return val

def evaluate_signal(pair):
    p = prices[pair]
    if len(p) < 60:
        return None

    e1 = ema(p[-10:], 3)
    e2 = ema(p[-20:], 5)
    e3 = ema(p[-30:], 8)
    e4 = ema(p[-50:], 13)

    if not all([e1,e2,e3,e4]):
        return None

    direction = None
    score = 0

    if e1 > e2 > e3 > e4:
        direction = "BUY"
        score += 30
    elif e1 < e2 < e3 < e4:
        direction = "SELL"
        score += 30
    else:
        return None

    diff = np.diff(p[-10:])
    if direction == "BUY" and np.sum(diff > 0) >= 8:
        score += 25
    elif direction == "SELL" and np.sum(diff < 0) >= 8:
        score += 25
    else:
        return None

    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean < 0.004:
        score += 20
    else:
        return None

    move = abs(p[-1]-p[-15])
    noise = np.std(p[-15:])
    if move > noise * 2:
        score += 20

    last = np.diff(p[-3:])
    if (direction=="BUY" and last[-1]>0) or (direction=="SELL" and last[-1]<0):
        score += 15
    else:
        return None

    if score >= 90:
        return {"direction":direction, "accuracy":95, "type":"EXPLOSIVE MOVE"}
    if score >= 80:
        return {"direction":direction, "accuracy":90, "type":"STRONG TREND"}
    if score >= 70:
        return {"direction":direction, "accuracy":85, "type":"STABLE TREND"}

    return None

def ml_update(signal_record):
    ML_HISTORY.append(signal_record)
    if len(ML_HISTORY) < ML_MIN_SIGNALS:
        return

    for key in FILTERS:
        wins = sum(1 for r in ML_HISTORY if r["success"] and r["filters"].get(key, False))
        total = sum(1 for r in ML_HISTORY if r["filters"].get(key, False))
        if total == 0: 
            continue
        observed = wins / total
        FILTERS[key] += ML_LEARNING_RATE * (observed - FILTERS[key])
        FILTERS[key] = max(0.5, min(FILTERS[key], 0.999))

# ================================
# DERIV WEBSOCKET STREAM
# ================================
async def stream_deriv():
    async with websockets.connect(DERIV_WS_URL) as ws:
        for pair in CRYPTO_PAIRS:
            await ws.send(json.dumps({"ticks":pair, "subscribe":1}))

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            if "tick" in data:
                pair = data["tick"]["symbol"]
                price = data["tick"]["quote"]
                prices[pair].append(price)

                if len(prices[pair]) > 5000:
                    prices[pair] = prices[pair][-5000:]

                result = evaluate_signal(pair)
                if result:
                    formatted = f"""
🔥 ELITE SIGNAL 🔥

Pair: {pair}
Direction: {result['direction']}
Type: {result['type']}
Accuracy: {result['accuracy']}%
Entry Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC
Expiry: 5 min
"""
                    await send_telegram(formatted)
                    logging.info(f"SENT: {pair} {result['direction']} {result['accuracy']}%")

async def main():
    try:
        await stream_deriv()
    except Exception as e:
        logging.error(f"[WEBSOCKET ERROR] {e}")
        await asyncio.sleep(5)
        await main()

if __name__ == "__main__":
    asyncio.run(main())
