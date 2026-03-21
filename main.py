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
COINCAP_WS = "wss://ws.coincap.io/prices?assets=ALL"
TIMEZONE = pytz.timezone("Africa/Lagos")
EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
MIN_SIGNAL_INTERVAL = 1800  # 30 minutes min between signals
MAX_SIGNAL_PER_HOUR = 2
FILTER_THRESHOLD = 0.95  # 95% bad patterns filtered

# ----------------------
# GLOBAL STATE
# ----------------------
prices = defaultdict(lambda: deque(maxlen=MAX_PRICES))
signal_history = defaultdict(list)
adaptive_weights = {"ema":0.25,"momentum":0.25,"volatility":0.25,"pullback":0.25}
pair_losses = defaultdict(int)
active_signals = []
last_signal_times = defaultdict(lambda: datetime.min.replace(tzinfo=TIMEZONE))

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
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if not all([e1,e2,e3,e4]): return None
    if e1>e2 and e3>e4: return "BUY"
    if e1<e2 and e3<e4: return "SELL"
    return None

# ----------------------
# PULLBACK & STABILITY
# ----------------------
def is_stable_and_no_pullback(p,direction):
    if len(p)<OBSERVATION_TICKS+5: return False
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
# ACCURACY CALCULATION
# ----------------------
def calculate_accuracy(p,direction):
    score=0
    e1 = ema(p[-10:],3)
    e2 = ema(p[-20:],5)
    e3 = ema(p[-30:],8)
    e4 = ema(p[-50:],13)
    if direction=="BUY" and e1>e2 and e3>e4: score+=adaptive_weights["ema"]*100
    if direction=="SELL" and e1<e2 and e3<e4: score+=adaptive_weights["ema"]*100
    diff = np.diff(p[-5:])
    if direction=="BUY" and np.all(diff>0): score+=adaptive_weights["momentum"]*100
    if direction=="SELL" and np.all(diff<0): score+=adaptive_weights["momentum"]*100
    std = np.std(p[-30:])
    mean = np.mean(p[-30:])
    if std/mean<0.005: score+=adaptive_weights["volatility"]*100
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY" and np.all(last_diff>0): score+=adaptive_weights["pullback"]*100
    if direction=="SELL" and np.all(last_diff<0): score+=adaptive_weights["pullback"]*100
    return min(score,100)

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
def send_signal(pair,direction,accuracy):
    arrow="⬆️" if direction=="BUY" else "⬇️"
    msg=f"SIGNAL {arrow}\nAsset: {pair}\nAccuracy: {accuracy}%\nTime: {datetime.now(TIMEZONE).strftime('%H:%M')}"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
    logging.info(f"Sent signal for {pair} direction {direction} accuracy {accuracy}")

# ----------------------
# DERIV LOAD SYMBOLS
# ----------------------
async def load_deriv_symbols():
    try:
        async with websockets.connect(DERIV_WS) as ws:
            await ws.send(json.dumps({"active_symbols":"brief"}))
            res = json.loads(await ws.recv())
            return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx")]
    except:
        return []

# ----------------------
# RANKING FUNCTION (Top 2 Pairs)
# ----------------------
def rank_top_pairs():
    scores = {}
    for pair, pdeque in prices.items():
        if len(pdeque)<50: continue
        direction = detect_trend(list(pdeque))
        if not direction: continue
        if not is_stable_and_no_pullback(list(pdeque),direction): continue
        if not is_market_stable(list(pdeque)): continue
        scores[pair] = calculate_accuracy(list(pdeque),direction)
    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:2]  # top 2 pairs

# ----------------------
# MONITOR LOOP
# ----------------------
async def monitor():
    global active_signals,last_signal_times

    while True:
        try:
            deriv_symbols = await load_deriv_symbols()
            if not deriv_symbols:
                await asyncio.sleep(5)
                continue

            for s in deriv_symbols:
                if s not in prices: prices[s]=deque(maxlen=MAX_PRICES)

            async with websockets.connect(DERIV_WS) as deriv_ws, websockets.connect(COINCAP_WS) as coin_ws:
                for pair in deriv_symbols:
                    await deriv_ws.send(json.dumps({"ticks":pair,"subscribe":1}))

                async def handle_deriv():
                    async for msg in deriv_ws:
                        try:
                            data=json.loads(msg)
                            if "tick" not in data: continue
                            pair = data["tick"]["symbol"]
                            price = data["tick"]["quote"]
                            prices[pair].append(price)
                        except Exception as e:
                            logging.error(f"Deriv tick error: {e}")

                async def handle_coin():
                    async for msg in coin_ws:
                        try:
                            data = json.loads(msg)
                            for pair,price in data.items():
                                prices[pair].append(price)
                        except Exception as e:
                            logging.error(f"CoinCap tick error: {e}")

                async def signal_loop():
                    while True:
                        top_pairs = rank_top_pairs()
                        for pair,score in top_pairs:
                            now = datetime.now(TIMEZONE)
                            if (now - last_signal_times[pair]).total_seconds() < MIN_SIGNAL_INTERVAL:
                                continue
                            if len(active_signals)>=MAX_SIGNAL_PER_HOUR: break
                            direction = detect_trend(list(prices[pair]))
                            if not direction: continue
                            send_signal(pair,direction,score)
                            last_signal_times[pair] = now
                            active_signals.append(pair)
                            await asyncio.sleep(EXPIRY_MINUTES*60)
                            final_price = prices[pair][-1]
                            result = (direction=="BUY" and final_price>prices[pair][0]) or (direction=="SELL" and final_price<prices[pair][0])
                            update_adaptive_weights(pair,direction,result)
                            active_signals.remove(pair)
                            prices[pair].clear()
                        await asyncio.sleep(10)

                await asyncio.gather(handle_deriv(), handle_coin(), signal_loop())

        except Exception as e_outer:
            logging.error(f"Main loop error: {e_outer}")
            await asyncio.sleep(5)

# ----------------------
# RUN SYSTEM
# ----------------------
asyncio.run(monitor())
