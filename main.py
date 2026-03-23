# ======================================
# ADAPTIVE OTC SIGNAL BOT
# PRODUCTION-READY, HIGH ACCURACY
# ======================================

import asyncio
import json
import requests
import websockets
import logging
import numpy as np
from datetime import datetime, timedelta
import pytz

# -------------------------------
# TELEGRAM SETTINGS
# -------------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

# -------------------------------
# GENERAL SETTINGS
# -------------------------------
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

# Thresholds for signal detection
TREND_SCORE_BASE = 92
TREND_STRENGTH_BASE = 92

# Martingale / timing
ENTRY_DELAY = 2            # seconds
MG_STEP = 2                # minutes between MG levels
MAX_MG_STEPS = 3
EXPIRY_MINUTES = 2

# Rolling price management
MAX_PRICES = 700
RETRY_SECONDS = 5
SYMBOL_REFRESH_INTERVAL = 5
TICK_CONFIRMATION = 3

# Blocked pairs
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

# -------------------------------
# STATE
# -------------------------------
prices = {}            # price history per symbol
tick_confirm = {}      # tick confirmation counters
active_signal = {"pair": None, "expiry_time": None}
pending_signal = None
last_candle_time = None
signal_sent_this_candle = False

# -------------------------------
# UTILITIES
# -------------------------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    value = data[0]
    for price in data:
        value = price * k + value * (1 - k)
    return value

def trend_strength(price_list):
    if len(price_list) < 150:
        return 0
    ema_fast = ema(price_list[-50:], 10)
    ema_slow = ema(price_list[-100:], 20)
    if ema_fast is None or ema_slow is None:
        return 0
    separation = abs(ema_fast - ema_slow)
    volatility = np.std(price_list[-100:])
    if volatility == 0:
        return 0
    strength = (separation / volatility) * 100
    # Adaptive clamp based on volatility
    min_strength = 80 if volatility < 0.0005 else 85
    max_strength = 98
    return max(min_strength, min(strength, max_strength))

def detect_trend(price_list):
    if len(price_list) < 300:
        return 0, 0, None
    ema_fast = ema(price_list[-50:], 10)
    ema_slow = ema(price_list[-100:], 20)
    ema_long_fast = ema(price_list[-200:], 30)
    ema_long_slow = ema(price_list[-300:], 60)
    strength = trend_strength(price_list)
    score = min(50 + strength * 0.5, 100)
    direction = None
    if ema_fast and ema_slow and ema_long_fast and ema_long_slow:
        if ema_fast > ema_slow and ema_long_fast > ema_long_slow:
            direction = "BUY"
        elif ema_fast < ema_slow and ema_long_fast < ema_long_slow:
            direction = "SELL"
    return score, strength, direction

def signal_active():
    if active_signal["expiry_time"] is None:
        return False
    now = datetime.now(TIMEZONE)
    return now < active_signal["expiry_time"]

def register_signal(pair):
    now = datetime.now(TIMEZONE)
    total_lock_minutes = ENTRY_DELAY + (MG_STEP * MAX_MG_STEPS) + EXPIRY_MINUTES
    active_signal["pair"] = pair
    active_signal["expiry_time"] = now + timedelta(minutes=total_lock_minutes)

def get_flag(code):
    flags = {
        "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "CHF": "🇨🇭",
        "JPY": "🇯🇵", "AUD": "🇦🇺", "CAD": "🇨🇦", "NZD": "🇳🇿"
    }
    return flags.get(code.upper(), "")

def send_signal(pair, direction, score, strength):
    if signal_active():
        return
    now = datetime.now(TIMEZONE)
    entry_time = now + timedelta(seconds=ENTRY_DELAY)
    mg_times = [entry_time + timedelta(minutes=MG_STEP * i) for i in range(MAX_MG_STEPS)]
    register_signal(pair)
    base, quote = pair[3:6].upper(), pair[6:9].upper()
    msg = (f"🚨TRADE SIGNAL🚨\n\n"
           f"📉 {get_flag(base)} {base}/{quote} {get_flag(quote)} (OTC)\n"
           f"⏰ Expiry: {EXPIRY_MINUTES} minutes\n"
           f"📍 Entry Time: {entry_time.strftime('%I:%M:%S %p')}\n"
           f"📈 Direction: {direction} {'🟩' if direction=='BUY' else '🟥'}\n\n"
           f"🎯 Martingale Levels:\n" +
           "".join([f"🔁 Level {i+1} → {t.strftime('%I:%M:%S %p')}\n" for i, t in enumerate(mg_times)]) +
           f"\nConfidence: {score:.0f}%\nStrength: {strength:.0f}%\nMode: HIGH ACCURACY DAY TRADING")
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        logging.error(f"Telegram send error: {e}")

