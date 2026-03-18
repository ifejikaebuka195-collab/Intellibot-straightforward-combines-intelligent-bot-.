# ======================================  
# POCKET OPTION OTC SIGNAL BOT  
# HIGH ACCURACY DAY TRADING VERSION  
# 3-MIN CANDLE, STRICT LOCK, SLOW SIGNALS  
# TICK CONFIRMATION FILTER  
# ======================================  

import asyncio  
import json  
import requests  
import websockets  
import logging  
import numpy as np  
from datetime import datetime, timedelta  
import pytz  

# ================================  
# TELEGRAM SETTINGS  
# ================================  
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"  
CHAT_ID = "6918721957"  

# ================================  
# GENERAL SETTINGS  
# ================================  
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"  
TIMEZONE = pytz.timezone("Africa/Lagos")  

TREND_SCORE_THRESHOLD = 92  
TREND_STRENGTH_THRESHOLD = 98  

ENTRY_DELAY = 2  
MG_STEP = 2  
MAX_MG_STEPS = 3  
EXPIRY_MINUTES = 2  

MAX_PRICES = 700  
RETRY_SECONDS = 5  
SYMBOL_REFRESH_INTERVAL = 5  

TICK_CONFIRMATION = 3  

# ================================
# 🔴 FINAL CONFIRMATION SETTINGS (ADDED ONLY)
# ================================
FINAL_CONFIRM_TICKS = 5

# ================================
# 🔴 DURATION POWER CHECK SETTINGS (ADDED ONLY)
# ================================
DURATION_LOOKBACK_SECONDS = EXPIRY_MINUTES * 60  # look at full expiry duration

# ================================  
# BLOCKED PAIRS  
# ================================  
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]  

# ================================  
# STATE  
# ================================  
prices = {}  
tick_confirm = {}  

active_signal = {"pair": None, "expiry_time": None}  

last_candle_time = None  
pending_signal = None  
signal_sent_this_candle = False  

# ================================  
# EMA FUNCTION  
# ================================  
def ema(data, period):  
    if len(data) < period:  
        return None  
    k = 2/(period+1)  
    value = data[0]  
    for price in data:  
        value = price*k + value*(1-k)  
    return value  

# ================================
# 🔴 FINAL CONFIRM FUNCTION (ADDED ONLY)
# ================================
def final_confirmation(price_list, direction):
    if len(price_list) < FINAL_CONFIRM_TICKS:
        return False
    recent = price_list[-FINAL_CONFIRM_TICKS:]
    moves = np.diff(recent)
    
    if direction == "BUY":
        return np.all(moves >= 0)
    elif direction == "SELL":
        return np.all(moves <= 0)
    return False

# ================================
# 🔴 DURATION POWER CHECK FUNCTION (ADDED ONLY)
# ================================
def duration_power_check(price_list, duration_seconds=DURATION_LOOKBACK_SECONDS):
    if len(price_list) < 2:
        return False
    ticks_to_check = min(len(price_list), duration_seconds)
    recent_prices = price_list[-ticks_to_check:]
    moves = np.diff(recent_prices)
    # Strong, consistent move in one direction
    if np.all(moves >= 0) or np.all(moves <= 0):
        return True
    return False

# ================================  
# TREND STRENGTH  
# ================================  
def trend_strength(price_list):  
    if len(price_list) < 150:  
        return 0  
    ema_fast = ema(price_list[-50:],10)  
    ema_slow = ema(price_list[-100:],20)  
    if ema_fast is None or ema_slow is None:  
        return 0  
    separation = abs(ema_fast-ema_slow)  
    volatility = np.std(price_list[-100:])  
    if volatility == 0:  
        return 0  
    strength = (separation/volatility)*100  
    if strength >= 98:  
        return 98  
    else:  
        return 0  

# ================================  
# TREND DETECTION  
# ================================  
def detect_trend(price_list):  
    if len(price_list) < 300:  
        return 0,0,None  
    ema_fast = ema(price_list[-50:],10)  
    ema_slow = ema(price_list[-100:],20)  
    ema_long_fast = ema(price_list[-200:],30)  
    ema_long_slow = ema(price_list[-300:],60)  

    strength = trend_strength(price_list)  

    if strength < 98:  
        return 0, strength, None  

    score = 99  

    direction = None  
    if ema_fast and ema_slow and ema_long_fast and ema_long_slow:  
        if ema_fast > ema_slow and ema_long_fast > ema_long_slow:  
            direction = "BUY"  
        elif ema_fast < ema_slow and ema_long_fast < ema_long_slow:  
            direction = "SELL"  

    return score, strength, direction  

# ================================  
# SIGNAL LOCK  
# ================================  
def signal_active():  
    if active_signal["expiry_time"] is None:  
        return False  
    now = datetime.now(TIMEZONE)  
    return now < active_signal["expiry_time"]  

