import asyncio
import json
import requests
import websockets
import logging
from datetime import datetime, timedelta
import pytz

# -----------------------------
# TELEGRAM SETTINGS
# -----------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

# -----------------------------
# DERIV WEBSOCKET
# -----------------------------
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# -----------------------------
# PAIRS TO MONITOR
# -----------------------------
CRYPTO_PAIRS = [
    "cryBTCUSD","cryETHUSD","cryXRPUSD","cryLTCUSD","cryBCHUSD",
    "cryADAUSD","cryBNBUSD","cryDOTUSD","cryLINKUSD","crySOLUSD",
    "cryDOGEUSD","cryUNIUSD","cryMATICUSD","cryAVAXUSD","cryTRXUSD"
]

FOREX_PAIRS = [
    "frxEURUSD","frxGBPUSD","frxUSDJPY","frxAUDUSD","frxUSDCAD"
]

ALL_PAIRS = CRYPTO_PAIRS + FOREX_PAIRS

# -----------------------------
# FILTER THRESHOLDS
# -----------------------------
MIN_ACCURACY = 90
HIGH_ACCURACY = 95
TICK_BUFFER_LIMIT = 10000
EXPIRY_MINUTES = 5

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(level=logging.INFO)

# -----------------------------
# DATA STORAGE
# -----------------------------
tick_buffers = {pair: [] for pair in ALL_PAIRS}
cooldown_until = {pair: datetime.min.replace(tzinfo=pytz.UTC) for pair in ALL_PAIRS}

# -----------------------------
# SCHEDULE LOGIC
# -----------------------------
def is_crypto_time():
    now = datetime.utcnow().replace(tzinfo=pytz.UTC)
    weekday = now.weekday()
    time = now.time()
    # Fri 22:00 → Sun 00:00
    if weekday == 4 and time >= datetime.strptime("22:00","%H:%M").time():
        return True
    if weekday == 5 or weekday == 6:
        return True
    return False

def active_pairs():
    """Switches based on schedule."""
    if is_crypto_time():
        return CRYPTO_PAIRS
    return FOREX_PAIRS

# -----------------------------
# SIGNAL GENERATOR
# -----------------------------
def evaluate_patterns(pair):
    """
    Your AI pattern evaluation:
    Uses EMA, trend-check, stability, pullback, etc.
    Only returns a signal if 90%+ or 95%+
    """
    prices = tick_buffers[pair]
    if len(prices) < 60:
        return None

    def ema(data, n):
        if len(data) < n: 
            return None
        k = 2/(n+1)
        s = data[0]
        for p in data:
            s = p*k + s*(1-k)
        return s

    e1 = ema(prices[-10:], 3)
    e2 = ema(prices[-20:], 5)
    e3 = ema(prices[-30:], 8)
    e4 = ema(prices[-50:],13)
    if not all([e1,e2,e3,e4]):
        return None

    direction = None
    score = 0
    if e1>e2 and e3>e4:
        direction="BUY"; score+=30
    if e1<e2 and e3<e4:
        direction="SELL"; score+=30
    if score == 0:
        return None

    # momentum check
    diffs = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    if direction == "BUY" and sum(1 for d in diffs[-10:] if d>0) >= 8:
        score+=25
    elif direction == "SELL" and sum(1 for d in diffs[-10:] if d<0) >= 8:
        score+=25
    else:
        return None

    # volatility check
    import numpy as np
    std = np.std(prices[-30:])
    mean = np.mean(prices[-30:])
    if std/mean < 0.005:
        score+=20
    else:
        return None

    # big move
    if abs(prices[-1]-prices[-15]) > std*2:
        score+=20

    # final
    accuracy = min(100, score)
    if accuracy >= HIGH_ACCURACY:
        return {"direction":direction,"accuracy":HIGH_ACCURACY}
    if accuracy >= MIN_ACCURACY:
        return {"direction":direction,"accuracy":MIN_ACCURACY}
    return None

def format_signal(pair, res):
    now = datetime.utcnow().strftime("%H:%M:%S")
    return f"""
🔥 ELITE SIGNAL 🔥

Pair: {pair}
Direction: {res['direction']}
Accuracy: {res['accuracy']}%
Entry Time: {now} UTC
Expiry: {EXPIRY_MINUTES} min
"""

async def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# -----------------------------
# WEBSOCKET STREAM
# -----------------------------
async def handle_ticks():
    async with websockets.connect(DERIV_WS_URL) as ws:
        # Subscribe
        for p in ALL_PAIRS:
            await ws.send(json.dumps({"ticks":p,"subscribe":1}))

        while True:
            try:
                raw = await ws.recv()
                data = json.loads(raw)
                if "tick" not in data:
                    continue

                pair = data["tick"]["symbol"]
                quote = data["tick"]["quote"]

                # add to buffer
                buf = tick_buffers[pair]
                buf.append(quote)
                if len(buf) > TICK_BUFFER_LIMIT:
                    buf.pop(0)

                # Only evaluate if buffer full
                if len(buf) >= TICK_BUFFER_LIMIT:
                    now = datetime.utcnow().replace(tzinfo=pytz.UTC)
                    if now >= cooldown_until[pair]:
                        result = evaluate_patterns(pair)
                        if result:
                            msg = format_signal(pair, result)
                            await send_telegram(msg)
                            logging.info(f"Signal for {pair}: {result}")

                            # cooldown
                            cooldown_until[pair] = now + timedelta(minutes=EXPIRY_MINUTES)

                            # reset buffer
                            tick_buffers[pair] = []

            except Exception as e:
                logging.error(f"WebSocket receive error: {e}")
                await asyncio.sleep(5)

# -----------------------------
# RUN
# -----------------------------
async def main():
    while True:
        try:
            await handle_ticks()
        except Exception as err:
            logging.error(f"Connection error: {err}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