# -------------------------------
# SYMBOL MANAGEMENT
# -------------------------------
async def load_otc_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols": "brief"}))
            response = json.loads(await ws.recv())
            if "active_symbols" not in response:
                return []
            return [s["symbol"] for s in response["active_symbols"]
                    if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except:
        return []

# -------------------------------
# MAIN BOT LOOP
# -------------------------------
async def monitor():
    global last_candle_time, pending_signal, signal_sent_this_candle
    while True:
        try:
            symbols = await load_otc_symbols()
            if not symbols:
                await asyncio.sleep(SYMBOL_REFRESH_INTERVAL)
                continue
            # Initialize state for new symbols
            for s in symbols:
                if s not in prices:
                    prices[s] = []
                    tick_confirm[s] = {"count": 0, "direction": None}
            print(f"BOT STARTED with symbols: {symbols}")
            async with websockets.connect(DERIV_WS) as ws:
                # Subscribe to live ticks
                for s in symbols:
                    await ws.send(json.dumps({"ticks": s, "subscribe": 1}))
                async for message in ws:
                    data = json.loads(message)
                    if "tick" not in data:
                        continue
                    pair = data["tick"]["symbol"]
                    price = data["tick"]["quote"]
                    prices[pair].append(price)
                    if len(prices[pair]) > MAX_PRICES:
                        prices[pair].pop(0)
                    score, strength, direction = detect_trend(prices[pair])
                    # Tick confirmation & spike filter
                    if direction and score >= TREND_SCORE_BASE and strength >= TREND_STRENGTH_BASE:
                        if tick_confirm[pair]["direction"] == direction:
                            tick_confirm[pair]["count"] += 1
                        else:
                            tick_confirm[pair]["direction"] = direction
                            tick_confirm[pair]["count"] = 1
                        if tick_confirm[pair]["count"] >= TICK_CONFIRMATION:
                            # Spike filter (>1% move)
                            if len(prices[pair]) > 1 and abs(prices[pair][-1]-prices[pair][-2])/prices[pair][-2] > 0.01:
                                continue
                            pending_signal = (pair, direction, score, strength)
                    else:
                        tick_confirm[pair] = {"count": 0, "direction": None}

                    # Candle management
                    now = datetime.now(TIMEZONE)
                    candle_time = now.replace(second=0, microsecond=0)
                    minute = candle_time.minute - (candle_time.minute % 3)
                    candle_time = candle_time.replace(minute=minute)
                    if last_candle_time is None:
                        last_candle_time = candle_time
                    if candle_time > last_candle_time:
                        last_candle_time = candle_time
                        signal_sent_this_candle = False

                    # Send signal if validated
                    if pending_signal and not signal_active() and not signal_sent_this_candle:
                        seconds_into_candle = now.second
                        if seconds_into_candle >= 10:
                            pair_check, dir_check, score_check, strength_check = pending_signal
                            score2, strength2, direction2 = detect_trend(prices[pair_check])
                            if (direction2 == dir_check and score2 >= TREND_SCORE_BASE
                                and strength2 >= TREND_STRENGTH_BASE
                                and tick_confirm[pair_check]["count"] >= TICK_CONFIRMATION):
                                send_signal(pair_check, dir_check, score2, strength2)
                                signal_sent_this_candle = True
                            pending_signal = None
        except Exception as e:
            logging.warning(f"Reconnecting after error: {e}")
            await asyncio.sleep(RETRY_SECONDS)

# -------------------------------
# START BOT
# -------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(monitor())
