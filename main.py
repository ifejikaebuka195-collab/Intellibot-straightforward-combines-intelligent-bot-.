import asyncio
import json
import websockets
from collections import deque
from datetime import datetime
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# 10 FOREX OTC PAIRS
OTC_PAIRS = [
    "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD", "frxUSDCAD",
    "frxUSDCHF", "frxNZDUSD", "frxEURGBP", "frxEURJPY", "frxGBPJPY"
]

# 7 CRYPTO PAIRS
CRYPTO_PAIRS = [
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD",
    "cryXRPUSD", "cryBCHUSD", "cryEOSUSD", "cryTRXUSD"
]

TIMEFRAMES = ["1m", "2m", "3m", "5m", "15m", "30m"]

# =========================
# GLOBAL STORAGE
# =========================
MAX_TICKS = 1000
TICKS = {pair: deque(maxlen=MAX_TICKS) for pair in OTC_PAIRS + CRYPTO_PAIRS}
CONNECTED = False

# Memory for learning from wins/losses
MEMORY_FILE = "learning_memory.json"
MEMORY = {"winning_setups": []}

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
# RECORD WIN / LOSS
# =========================
def record_outcome(trade, outcome):
    """
    Record trade outcome based on WIN/LOSS button
    - WIN: store in memory
    - LOSS: discard if exists
    """
    if outcome == "WIN":
        MEMORY["winning_setups"].append(trade)
    elif outcome == "LOSS":
        MEMORY["winning_setups"] = [
            t for t in MEMORY["winning_setups"]
            if not (
                t["pair"] == trade["pair"] and
                t["direction"] == trade["direction"] and
                t["tf"] == trade["tf"]
            )
        ]
    save_memory()

# =========================
# WEBSOCKET ENGINE
# =========================
async def websocket_manager():
    global CONNECTED
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                CONNECTED = True
                logging.info("🌐 Connected to Deriv WebSocket")

                for pair in OTC_PAIRS + CRYPTO_PAIRS:
                    await ws.send(json.dumps({
                        "ticks": pair,
                        "subscribe": 1
                    }))
                    logging.info(f"✅ Subscribed to {pair}")

                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" in data:
                        symbol = data["tick"]["symbol"]
                        quote = data["tick"]["quote"]
                        TICKS[symbol].append(quote)
                        logging.debug(f"💹 {symbol}: {quote}")

        except Exception as e:
            CONNECTED = False
            logging.error(f"❌ WebSocket disconnected: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

# =========================
# REAL MARKET ACCURACY ENGINE
# =========================
def analyze_market(prices):
    if len(prices) < 30:
        return None

    last = prices[-1]
    momentum = last - prices[-5]
    volatility = max(prices) - min(prices)

    direction = "BUY 🔼" if momentum > 0 else "SELL 🔽"

    recent = prices[-30:]
    wins = sum(
        1 for i in range(1, len(recent))
        if (recent[i] - recent[i-1] > 0 and direction == "BUY 🔼") or
           (recent[i] - recent[i-1] < 0 and direction == "SELL 🔽")
    )
    accuracy = round((wins / len(recent)) * 100)
    risk = round(volatility / last * 100, 2)

    if accuracy < 82:
        return None

    return direction, accuracy, risk

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

    if data == "OTC":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in OTC_PAIRS]
        await query.edit_message_text("OTC Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "CRYPTO":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR_{p}")] for p in CRYPTO_PAIRS]
        await query.edit_message_text("Crypto Market:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("PAIR_"):
        pair = "_".join(data.split("_")[1:])
        context.user_data["pair"] = pair
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"TF_{tf}")] for tf in TIMEFRAMES]
        await query.edit_message_text(f"{pair} selected.\nSelect timeframe:", reply_markup=InlineKeyboardMarkup(keyboard))
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
            direction, accuracy, risk = result
            trade = {"pair": pair, "direction": direction, "accuracy": accuracy, "risk": risk, "tf": tf}
            keyboard = [
                [InlineKeyboardButton("WIN ✅", callback_data="WIN"), InlineKeyboardButton("LOSS ❌", callback_data="LOSS")],
                [InlineKeyboardButton("RESET", callback_data="RESET")]
            ]
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📊 SIGNAL RESULT\n\n"
                    f"Pair: {pair}\n"
                    f"Timeframe: {tf}\n"
                    f"Direction: {direction}\n"
                    f"Accuracy: {accuracy}%\n"
                    f"Risk Level: {risk}%\n\n"
                    f"⚠️ Press WIN if profitable, LOSS if not"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["last_trade"] = trade

        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ No profitable signal found. Try again.")

    elif data == "WIN":
        trade = context.user_data.get("last_trade")
        if trade:
            record_outcome(trade, "WIN")
            await context.bot.send_message(chat_id=chat_id, text="✅ Trade marked as WIN and stored in memory.")
    elif data == "LOSS":
        trade = context.user_data.get("last_trade")
        if trade:
            record_outcome(trade, "LOSS")
            await context.bot.send_message(chat_id=chat_id, text="❌ Trade marked as LOSS and discarded from memory.")
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

    loop = asyncio.get_event_loop()
    loop.create_task(websocket_manager())

    app.run_polling()

if __name__ == "__main__":
    main()
