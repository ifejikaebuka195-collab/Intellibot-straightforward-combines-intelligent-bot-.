from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ===============================
# TELEGRAM BOT SETTINGS
# ===============================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"

# ===============================
# CURRENCY PAIRS
# ===============================
OTC_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
CRYPTO_PAIRS = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "BNBUSD", "SOLUSD"]

TIME_FRAMES = ["1m", "2m", "5m", "15m", "30m"]

# ===============================
# START COMMAND
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("OTC", callback_data="choose_otc")],
        [InlineKeyboardButton("Crypto", callback_data="choose_crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select asset type:", reply_markup=reply_markup)

# ===============================
# CALLBACK HANDLER
# ===============================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "choose_otc":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"pair_{p}")] for p in OTC_PAIRS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select OTC pair:", reply_markup=reply_markup)
    elif query.data == "choose_crypto":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"pair_{p}")] for p in CRYPTO_PAIRS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select Crypto pair:", reply_markup=reply_markup)
    elif query.data.startswith("pair_"):
        pair = query.data.replace("pair_", "")
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"tf_{tf}_{pair}")] for tf in TIME_FRAMES]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Select time frame for {pair}:", reply_markup=reply_markup)
    elif query.data.startswith("tf_"):
        parts = query.data.split("_")
        tf, pair = parts[1], parts[2]
        await query.edit_message_text(f"✅ You selected {pair} with time frame {tf}.\nScanning and generating signals now...")
        # Here you can call your signal generation logic for this pair and timeframe

# ===============================
# MAIN FUNCTION
# ===============================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()
