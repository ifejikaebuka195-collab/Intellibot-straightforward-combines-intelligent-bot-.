from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# ================================
# Telegram Settings
# ================================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"

# ================================
# Pairs
# ================================
OTC_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]
CRYPTO_PAIRS = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "BNBUSD", "SOLUSD"]

TIMEFRAMES = ["1m", "2m", "5m", "15m", "30m"]

# ================================
# Start Command
# ================================
def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("OTC", callback_data="otc")],
        [InlineKeyboardButton("Crypto", callback_data="crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Select OTC or Crypto:", reply_markup=reply_markup)

# ================================
# Button Handler
# ================================
def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data
    
    # -------------------
    # Show OTC or Crypto pairs
    # -------------------
    if data == "otc":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"pair_{pair}")] for pair in OTC_PAIRS]
        query.edit_message_text("Select OTC Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "crypto":
        keyboard = [[InlineKeyboardButton(pair, callback_data=f"pair_{pair}")] for pair in CRYPTO_PAIRS]
        query.edit_message_text("Select Crypto Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    # -------------------
    # Show Timeframes
    # -------------------
    elif data.startswith("pair_"):
        pair = data.split("_")[1]
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"tf_{pair}_{tf}")] for tf in TIMEFRAMES]
        query.edit_message_text(f"Selected Pair: {pair}\nSelect Timeframe:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    # -------------------
    # Final selection
    # -------------------
    elif data.startswith("tf_"):
        _, pair, tf = data.split("_")
        query.edit_message_text(f"Selected Pair: {pair}\nTimeframe: {tf}\n✅ Ready to scan ticks and generate signal...")

# ================================
# Main
# ================================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    updater.dispatcher.add_handler(CommandHandler("start", start))
    updater.dispatcher.add_handler(CallbackQueryHandler(button))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
