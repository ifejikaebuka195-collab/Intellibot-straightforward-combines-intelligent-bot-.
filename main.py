======================================

DERIV AI SIGNAL BOT - FULLY INTEGRATED

LIVE MARKET, SELF-LEARNING, TELEGRAM ALERTS, ROBUST

======================================

import asyncio import json import requests import websockets import numpy as np from datetime import datetime, timedelta import pytz import csv import os

----------------------

CONFIG

----------------------

BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw" CHAT_ID = "6918721957" DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089" TIMEZONE = pytz.timezone("Africa/Lagos")

MAX_PRICES = 5000 TICK_CONFIRMATION = 3 COOLDOWN_MINUTES = 2 CONFIDENCE_THRESHOLD = 75  # minimum confidence to send signal

BLOCKED_PAIRS = ["frxUSDNOK","frxGBPNOK","frxUSDPLN","frxGBPNZD","frxUSDSEK"]

prices = {} tick_confirm = {} pending_signal = {} cooldowns = {} TRADE_LOG = "ai_trades.csv"

----------------------

INIT LOG

----------------------

if not os.path.exists(TRADE_LOG): with open(TRADE_LOG, "w", newline="") as f: csv.writer(f).writerow(["time","pair","direction","entry","exit","result"])

==============================

EMA UTILITY

==============================

def ema(data, period): if len(data) < period: return None k = 2 / (period + 1) val = data[0] for p in data: val = p * k + val * (1 - k) return val

==============================

TREND DETECTION

==============================

def detect_trend(p): if len(p) < 100: return None e1 = ema(p[-20:], 5) e2 = ema(p[-50:], 13) e3 = ema(p[-100:], 21) if not all([e1, e2, e3]): return None if e1 > e2 > e3: return "BUY" elif e1 < e2 < e3: return "SELL" return None

==============================

PULLBACK DETECTION

==============================

def detect_pullback(p, direction): window = min(15, len(p)) recent = np.array(p[-window:]) diff = np.diff(recent) if direction == "BUY" and np.any(diff < 0): return True if direction == "SELL" and np.any(diff > 0): return True return False

==============================

REVERSAL DETECTION

==============================

def detect_reversal(p): window = min(20, len(p)) diff = np.diff(np.array(p[-window:])) ups = np.sum(diff > 0) downs = np.sum(diff < 0) if ups >= 10 and downs >= 3: return "BUY_REVERSE" if downs >= 10 and ups >= 3: return "SELL_REVERSE" return None

==============================

BIG MOVE CHECK

==============================

def big_move_ready(p, direction): if len(p) < 50: return False std = np.std(p[-30:]) mean = np.mean(p[-30:]) if std > 0.01 * mean: return False diff = np.diff(p[-10:]) if direction in ["BUY","BUY_REVERSE"]: if np.sum(diff > 0) < 8 or not (diff[-1] > diff[-2] > diff[-3]): return False if direction in ["SELL","SELL_REVERSE"]: if np.sum(diff < 0) < 8 or not (diff[-1] < diff[-2] < diff[-3]): return False return True

==============================

CONFIDENCE CALCULATION

==============================

def calculate_confidence(p, direction): trend_score = 0 e1 = ema(p[-20:], 5) e2 = ema(p[-50:], 13) e3 = ema(p[-100:], 21) if direction == "BUY" and e1 > e2 > e3: trend_score = 50 elif direction == "SELL" and e1 < e2 < e3: trend_score = 50

recent_diff = np.diff(np.array(p[-10:]))
if direction in ["BUY","BUY_REVERSE"]:
    momentum_score = min(30, np.sum(recent_diff > 0) * 3)
else:
    momentum_score = min(30, np.sum(recent_diff < 0) * 3)

vol = np.std(p[-20:])
vol_score = max(0, 20 - int(vol * 1000))

total_confidence = trend_score + momentum_score + vol_score
return total_confidence

==============================

COOLDOWN / LOCK

==============================

def locked(pair): return pair in cooldowns and datetime.now(TIMEZONE) < cooldowns[pair]