def register_signal(pair):  
    now = datetime.now(TIMEZONE)  
    total_lock_minutes = ENTRY_DELAY + (MG_STEP*MAX_MG_STEPS) + EXPIRY_MINUTES  
    active_signal["pair"] = pair  
    active_signal["expiry_time"] = now + timedelta(minutes=total_lock_minutes)  

# ================================  
# FLAGS  
# ================================  
def get_flag(code):  
    flags = {  
        "USD":"🇺🇸","EUR":"🇪🇺","GBP":"🇬🇧","CHF":"🇨🇭",
        "JPY":"🇯🇵","AUD":"🇦🇺","CAD":"🇨🇦","NZD":"🇳🇿"
    }  
    return flags.get(code.upper(),"")  

# ================================  
# SEND TELEGRAM SIGNAL  
# ================================  
def send_signal(pair,direction,score,strength):  
    if signal_active():  
        return  
    now = datetime.now(TIMEZONE)  
    entry_time = now + timedelta(minutes=ENTRY_DELAY)  
    mg_times = [entry_time + timedelta(minutes=MG_STEP*i)
                for i in range(1,MAX_MG_STEPS+1)]  
    register_signal(pair)  
    base = pair[3:6].upper()  
    quote = pair[6:9].upper()  
    msg = (  
        f"🚨TRADE NOW!!\n\n"
        f"📉{get_flag(base)} {base}/{quote} {get_flag(quote)} (OTC)\n"
        f"⏰ Expiry: {EXPIRY_MINUTES} minutes\n"
        f"📍 Entry Time: {entry_time.strftime('%I:%M %p')}\n"
        f"📈 Direction: {direction} {'🟩' if direction=='BUY' else '🟥'}\n\n"
        f"🎯 Martingale Levels:\n"
        f"🔁 Level 1 → {mg_times[0].strftime('%I:%M %p')}\n"
        f"🔁 Level 2 → {mg_times[1].strftime('%I:%M %p')}\n"
        f"🔁 Level 3 → {mg_times[2].strftime('%I:%M %p')}\n\n"
        f"Confidence: {score:.0f}%\n"
        f"Strength: {strength:.0f}%\n"
        f"Mode: HIGH ACCURACY DAY TRADING"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg},
            timeout=10
        )
    except:
        logging.info("Telegram error")
  
# ================================  
# LOAD SYMBOLS  
# ================================  
async def load_otc_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            response = json.loads(await ws.recv())
            if "active_symbols" not in response:
                return []
            return [
                s["symbol"]
                for s in response["active_symbols"]
                if s["symbol"].startswith("frx")
                and s["symbol"] not in BLOCKED_PAIRS
            ]
    except:
        return []
  
# ================================  
# MAIN LOOP  
# ================================  
async def monitor():
    global last_candle_time, pending_signal, signal_sent_this_candle
    while True:
        try:
            symbols = await load_otc_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue
            for s in symbols:
                prices[s] = []
                tick_confirm[s] = {"count":0,"direction":None}

            print("BOT STARTED")

            async with websockets.connect(DERIV_WS) as ws:
                for s in symbols:
                    await ws.send(json.dumps({"ticks":s,"subscribe":1}))

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

                    if direction and score>=TREND_SCORE_THRESHOLD and strength>=TREND_STRENGTH_THRESHOLD:
                        if tick_confirm[pair]["direction"]==direction:
                            tick_confirm[pair]["count"]+=1
                        else:
                            tick_confirm[pair]["direction"]=direction
                            tick_confirm[pair]["count"]=1
                        if tick_confirm[pair]["count"]>=TICK_CONFIRMATION:
                            pending_signal=(pair,direction,score,strength)
                    else:
                        tick_confirm[pair]["count"]=0
                        tick_confirm[pair]["direction"]=None

                    now = datetime.now(TIMEZONE)
                    candle_time = now.replace(second=0,microsecond=0)
                    minute = candle_time.minute - (candle_time.minute % 3)
                    candle_time = candle_time.replace(minute=minute)
                    if last_candle_time is None:
                        last_candle_time = candle_time
                    if candle_time > last_candle_time:
                        last_candle_time = candle_time
                        signal_sent_this_candle = False

                    if pending_signal and not signal_active() and not signal_sent_this_candle:
                        seconds_into_candle = now.second
                        if seconds_into_candle >= 10:
                            pair_check, dir_check, score_check, strength_check = pending_signal
                            score2, strength2, direction2 = detect_trend(prices[pair_check])

                            if (direction2 == dir_check and
                                strength2 == 98 and
                                tick_confirm[pair_check]["count"]>=TICK_CONFIRMATION and
                                final_confirmation(prices[pair_check], dir_check) and
                                duration_power_check(prices[pair_check])):

                                send_signal(pair_check, dir_check, score2, strength2)
                                signal_sent_this_candle = True

                            pending_signal = None

        except:
            logging.info("Reconnecting...")
            await asyncio.sleep(RETRY_SECONDS)

# ================================  
# START BOT  
# ================================  
asyncio.run(monitor())
