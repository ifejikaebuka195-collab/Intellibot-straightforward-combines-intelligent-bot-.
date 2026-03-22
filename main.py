import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# ================================
# TELEGRAM BOT SETTINGS
# ================================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"  # Replace with your bot token

# ================================
# Pairs
# ================================
OTC_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
CRYPTO_PAIRS = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "BCHUSD", "ADAUSD", "BNBUSD"]

# ================================
# COMMAND /start
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("OTC", callback_data="OTC")],
        [InlineKeyboardButton("Crypto", callback_data="Crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select category:", reply_markup=reply_markup)

# ================================
# CALLBACK QUERY
# ================================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # OTC / Crypto selection
    if query.data == "OTC":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"OTC_{pair}")] for pair in OTC_PAIRS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select OTC pair:", reply_markup=reply_markup)
        return
    elif query.data == "Crypto":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"CRYPTO_{pair}")] for pair in CRYPTO_PAIRS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select Crypto pair:", reply_markup=reply_markup)
        return

    # Pair selection
    if query.data.startswith("OTC_") or query.data.startswith("CRYPTO_"):
        pair = query.data.split("_")[1]
        keyboard = [
            [InlineKeyboardButton("1 min", callback_data=f"TF_1_{pair}")],
            [InlineKeyboardButton("2 min", callback_data=f"TF_2_{pair}")],
            [InlineKeyboardButton("5 min", callback_data=f"TF_5_{pair}")],
            [InlineKeyboardButton("15 min", callback_data=f"TF_15_{pair}")],
            [InlineKeyboardButton("30 min", callback_data=f"TF_30_{pair}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Select timeframe for {pair}:", reply_markup=reply_markup)
        return

    # Timeframe selection
    if query.data.startswith("TF_"):
        parts = query.data.split("_")
        tf = parts[1]
        pair = parts[2]
        await query.edit_message_text(
            f"✅ Pair selected: {pair}\n"
            f"⏱ Timeframe: {tf} min\n"
            f"⚡ Now scanning {pair} and preparing signal..."
        )
        # Here you can trigger your WebSocket scan and signal generation
        # For demo purposes, we just send a placeholder
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🔔 Signal for {pair} ({tf} min) will appear here with real accuracy & risk."
        )

# ================================
# MAIN FUNCTION
# ================================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))

    print("Bot is running...")
    app.run_polling()
