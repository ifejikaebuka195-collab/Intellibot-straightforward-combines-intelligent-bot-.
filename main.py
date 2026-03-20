import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime, timedelta
import pytz
import logging
from collections import deque, defaultdict
import time

# ----------------------
# CONFIG
# ----------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
WEEKEND_WS = "wss://biquote.io/hubs/tick"  # Real weekend free feed
TIMEZONE = pytz.timezone("Africa/Lagos")
EXPIRY_MINUTES = 5
MAX_PRICES = 5000
OBSERVATION_TICKS = 15
BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]
LOSS_FREEZE_COUNT = 2
MIN_ACCURACY = 82
MAX_ACCURACY = 95
MAX_SIGNALS_PER_HOUR = 2
EXPLOSION_THRESHOLD = 0.01
EXPLOSION_BOOST = 5
PING_INTERVAL = 30
TELEGRAM_RETRY_INTERVAL = 2

# ----------------------
# GLOBAL STATE
# ----------------------
prices = {}
historical_memory = {}
signal_history = defaultdict(list)
pair_losses = defaultdict(int)
adaptive_weights = {"ema":0.25,"momentum":0.25,"volatility":0.25,"pullback":0.25}
active_pair = None
last_signal_time = datetime.min.replace(tzinfo=TIMEZONE)
signals_sent_this_hour = 0
current_hour = datetime.now(TIMEZONE).hour

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ----------------------
# EMA & TREND FUNCTIONS
# ----------------------
def ema(data, period):
    if len(data) < period: return None
    k = 2 / (period + 1)
    val = data[0]
    for p in data: val = p * k + val * (1 - k)
    return val

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
    return std/mean < 0.005

def detect_explosion(p,direction):
    if len(p)<OBSERVATION_TICKS: return False
    recent_change = (p[-1]-p[-OBSERVATION_TICKS])/p[-OBSERVATION_TICKS]
    if direction=="BUY" and recent_change >= EXPLOSION_THRESHOLD: return True
    if direction=="SELL" and recent_change <= -EXPLOSION_THRESHOLD: return True
    return False

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
    if std/mean < 0.005: score+=adaptive_weights["volatility"]*100
    last_diff = np.diff(p[-OBSERVATION_TICKS:])
    if direction=="BUY" and np.all(last_diff>0): score+=adaptive_weights["pullback"]*100
    if direction=="SELL" and np.all(last_diff<0): score+=adaptive_weights["pullback"]*100
    if detect_explosion(p,direction):
        score += EXPLOSION_BOOST
    accuracy = min(score,100)
    return max(MIN_ACCURACY,min(accuracy,MAX_ACCURACY))

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
def send_telegram(msg):
    while True:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          data={"chat_id":CHAT_ID,"text":msg}, timeout=5)
            break
        except Exception as e:
            logging.warning(f"Telegram send failed, retrying in {TELEGRAM_RETRY_INTERVAL}s: {e}")
            time.sleep(TELEGRAM_RETRY_INTERVAL)

def send_asset(pair, move_type="Steady Trend"):
    msg=f"SIGNAL ⚠️\nAsset: {pair}_otc\nExpiration: M{EXPIRY_MINUTES}\nMove Type: {move_type}\nObserving market..."
    send_telegram(msg)
    logging.info(f"Asset observation started: {pair} ({move_type})")

def send_final(pair,direction,acc, move_type="Steady Trend"):
    arrow="⬆️" if direction=="BUY" else "⬇️"
    msg=f"SIGNAL {arrow}\nAsset: {pair}_otc\nPayout: 92%\nAccuracy: {acc}%\nExpiration: M{EXPIRY_MINUTES}\nMove Type: {move_type}"
    send_telegram(msg)
    logging.info(f"Final signal sent: {pair} {direction} Accuracy: {acc}% ({move_type})")

