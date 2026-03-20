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
EXPIRY_MINUTES = 1  # 1-minute trade
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]
LOSS_FREEZE_COUNT = 2
MIN_SIGNAL_INTERVAL = 1800  # 30 minutes per pair minimum
MIN_PULLBACK_DURATION = 180  # minimum 3 minutes
MAX_PULLBACK_DURATION = 300  # maximum 5 minutes

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
historical_memory = {}
pair_losses = defaultdict(int)
active_signals = []
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))
pullback_observing = defaultdict(lambda: False)
pullback_start_time = defaultdict(lambda: None)
observing_pair = None  # Only one pair observed at a time

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ----------------------
# EMA
# ----------------------
def ema(data, period):
    if len(data) < period: return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data: val = p*k + val*(1-k)
    return val

# ----------------------
# TREND DETECTION
# ----------------------
def detect_trend(p):
    if len(p) < 50: return None
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if not all([e1,e2,e3,e4]): return None
    if e1>e2 and e3>e4: return "BUY"
    if e1<e2 and e3<e4: return "SELL"
    return None

# ----------------------
# PULLBACK DETECTION
# ----------------------
def is_pullback(p, direction):
    if len(p) < OBSERVATION_TICKS + 3: return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY": return np.any(last_diff < 0)
    if direction=="SELL": return np.any(last_diff > 0)
    return False

def is_stable_move(p, direction):
    if len(p) < OBSERVATION_TICKS + 5: return False
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY": return np.all(last_diff>0)
    if direction=="SELL": return np.all(last_diff<0)
    return False

def is_market_stable(p):
    if len(p)<30: return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    return std/mean<0.005

# ----------------------
# TELEGRAM
# ----------------------
def send_asset(pair):
    msg=f"""SIGNAL ⚠️
Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}
Observing massive pullback..."""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Observing massive pullback for: {pair}")

def send_final(pair, direction):
    arrow="⬆️" if direction=="BUY" else "⬇️"
    msg=f"""SIGNAL {arrow}
Asset: {pair}_otc
Payout: 92%
Expiration: M{EXPIRY_MINUTES}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Final trade signal sent: {pair} {direction}")

# ----------------------
# LOAD SYMBOLS
# ----------------------
async def load_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
    except Exception as e:
        logging.warning(f"Failed to load symbols: {e}")
        return []

# ----------------------
# MONITOR LOOP
# ----------------------
async def monitor():
    global active_signals,last_signal_times,pullback_observing,pullback_start_time,observing_pair

    while True:
        try:
            symbols = await load_symbols()
            if not symbols: await asyncio.sleep(5); continue

            for s in symbols:
                if s not in prices: prices[s]=deque(maxlen=MAX_PRICES)
                if s not in historical_memory: historical_memory[s]=deque(maxlen=1000)

            async with websockets.connect(DERIV_WS) as ws:
                for pair in symbols: await ws.send(json.dumps({"ticks":pair,"subscribe":1}))

                async for msg in ws:
                    try:
                        data=json.loads(msg)
                        if "tick" not in data: continue

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        if pair_losses[pair]>=LOSS_FREEZE_COUNT: continue
                        prices[pair].append(price)
                        historical_memory[pair].append(price)
                        now = datetime.now(TIMEZONE)

                        if observing_pair is not None and pair != observing_pair:
                            continue  # Only observe one pair at a time

                        direction = detect_trend(list(prices[pair]))
                        if not direction: continue

                        # Start observing a pullback
                        if not pullback_observing[pair]:
                            if is_pullback(list(prices[pair]), direction):
                                logging.info(f"Massive pullback detected for {pair} ({direction})")
                                pullback_observing[pair] = True
                                pullback_start_time[pair] = now
                                observing_pair = pair
                                send_asset(pair)
                                continue
                            else:
                                continue

                        # Confirm pullback duration before sending signal
                        if pullback_observing[pair]:
                            duration = (now - pullback_start_time[pair]).total_seconds()
                            if duration < MIN_PULLBACK_DURATION:
                                continue
                            if duration > MAX_PULLBACK_DURATION:
                                logging.info(f"Pullback duration too long for {pair}, resetting.")
                                pullback_observing[pair] = False
                                pullback_start_time[pair] = None
                                prices[pair].clear()
                                observing_pair = None
                                continue

                            if not is_stable_move(list(prices[pair]), direction): continue
                            if not is_market_stable(list(prices[pair])): continue

                            seconds_since_last = (now-last_signal_times[pair]).total_seconds()
                            if seconds_since_last<MIN_SIGNAL_INTERVAL: continue

                            send_final(pair,direction)
                            last_signal_times[pair] = now
                            active_signals.append(pair)

                            await asyncio.sleep(EXPIRY_MINUTES*60)

                            final_price = historical_memory[pair][-1]
                            result = (direction=="BUY" and final_price>prices[pair][-1]) or (direction=="SELL" and final_price<prices[pair][-1])
                            pair_losses[pair] = 0 if result else pair_losses[pair]+1

                            # Reset after trade
                            active_signals.remove(pair)
                            pullback_observing[pair] = False
                            pullback_start_time[pair] = None
                            prices[pair].clear()
                            observing_pair = None

                    except Exception as e_tick:
                        logging.error(f"Tick error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
