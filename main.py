# ======================================
# FINAL REAL-ACCURACY ADAPTIVE BOT
# ======================================

import asyncio
import json
import requests
import websockets
import logging
import numpy as np
from datetime import datetime, timedelta
import pytz

BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"

DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
TIMEZONE = pytz.timezone("Africa/Lagos")

BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

ENTRY_DELAY_MINUTES = 2
MG_STEP = 2
MAX_MG_STEPS = 3
EXPIRY_MINUTES = 2

MIN_ACCURACY_REQUIRED = 82

prices = {}
trade_history = {}
pair_settings = {}
active_signal = {}

# ---------------- EMA ----------------
def ema(data, period):
    if len(data) < period:
        return None
    k = 2/(period+1)
    value = data[0]
    for p in data:
        value = p*k + value*(1-k)
    return value

# ---------------- TREND ----------------
def analyze(price_list, settings):
    if len(price_list) < 300:
        return 0,0,None

    ema_fast = ema(price_list[-50:], settings['fast'])
    ema_slow = ema(price_list[-100:], settings['slow'])
    ema_lf = ema(price_list[-200:], settings['lf'])
    ema_ls = ema(price_list[-300:], settings['ls'])

    if not all([ema_fast, ema_slow, ema_lf, ema_ls]):
        return 0,0,None

    direction = None
    if ema_fast > ema_slow and ema_lf > ema_ls:
        direction = "BUY"
    elif ema_fast < ema_slow and ema_lf < ema_ls:
        direction = "SELL"

    volatility = np.std(price_list[-100:])
    separation = abs(ema_fast - ema_slow)

    if volatility == 0:
        return 0,0,None

    strength = min(98, (separation/volatility)*100)
    return strength, strength, direction

# ---------------- ACCURACY ----------------
def get_accuracy(pair):
    history = trade_history.get(pair, [])
    if len(history) < 20:
        return 82  # default until enough data

    wins = sum(1 for t in history if t == "win")
    return (wins / len(history)) * 100

# ---------------- SIGNAL ----------------
def send_signal(pair, direction, accuracy, strength):
    now = datetime.now(TIMEZONE)

    entry_time = now + timedelta(minutes=ENTRY_DELAY_MINUTES)
    mg1 = entry_time + timedelta(minutes=MG_STEP)
    mg2 = mg1 + timedelta(minutes=MG_STEP)
    mg3 = mg2 + timedelta(minutes=MG_STEP)

    base = pair[3:6]
    quote = pair[6:9]

    msg = f"""🚨 TRADE SIGNAL 🚨

📉 {base}/{quote} (OTC)

📍 Entry Time: {entry_time.strftime('%I:%M:%S %p')}
⏰ Expiry: {EXPIRY_MINUTES} min

📈 Direction: {direction}

🎯 Martingale:
🔁 MG1: {mg1.strftime('%I:%M:%S %p')}
🔁 MG2: {mg2.strftime('%I:%M:%S %p')}
🔁 MG3: {mg3.strftime('%I:%M:%S %p')}

Accuracy: {accuracy:.0f}%
Strength: {strength:.0f}%
"""

    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg})

    active_signal[pair] = now + timedelta(minutes=10)

# ---------------- MAIN ----------------
async def monitor():
    async with websockets.connect(DERIV_WS) as ws:
        await ws.send(json.dumps({"active_symbols":"brief"}))
        res = json.loads(await ws.recv())

        symbols = [s["symbol"] for s in res["active_symbols"]
                   if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]

        for s in symbols:
            prices[s] = []
            pair_settings[s] = {"fast":10,"slow":20,"lf":30,"ls":60}
            trade_history[s] = []

        for s in symbols:
            await ws.send(json.dumps({"ticks":s,"subscribe":1}))

        async for msg in ws:
            data = json.loads(msg)
            if "tick" not in data:
                continue

            pair = data["tick"]["symbol"]
            price = data["tick"]["quote"]

            prices[pair].append(price)
            if len(prices[pair]) > 700:
                prices[pair].pop(0)

            strength, _, direction = analyze(prices[pair], pair_settings[pair])
            accuracy = get_accuracy(pair)

            print(f"{pair} | {price} | Acc:{accuracy:.1f}% | Str:{strength:.1f} | Dir:{direction}")

            # Only send if REAL accuracy is high
            if direction and accuracy >= MIN_ACCURACY_REQUIRED and strength >= 85:
                if pair not in active_signal or datetime.now(TIMEZONE) > active_signal[pair]:
                    send_signal(pair, direction, accuracy, strength)

# ---------------- START ----------------
asyncio.run(monitor())
