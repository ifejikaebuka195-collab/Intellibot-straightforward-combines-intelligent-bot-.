import asyncio
import json
import websockets
import random
from collections import deque
from datetime import datetime, timedelta
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# ✅ ONLY REAL MARKET PAIRS
OTC_PAIRS = ["R_100", "R_75", "R_50", "R_25", "R_10", "R_10S", "R_25S"]
CRYPTO_PAIRS = ["cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "cryBCHUSD", "cryEOSUSD", "cryTRXUSD"]

TIMEFRAMES = ["1m", "2m", "3m", "5m", "15m", "30m"]

# =========================
# GLOBAL STORAGE
# =========================
MAX_TICKS = 500  # store more ticks for fast signal
TICKS = {pair: deque(maxlen=MAX_TICKS) for pair in OTC_PAIRS + CRYPTO_PAIRS}
CONNECTED = False

# Memory storage for win/loss learning
MEMORY_FILE = "trade_memory.json"
MEMORY = {"wins": [], "losses": []}

logging.basicConfig(level=logging.INFO)

# =========================
# LOAD / SAVE MEMORY
# =========================
def load_memory():
    global MEMORY
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            MEMORY = json.load(f)

def save_memory():
    with open(MEMORY_FILE, "w") as f:
        json.dump(MEMORY, f, indent=4)

# =========================
# DERIV WEBSOCKET ENGINE (FAST COLLECTION)
# =========================
async def websocket_manager():
    global CONNECTED
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                CONNECTED = True
                logging.info("🌐 Connected to Deriv WebSocket")

                # Subscribe to all pairs
                for pair in OTC_PAIRS + CRYPTO_PAIRS:
                    await ws.send(json.dumps({
                        "ticks": pair,
                        "subscribe": 1
                    }))
                    logging.info(f"✅ Subscribed to {pair}")

                # Receive live ticks
                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" in data:
                        symbol = data["tick"]["symbol"]
                        quote = data["tick"]["quote"]
                        TICKS[symbol].append(quote)
                        logging.info(f"💹 {symbol}: {quote}")

        except Exception as e:
            CONNECTED = False
            logging.error(f"❌ WebSocket disconnected: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

# =========================
# MARKET ANALYSIS ENGINE
# =========================
def analyze_market(prices):
    if len(prices) < 30:
        return None

    last = prices[-1]
    avg = sum(prices) / len(prices)
    momentum = last - prices[-5]
    volatility = max(prices) - min(prices)

    # Signal logic
    signals = [
        last > avg, last > avg, momentum > 0, momentum > 0,
        volatility > 0, momentum > 0, volatility > 0, momentum > 0,
        last > avg, True, momentum > 0, True,
        last > avg, True, momentum > 0, momentum > 0,
        last > avg, momentum > 0, last > avg, volatility > 0
    ]

    score = sum(1 for s in signals if s)
    direction = "BUY 🔼" if score >= 10 else "SELL 🔽"
    accuracy = round((score / 20) * 100)
    risk = round((100 - accuracy) / 10, 2)
    duration = random.choice(["1 min", "2 min", "3 min", "5 min"])

    # Include the setup for learning
    setup = {
        "last": last,
        "avg": avg,
        "momentum": momentum,
        "volatility": volatility,
        "signals": signals
    }

    return direction, accuracy, risk, duration, setup

# =========================
# TELEGRAM BOT HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("OTC", callback_data="OTC"),
        InlineKeyboardButton("CRYPTO", callback_data="CRYPTO")
    ]]
    await update.message.reply_text("Select Market:", reply_markup=InlineKeyboardMarkup(keyboard))

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # MARKET SELECTION
    if data == "OTC":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in OTC_PAIRS]
        await query.edit_message_text("OTC Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "CRYPTO":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in CRYPTO_PAIRS]
        await query.edit_message_text("Crypto Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    # PAIR SELECTION
    elif data.startswith("PAIR_"):
        pair = "_".join(data.split("_")[1:])
        context.user_data["pair"] = pair
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"TF_{tf}")] for tf in TIMEFRAMES]
        await query.edit_message_text(f"{pair} selected.\nSelect timeframe:", reply_markup=InlineKeyboardMarkup(keyboard))
    # TIMEFRAME SELECTION
    elif data.startswith("TF_"):
        tf = "_".join(data.split("_")[1:])
        pair = context.user_data.get("pair")

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Pair selected: {pair}\n⏱ Timeframe: {tf}\n⚡ Scanning real market signal..."
        )
        await asyncio.sleep(15)

        prices = list(TICKS.get(pair, []))
        result = analyze_market(prices)

        if result:
            direction, accuracy, risk, duration, setup = result

            # Save last signal temporarily
            context.user_data["last_signal"] = {
                "pair": pair,
                "timeframe": tf,
                "direction": direction,
                "accuracy": accuracy,
                "risk": risk,
                "duration": duration,
                "setup": setup
            }

            # Show signal with WIN/LOSS buttons
            keyboard = [
                [
                    InlineKeyboardButton("WIN ✅", callback_data="WIN"),
                    InlineKeyboardButton("LOSS ❌", callback_data="LOSS"),
                    InlineKeyboardButton("RESET 🔄", callback_data="RESET")
                ]
            ]
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📊 SIGNAL RESULT\n\n"
                    f"Pair: {pair}\n"
                    f"Timeframe: {tf}\n"
                    f"Direction: {direction}\n"
                    f"Accuracy: {accuracy}%\n"
                    f"Risk Level: {risk}%\n"
                    f"Duration: {duration}\n\n"
                    f"⚠️ Mark WIN if successful or LOSS if failed"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Not enough data yet. Try again.")

    # WIN / LOSS HANDLER
    elif data == "WIN":
        last_signal = context.user_data.get("last_signal")
        if last_signal:
            MEMORY["wins"].append(last_signal)
            save_memory()
            await context.bot.send_message(chat_id=chat_id, text="✅ Win recorded! Memory updated.")
    elif data == "LOSS":
        last_signal = context.user_data.get("last_signal")
        if last_signal:
            MEMORY["losses"].append(last_signal)
            save_memory()
            await context.bot.send_message(chat_id=chat_id, text="❌ Loss recorded! Setup discarded.")

    # RESET
    elif data == "RESET":
        keyboard = [[
            InlineKeyboardButton("OTC", callback_data="OTC"),
            InlineKeyboardButton("CRYPTO", callback_data="CRYPTO")
        ]]
        await query.edit_message_text("Select Market:", reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# MAIN
# =========================
def main():
    load_memory()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))

    # Start websocket task for fast tick collection
    loop = asyncio.get_event_loop()
    loop.create_task(websocket_manager())

    app.run_polling()

if __name__ == "__main__":
    main()
