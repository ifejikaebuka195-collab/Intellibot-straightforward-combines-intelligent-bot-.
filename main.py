# ===============================
# Minimal Telegram Test Bot
# ===============================

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# -------------------------------
# CONFIG
# -------------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"

# -------------------------------
# START COMMAND
# -------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Test Button 1", callback_data="BTN1")],
        [InlineKeyboardButton("Test Button 2", callback_data="BTN2")]
    ]
    await update.message.reply_text(
        "Welcome! Press a button to test:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# -------------------------------
# BUTTON HANDLER
# -------------------------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "BTN1":
        await query.edit_message_text("✅ You pressed Test Button 1!")
    elif data == "BTN2":
        await query.edit_message_text("✅ You pressed Test Button 2!")

# -------------------------------
# MAIN
# -------------------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))

    # Run bot
    app.run_polling()

if __name__ == "__main__":
    main()
