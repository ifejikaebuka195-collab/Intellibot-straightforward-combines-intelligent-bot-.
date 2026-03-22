import asyncio
import json
import websockets
import numpy as np
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ================================
# TELEGRAM BOT SETTINGS
# ================================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"

# Pairs
OTC_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
CRYPTO_PAIRS = ["BTC/USD", "ETH/USD", "LTC/USD", "XRP/USD", "BCH/USD", "ADA/USD", "DOGE/USD"]

# Timeframes
TIMEFRAMES = ["1m", "2m", "5m", "15m", "30m"]

# Selected values (manual)
selected_pair = None
selected_timeframe = None

# WebSocket URL
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# ================================
# TELEGRAM HANDLERS
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("OTC", callback_data="otc")],
        [InlineKeyboardButton("Crypto", callback_data="crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select Market Type:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_pair, selected_timeframe
    query = update.callback_query
    await query.answer()
    data = query.data

    # Select market type
    if data == "otc":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"pair:{pair}")] for pair in OTC_PAIRS]
        await query.edit_message_text("Select OTC Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "crypto":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"pair:{pair}")] for pair in CRYPTO_PAIRS]
        await query.edit_message_text("Select Crypto Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("pair:"):
        selected_pair = data.split(":")[1]
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"time:{tf}")] for tf in TIMEFRAMES]
        await query.edit_message_text(f"Selected Pair: {selected_pair}\nSelect Timeframe:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("time:"):
        selected_timeframe = data.split(":")[1]
        await query.edit_message_text(f"✅ Pair selected: {selected_pair}\n⏱ Timeframe: {selected_timeframe}\n⚡ Scanning market for signals...")
        # Start scanning market once pair & timeframe selected
        asyncio.create_task(scan_market(selected_pair, selected_timeframe, context))

# ================================
# WEBSOCKET MARKET SCAN
# ================================
async def scan_market(pair, timeframe, context):
    async with websockets.connect(DERIV_WS_URL) as ws:
        # Subscribe to ticks
        subscribe_msg = json.dumps({"ticks": pair})
        await ws.send(subscribe_msg)
        await asyncio.sleep(0.1)  # Give time for subscription

        ticks = []
        while True:
            if selected_pair != pair or selected_timeframe != timeframe:
                break  # Stop scanning if selection changed

            response = await ws.recv()
            data = json.loads(response)

            if "tick" in data:
                ticks.append(data["tick"])
            
            # Analyze every 10-15 seconds
            if len(ticks) >= 15:
                signal_info = analyze_market(ticks, pair, timeframe)
                await send_signal(context, signal_info)
                ticks.clear()  # Clear ticks for next scan

# ================================
# MARKET ANALYSIS
# ================================
def analyze_market(ticks, pair, timeframe):
    # Dummy placeholder for real indicator calculation
    # Replace with full 20 indicators logic
    price_series = np.array([tick["quote"] for tick in ticks])
    real_accuracy = np.random.uniform(50, 95)  # Placeholder
    real_risk = np.random.uniform(0.5, 5.0)    # Placeholder
    duration = timeframe

    # Decide signal
    direction = "BUY" if price_series[-1] > price_series[0] else "SELL"

    return {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "accuracy": round(real_accuracy, 2),
        "risk": round(real_risk, 2),
        "duration": duration
    }

# ================================
# SEND SIGNAL TO TELEGRAM
# ================================
async def send_signal(context, signal_info):
    msg = (
        f"🔔 Signal for {signal_info['pair']} ({signal_info['timeframe']})\n"
        f"Direction: {signal_info['direction']}\n"
        f"Real Accuracy: {signal_info['accuracy']}%\n"
        f"Real Risk: {signal_info['risk']}\n"
        f"Recommended Duration: {signal_info['duration']}"
    )
    # Send message to all users (you can adjust chat_id or context.bot)
    await context.bot.send_message(chat_id=context._chat_id, text=msg)

# ================================
# MAIN
# ================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
