import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import Conflict

# =========================
# CONFIG
# =========================
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"

# =========================
# START COMMAND
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot connected and running! Fix applied for conflicts.")

# =========================
# MAIN FUNCTION
# =========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    async def run_app():
        try:
            # This handles conflicts without crashing
            await app.run_polling()
        except Conflict as e:
            print(f"⚠️ Telegram Conflict detected: {e}")
            print("Make sure only one instance of the bot is running!")

    asyncio.run(run_app())

if __name__ == "__main__":
    print("🚀 Starting small Telegram bot test...")
    main()