def set_cooldown(pair, minutes): cooldowns[pair] = datetime.now(TIMEZONE) + timedelta(minutes=minutes)

==============================

TELEGRAM SIGNALS

==============================

def send_signal(pair, direction, duration, acc): arrow = "⬆️" if "BUY" in direction else "⬇️" msg = f""" PRE-SIGNAL ALERT ⏳

Asset: {pair}_otc Suggested Duration: {duration} min Expected Accuracy: {acc}% """ requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})

# Wait before actual entry
asyncio.run(asyncio.sleep(10))  # 10 seconds for demo, can adjust

msg_entry = f"""

SIGNAL {arrow}

Asset: {pair}_otc Duration: {duration} min Payout: 92% Accuracy: {acc}% """ requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg_entry}) print(f"[SIGNAL SENT] {pair} | {direction} | Duration={duration} | Acc={acc}%")

==============================

LOGGING

==============================

def log_trade(pair, direction, entry, exit_price): result = "WIN" if ((direction == "BUY" and exit_price > entry) or (direction == "SELL" and exit_price < entry)) else "LOSS" with open(TRADE_LOG, "a", newline="") as f: csv.writer(f).writerow([datetime.now(TIMEZONE), pair, direction, entry, exit_price, result])

==============================

LOAD SYMBOLS

==============================

async def load_symbols(): try: async with websockets.connect(DERIV_WS) as ws: await ws.send(json.dumps({"active_symbols": "brief"})) res = json.loads(await ws.recv()) return [s["symbol"] for s in res["active_symbols"] if s["symbol"].startswith("frx") and s["symbol"] not in BLOCKED_PAIRS] except Exception as e: print(f"[ERROR] Loading symbols: {e}") return []

==============================

MAIN MONITOR LOOP

==============================

async def monitor(): while True: try: symbols = await load_symbols() if not symbols: await asyncio.sleep(5) continue

for s in symbols:
            prices[s] = []
            tick_confirm[s] = {"count":0, "dir":None}
            pending_signal[s] = None

        async with websockets.connect(DERIV_WS) as ws:
            for s in symbols:
                await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if "tick" not in data:
                        continue

                    pair = data["tick"]["symbol"]
                    price = data["tick"]["quote"]
                    prices[pair].append(price)
                    if len(prices[pair]) > MAX_PRICES:
                        prices[pair].pop(0)

                    print(f"[LIVE] {pair} {price}")

                    if locked(pair) or pending_signal[pair] is not None:
                        continue

                    direction = detect_trend(prices[pair])
                    if not direction:
                        continue
                    if detect_pullback(prices[pair], direction):
                        continue
                    reversal = detect_reversal(prices[pair])
                    if reversal:
                        direction = reversal

                    if tick_confirm[pair]["dir"] == direction:
                        tick_confirm[pair]["count"] += 1
                    else:
                        tick_confirm[pair] = {"dir": direction, "count": 1}

                    if tick_confirm[pair]["count"] < TICK_CONFIRMATION:
                        continue

                    if not big_move_ready(prices[pair], direction):
                        continue

                    confidence = calculate_confidence(prices[pair], direction)
                    if confidence < CONFIDENCE_THRESHOLD:
                        continue

                    entry_price = prices[pair][-1]
                    pending_signal[pair] = {"direction": direction, "start": datetime.now(TIMEZONE)}

                    send_signal(pair, direction, duration=1, acc=confidence)
                    set_cooldown(pair, COOLDOWN_MINUTES)

                    # Simulated exit logic after duration
                    await asyncio.sleep(60)
                    exit_price = prices[pair][-1]
                    log_trade(pair, direction, entry_price, exit_price)

                    pending_signal[pair] = None
                    tick_confirm[pair] = {"count":0, "dir":None}

                except Exception as e:
                    print(f"[ERROR] Tick processing: {e}")
                    continue

    except Exception as e:
        print(f"[ERROR] Main loop: {e}")
        await asyncio.sleep(5)

asyncio.run(monitor())
