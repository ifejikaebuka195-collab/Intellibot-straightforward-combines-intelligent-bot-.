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
EXPIRY_MINUTES = 1  # 1-minute expiry for pullback trades
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]
LOSS_FREEZE_COUNT = 2
MIN_SIGNAL_INTERVAL = 1800  # 30 minutes per pair minimum between signals

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
historical_memory = {}
signal_history = defaultdict(list)
pair_losses = defaultdict(int)
adaptive_weights = {"ema":0.25,"momentum":0.25,"volatility":0.25,"pullback":0.25}
active_signals = []
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))
pullback_observing = defaultdict(lambda: False)

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

# ----------------------
# MARKET NOISE FILTER
# ----------------------
def is_market_stable(p):
    if len(p)<30: return False
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    return std/mean<0.005

# ----------------------
# ADAPTIVE LEARNING
# ----------------------
def update_adaptive_weights(pair,direction,result):
    signal_history[pair].append(result)
    if len(signal_history[pair])>100: signal_history[pair].pop(0)
    for k in adaptive_weights:
        if result: adaptive_weights[k]=min(0.4,adaptive_weights[k]+0.01)
        else: adaptive_weights[k]=max(0.15,adaptive_weights[k]-0.01)
    if not result: pair_losses[pair]+=1
    else: pair_losses[pair]=0
    logging.info(f"Adaptive weights: {adaptive_weights} | Pair losses: {dict(pair_losses)}")

# ----------------------
# TELEGRAM
# ----------------------
def send_asset(pair):
    msg=f"""SIGNAL ⚠️
Asset: {pair}_otc
Expiration: M{EXPIRY_MINUTES}
Observing pullback for 1-minute trade..."""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Pullback observation started: {pair}")

def send_final(pair,direction):
    arrow="⬆️" if direction=="BUY" else "⬇️"
    msg=f"""SIGNAL {arrow}
Asset: {pair}_otc
Payout: 92%
Expiration: M{EXPIRY_MINUTES}"""
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Final signal sent: {pair} {direction}")

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
# MONITOR LOOP (POWERFUL PULLBACK 1-MIN)
# ----------------------
async def monitor():
    global active_signals,last_signal_times,pullback_observing

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

                        pair=data["tick"]["symbol"]
                        price=data["tick"]["quote"]

                        if pair_losses[pair]>=LOSS_FREEZE_COUNT: continue
                        prices[pair].append(price)
                        historical_memory[pair].append(price)
                        now=datetime.now(TIMEZONE)

                        direction = detect_trend(list(prices[pair]))
                        if not direction: continue

                        # Only detect powerful pullbacks first
                        if not pullback_observing[pair]:
                            if is_pullback(list(prices[pair]), direction):
                                logging.info(f"Powerful pullback detected for {pair} ({direction})")
                                pullback_observing[pair] = True
                                send_asset(pair)
                                continue
                            else: continue

                        # Wait for stable move to confirm 1-min trade
                        if pullback_observing[pair]:
                            if not is_stable_move(list(prices[pair]), direction): continue
                            if not is_market_stable(list(prices[pair])): continue

                            seconds_since_last = (now-last_signal_times[pair]).total_seconds()
                            if seconds_since_last<MIN_SIGNAL_INTERVAL: continue

                            send_final(pair,direction)

                            last_signal_times[pair]=now
                            active_signals.append(pair)

                            await asyncio.sleep(EXPIRY_MINUTES*60)
                            final_price=historical_memory[pair][-1]
                            result=(direction=="BUY" and final_price>prices[pair][-1]) or (direction=="SELL" and final_price<prices[pair][-1])
                            update_adaptive_weights(pair,direction,result)

                            active_signals.remove(pair)
                            prices[pair].clear()
                            pullback_observing[pair]=False

                    except Exception as e_tick:
                        logging.error(f"Tick error: {e_tick}")

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN
# ----------------------
asyncio.run(monitor())
