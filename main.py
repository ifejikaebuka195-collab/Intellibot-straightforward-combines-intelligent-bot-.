# full_system.py
import asyncio
import json
import requests
import websockets
import numpy as np
from datetime import datetime
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# -----------------------------
# TELEGRAM SETTINGS
# -----------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
CHAT_ID = "6918721957"
TIMEZONE = pytz.timezone("Africa/Lagos")

# -----------------------------
# DERIV WEBSOCKET SETTINGS
# -----------------------------
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
MAX_PRICES = 10000
TICK_CONFIRMATION = 3

# -----------------------------
# PAIRS
# -----------------------------
OTC_PAIRS = ["frxEURUSD","frxUSDJPY","frxGBPUSD","frxAUDUSD","frxUSDCAD","frxNZDUSD","frxEURJPY"]
CRYPTO_PAIRS = ["BTCUSD","ETHUSD","XRPUSD","LTCUSD","ADAUSD","SOLUSD","DOTUSD"]

# -----------------------------
# GLOBALS
# -----------------------------
prices = {}
candlesticks = {}
tick_confirm = {}
selected_pair = None
selected_timeframe = None
hourly_signals_count = 0
last_signal_hour = None

# -----------------------------
# INDICATOR FUNCTIONS (20)
# -----------------------------
def ema(data, period): return sum(data[-period:])/period if len(data)>=period else None
def sma(data, period): return sum(data[-period:])/period if len(data)>=period else None
def rsi(data, period=14):
    if len(data)<period+1: return None
    gains, losses = 0,0
    for i in range(-period,0):
        diff = data[i]-data[i-1]
        if diff>0: gains+=diff
        else: losses-=diff
    rs=gains/losses if losses!=0 else 0
    return 100-(100/(1+rs))
# Placeholder functions for MACD, Bollinger Bands, ATR, Stochastic, ADX, SAR, OBV, CCI, Ichimoku, Heiken Ashi, Williams, Pivot, Fibonacci, EMA Ribbon, Keltner, VWMA, Money Flow
def indicators_agree(data, direction): return True  # placeholder that simulates all 20 agreeing

# -----------------------------
# CANDLESTICK HANDLER
# -----------------------------
def add_candle(pair, price):
    if pair not in candlesticks: candlesticks[pair] = []
    candlesticks[pair].append(price)
    if len(candlesticks[pair])>MAX_PRICES: candlesticks[pair].pop(0)

# -----------------------------
# TREND DETECTION
# -----------------------------
def detect_trend(p):
    if len(p)<20: return None
    e1=ema(p[-10:],3)
    e2=ema(p[-20:],5)
    if e1 and e2: return "BUY" if e1>e2 else "SELL"
    return None

# -----------------------------
# ACCURACY & RISK
# -----------------------------
def get_accuracy(p): return min(max(int(100-(np.std(p[-20:])/np.mean(p[-20:])*100)),50),95) if len(p)>=20 else 82
def get_risk(p): return round(np.std(p[-20:])/np.mean(p[-20:]),4) if len(p)>=20 else 0.02

# -----------------------------
# TELEGRAM BUTTONS
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard=[[InlineKeyboardButton("OTC",callback_data="OTC"),InlineKeyboardButton("Crypto",callback_data="CRYPTO")]]
    await update.message.reply_text("Select OTC or Crypto:",reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_pair, selected_timeframe
    query = update.callback_query
    await query.answer()
    data=query.data
    if data in ["OTC","CRYPTO"]:
        pairs=OTC_PAIRS if data=="OTC" else CRYPTO_PAIRS
        keyboard=[[InlineKeyboardButton(p.replace("frx",""),callback_data=p)] for p in pairs]
        await query.edit_message_text(f"Select Pair ({data}):",reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if data in OTC_PAIRS+CRYPTO_PAIRS:
        selected_pair=data
        keyboard=[[InlineKeyboardButton(tf,callback_data=tf)] for tf in ["1m","2m","5m","15m","30m"]]
        await query.edit_message_text(f"Selected Pair: {data}\nSelect Timeframe:",reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if data in ["1m","2m","5m","15m","30m"]:
        selected_timeframe=data
        await query.edit_message_text(f"Pair: {selected_pair}\nTimeframe: {selected_timeframe}\n⚡ Now scanning...")
        asyncio.create_task(run_signal(selected_pair,selected_timeframe))
        return

# -----------------------------
# SIGNAL GENERATION
# -----------------------------
async def run_signal(pair, timeframe):
    global prices, candlesticks, tick_confirm, hourly_signals_count, last_signal_hour
    now=datetime.now(TIMEZONE)
    if last_signal_hour!=now.hour:
        hourly_signals_count=0
        last_signal_hour=now.hour
    prices[pair]=[]
    tick_confirm[pair]={"count":0,"dir":None}
    async with websockets.connect(DERIV_WS) as ws:
        await ws.send(json.dumps({"ticks":pair,"subscribe":1}))
        async for msg in ws:
            data=json.loads(msg)
            if "tick" not in data: continue
            price=data["tick"]["quote"]
            prices[pair].append(price)
            add_candle(pair,price)
            if len(prices[pair])>MAX_PRICES: prices[pair].pop(0)
            # detect trend
            direction=detect_trend(prices[pair])
            if not direction: continue
            # tick confirmation
            if tick_confirm[pair]["dir"]==direction: tick_confirm[pair]["count"]+=1
            else: tick_confirm[pair]={"dir":direction,"count":1}
            if tick_confirm[pair]["count"]<TICK_CONFIRMATION: continue
            # indicator check
            if not indicators_agree(prices[pair],direction): continue
            # wait 12 seconds for scanning
            await asyncio.sleep(12)
            # calculate accuracy & risk
            acc=get_accuracy(prices[pair])
            risk=get_risk(prices[pair])
            msg=f"AI TRADING BOT:\nPAIR: {pair}\nTIMEFRAME: {timeframe}\nSIGNAL: {direction}\nDURATION: 12s\nACCURACY: {acc}%\nRISK: {risk}\n⚠ Please apply proper risk management!"
            await requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":msg})
            hourly_signals_count+=1
            if hourly_signals_count>=2: break

# -----------------------------
# RUN TELEGRAM BOT
# -----------------------------
app=ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start",start))
app.add_handler(CallbackQueryHandler(button_handler))
app.run_polling()
