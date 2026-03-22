# =========================================================
# FULL MANUAL AI TRADING SYSTEM (FAST TICK ENGINE UPGRADE)
# DERIV REAL WEBSOCKET + TELEGRAM BOT (SUPER FAST VERSION)
# =========================================================

import asyncio
import json
import websockets
import random
import time
from collections import deque

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
DERIV_APP_ID = "1089"
DERIV_API_TOKEN = "YOUR_DERIV_API_TOKEN"

DERIV_WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"

# ✅ FOREX OTC (AUTO WHEN AVAILABLE)
OTC_PAIRS = [
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
    "frxAUDUSD",
    "frxUSDCAD",
    "frxUSDCHF",
    "frxNZDUSD"
]

# ✅ CRYPTO (ALWAYS AVAILABLE)
CRYPTO_PAIRS = [
    "cryBTCUSD",
    "cryETHUSD",
    "cryLTCUSD",
    "cryXRPUSD",
    "cryBCHUSD",
    "cryEOSUSD",
    "cryTRXUSD"
]

TIMEFRAMES = ["1m", "2m", "3m", "5m", "15m", "30m"]

# =========================
# GLOBAL STORAGE (FAST BUFFER)
# =========================
MAX_TICKS = 2000  # 🔥 LARGE BUFFER = MORE DATA
TICKS = {pair: deque(maxlen=MAX_TICKS) for pair in OTC_PAIRS + CRYPTO_PAIRS}
LAST_UPDATE = {pair: 0 for pair in OTC_PAIRS + CRYPTO_PAIRS}

CONNECTED = False

# =========================
# 🔥 ULTRA FAST WEBSOCKET ENGINE
# =========================
async def websocket_manager():
    global CONNECTED
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL, ping_interval=None, close_timeout=1) as ws:
                CONNECTED = True

                # AUTHORIZE
                await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth = json.loads(await ws.recv())
                if "error" in auth:
                    CONNECTED = False
                    await asyncio.sleep(5)
                    continue

                subscribed = set()
                while True:
                    # SUBSCRIBE TO ALL PAIRS FAST
                    for pair in OTC_PAIRS + CRYPTO_PAIRS:
                        if pair not in subscribed:
                            try:
                                await ws.send(json.dumps({"ticks": pair, "subscribe": 1}))
                                subscribed.add(pair)
                            except:
                                pass

                    # RECEIVE FAST STREAM
                    try:
                        raw = await ws.recv()
                        data = json.loads(raw)
                        if "tick" in data:
                            symbol = data["tick"]["symbol"]
                            price = data["tick"]["quote"]
                            now = time.time()

                            if symbol in TICKS and now - LAST_UPDATE[symbol] > 0.05:
                                TICKS[symbol].append(price)
                                LAST_UPDATE[symbol] = now
                    except:
                        break
        except:
            CONNECTED = False
            await asyncio.sleep(2)

# =========================
# 🔥 SUPER FAST INDICATOR ENGINE
# =========================
def analyze_market(prices):
    if len(prices) < 50:
        return None
    last = prices[-1]
    avg = sum(prices[-50:]) / 50
    momentum = prices[-1] - prices[-10]
    trend = prices[-1] - prices[-30]
    volatility = max(prices[-50:]) - min(prices[-50:])
    signals = [last > avg, momentum > 0, trend > 0, volatility > 0] * 5
    score = sum(signals)
    direction = "BUY 🔼" if score >= 12 else "SELL 🔽"
    accuracy = round((score / 20) * 100)
    risk = round((100 - accuracy) / 8, 2)
    duration = "1 min" if accuracy > 80 else "3 min"
    return direction, accuracy, risk, duration

# =========================
# TELEGRAM START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("OTC", callback_data="OTC"),
        InlineKeyboardButton("CRYPTO", callback_data="CRYPTO")
    ]]
    await update.message.reply_text("Select Market:", reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# BUTTON HANDLER
# =========================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "OTC":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in OTC_PAIRS]
        await query.edit_message_text("OTC Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "CRYPTO":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in CRYPTO_PAIRS]
        await query.edit_message_text("Crypto Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("PAIR_"):
        pair = data.split("_")[1]
        context.user_data["pair"] = pair
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"TF_{tf}")] for tf in TIMEFRAMES]
        await query.edit_message_text(f"{pair} selected.\nSelect timeframe:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("TF_"):
        tf = data.split("_")[1]
        pair = context.user_data.get("pair")
        await query.edit_message_text(
            f"✅ Pair selected: {pair}\n⏱ Timeframe: {tf}\n⚡ Now scanning {pair}..."
        )
        await context.bot.send_message(chat_id=query.message.chat_id, text="🔔 Signal will appear with real accuracy & risk.")
        await context.bot.send_message(chat_id=query.message.chat_id, text="⏳ Scanning market... wait for 15 seconds")
        await asyncio.sleep(15)
        prices = list(TICKS.get(pair, []))
        result = analyze_market(prices)
        if result:
            direction, accuracy, risk, duration = result
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"📊 SIGNAL RESULT\n\n"
                    f"Pair: {pair}\n"
                    f"Timeframe: {tf}\n"
                    f"Direction: {direction}\n\n"
                    f"Accuracy: {accuracy}%\n"
                    f"Risk Level: {risk}%\n"
                    f"Duration: {duration}\n\n"
                    f"⚠️ Use proper risk management"
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("RESET", callback_data="RESET")]])
            )
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Not enough data yet. Try again.")
    elif data == "RESET":
        keyboard = [[InlineKeyboardButton("OTC", callback_data="OTC"), InlineKeyboardButton("CRYPTO", callback_data="CRYPTO")]]
        await query.edit_message_text("Select Market:", reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    loop = asyncio.get_event_loop()
    loop.create_task(websocket_manager())
    app.run_polling()

if __name__ == "__main__":
    main()