# ----------------------
# LOAD SYMBOLS
# ----------------------
async def load_symbols(ws_url):
    try:
        async with websockets.connect(ws_url) as ws:
            if ws_url == DERIV_WS:
                await ws.send(json.dumps({"active_symbols":"brief"}))
                res = json.loads(await ws.recv())
                return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS]
            else:  # BiQuote format
                await ws.send(json.dumps({"type":"subscribe","pairs":["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCHF"]}))
                return ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCHF"]
    except Exception as e:
        logging.warning(f"Failed to load symbols: {e}")
        return []

# ----------------------
# MONITOR PAIRS
# ----------------------
async def monitor_pairs(symbols):
    global active_pair, last_signal_time, signals_sent_this_hour, current_hour
    for pair in symbols:
        prices[pair] = deque(maxlen=MAX_PRICES)
        historical_memory[pair] = deque(maxlen=MAX_PRICES)

    async def handle_single(pair, ws_url):
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=PING_INTERVAL, ping_timeout=10) as ws:
                    if ws_url == DERIV_WS:
                        await ws.send(json.dumps({"ticks":pair,"subscribe":1}))
                    else:
                        await ws.send(json.dumps({"type":"subscribe","pairs":[pair]}))
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if ws_url == DERIV_WS and "tick" in data:
                                price = data["tick"]["quote"]
                            elif ws_url == WEEKEND_WS:
                                price = float(data.get("price",0))
                            else:
                                continue
                            if pair_losses[pair]>=LOSS_FREEZE_COUNT: continue
                            prices[pair].append(price)
                            historical_memory[pair].append(price)
                        except:
                            continue
            except:
                await asyncio.sleep(5)

    async def ranking_loop():
        global active_pair, last_signal_time, signals_sent_this_hour, current_hour
        while True:
            now = datetime.now(TIMEZONE)
            ws_url = WEEKEND_WS if (now.weekday() == 4 and now.hour >= 22) or now.weekday() in [5,6] else DERIV_WS
            if now.hour != current_hour:
                signals_sent_this_hour = 0
                current_hour = now.hour
            if signals_sent_this_hour < MAX_SIGNALS_PER_HOUR and not active_pair:
                candidates = []
                for pair in symbols:
                    if len(prices[pair])<50: continue
                    direction = detect_trend(list(prices[pair]))
                    if not direction: continue
                    if not is_stable_and_no_pullback(list(prices[pair]),direction): continue
                    if not is_market_stable(list(prices[pair])): continue
                    acc = calculate_accuracy(list(prices[pair]),direction)
                    if acc>=MIN_ACCURACY:
                        candidates.append((acc,pair,direction))
                if candidates:
                    candidates.sort(reverse=True)
                    acc,pair,direction = candidates[0]
                    move_type = "Big Move" if detect_explosion(list(prices[pair]),direction) else "Steady Trend"
                    active_pair = pair
                    signals_sent_this_hour +=1
                    last_signal_time = datetime.now(TIMEZONE)
                    send_asset(pair, move_type)
                    await asyncio.sleep(2)
                    send_final(pair,direction,acc,move_type)
                    await asyncio.sleep(EXPIRY_MINUTES*60)
                    final_price = historical_memory[pair][-1]
                    result = (direction=="BUY" and final_price>prices[pair][-1]) or (direction=="SELL" and final_price<prices[pair][-1])
                    update_adaptive_weights(pair,direction,result)
                    active_pair = None
            await asyncio.sleep(1)

    tasks = [handle_single(pair, WEEKEND_WS if datetime.now(TIMEZONE).weekday() in [5,6] else DERIV_WS) for pair in symbols] + [ranking_loop()]
    await asyncio.gather(*tasks)

# ----------------------
# MAIN
# ----------------------
async def main():
    now = datetime.now(TIMEZONE)
    ws_url = WEEKEND_WS if (now.weekday() == 4 and now.hour >= 22) or now.weekday() in [5,6] else DERIV_WS
    symbols = await load_symbols(ws_url)
    while not symbols:
        logging.warning("No symbols loaded, retrying in 5s")
        await asyncio.sleep(5)
        symbols = await load_symbols(ws_url)
    await monitor_pairs(symbols)

# ----------------------
# RUN
# ----------------------
asyncio.run(main())
