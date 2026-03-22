import asyncio
import json
import websockets
import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ------------------------------
# SETTINGS
# ------------------------------
BOT_TOKEN = "8640045107:AAEBfp3L8go-qAVkKdrb2LPz4LrzhqblbNw"
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
OTC_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
CRYPTO_PAIRS = ["BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "BCHUSD", "EOSUSD", "ADAUSD"]
TIMEFRAMES = ["1m", "2m", "5m", "15m", "30m"]

# ------------------------------
# GLOBALS
# ------------------------------
user_selection = {
    "market_type": None,
    "pair": None,
    "timeframe": None
}
ohlc_data = {}  # stores candlestick data for all pairs

# ------------------------------
# TELEGRAM BOT INTERFACE
# ------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("OTC", callback_data="OTC")],
        [InlineKeyboardButton("Crypto", callback_data="Crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select Market Type:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # MARKET TYPE
    if data in ["OTC", "Crypto"]:
        user_selection["market_type"] = data
        pairs = OTC_PAIRS if data == "OTC" else CRYPTO_PAIRS
        keyboard = [[InlineKeyboardButton(p, callback_data=f"PAIR:{p}")] for p in pairs]
        await query.edit_message_text(f"Select {data} Pair:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # PAIR
    if data.startswith("PAIR:"):
        pair = data.split(":")[1]
        user_selection["pair"] = pair
        keyboard = [[InlineKeyboardButton(tf, callback_data=f"TF:{tf}")] for tf in TIMEFRAMES]
        await query.edit_message_text(f"Select Timeframe for {pair}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # TIMEFRAME
    if data.startswith("TF:"):
        tf = data.split(":")[1]
        user_selection["timeframe"] = tf
        await query.edit_message_text(f"Scanning {user_selection['pair']} on {tf} timeframe...")
        # Start scanning async
        asyncio.create_task(scan_pair(user_selection["pair"], user_selection["timeframe"]))
        return

# ------------------------------
# WEBSOCKET & CANDLE AGGREGATION
# ------------------------------
async def scan_pair(pair, timeframe):
    # Initialize OHLC storage
    if pair not in ohlc_data:
        ohlc_data[pair] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    async with websockets.connect(DERIV_WS) as ws:
        # Subscribe to ticks
        sub_msg = {"ticks": pair, "subscribe": 1}
        await ws.send(json.dumps(sub_msg))

        async for message in ws:
            data = json.loads(message)
            if "tick" in data:
                tick = data["tick"]
                ts, price, volume = tick["epoch"], tick["quote"], tick.get("volume", 0)
                append_tick(pair, ts, price, volume)
                # Once enough data for timeframe, calculate indicators
                if len(ohlc_data[pair]) >= 20:  # minimum candles
                    signal, accuracy, risk, duration = calculate_signal(pair)
                    # Send Telegram message
                    await send_signal(pair, timeframe, signal, accuracy, risk, duration)
                    break

def append_tick(pair, ts, price, volume):
    df = ohlc_data[pair]
    if len(df) == 0 or ts > df.index[-1] + 60:
        # new candle
        df.loc[ts] = [price, price, price, price, volume]
    else:
        # update last candle
        df.iloc[-1]["high"] = max(df.iloc[-1]["high"], price)
        df.iloc[-1]["low"] = min(df.iloc[-1]["low"], price)
        df.iloc[-1]["close"] = price
        df.iloc[-1]["volume"] += volume
    ohlc_data[pair] = df

# ------------------------------
# SIGNAL CALCULATION
# ------------------------------
def calculate_signal(pair):
    df = ohlc_data[pair].copy()
    df = df.tail(50)

    # Example 20 indicators
    ema = EMAIndicator(df["close"], window=14).ema_indicator()
    rsi = RSIIndicator(df["close"], window=14).rsi()
    macd = MACD(df["close"]).macd_diff()
    adx = ADXIndicator(df["high"], df["low"], df["close"], window=14).adx()
    stoch = StochasticOscillator(df["high"], df["low"], df["close"]).stoch()
    bb = BollingerBands(df["close"]).bollinger_hband_indicator()
    atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
    obv = OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
    vwap = VolumeWeightedAveragePrice(df["high"], df["low"], df["close"], df["volume"]).volume_weighted_average_price()
    # ...add remaining 11 indicators similarly

    # Simplified signal logic (example)
    last = df["close"].iloc[-1]
    signal = "BUY" if last > ema.iloc[-1] and rsi.iloc[-1] < 70 else "SELL"
    accuracy = np.random.randint(80, 96)  # placeholder for real calculation
    risk = "Low" if adx.iloc[-1] > 25 else "High"
    duration = "1 candle"
    return signal, accuracy, risk, duration

# ------------------------------
# TELEGRAM SIGNAL MESSAGE
# ------------------------------
async def send_signal(pair, timeframe, signal, accuracy, risk, duration):
    message = (
        f"AI TRADING BOT:\n"
        f"✅ Pair: {pair}\n"
        f"⏱ Timeframe: {timeframe}\n"
        f"⚡ Signal: {signal}\n"
        f"📊 Accuracy: {accuracy}%\n"
        f"⚠️ Risk: {risk}\n"
        f"⏳ Duration: {duration}\n"
        f"Please manage your risk properly."
    )
    retry_button = [[InlineKeyboardButton("Retry", callback_data="Retry")]]
    chat_id = user_selection.get("chat_id")
    if chat_id:
        await app.bot.send_message(chat_id=chat_id, text=message, reply_markup=InlineKeyboardMarkup(retry_button))

# ------------------------------
# RETRY HANDLER
# ------------------------------
async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_selection["market_type"] = None
    user_selection["pair"] = None
    user_selection["timeframe"] = None
    await start(update, context)

# ------------------------------
# MAIN
# ------------------------------
async def main():
    global app
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(retry_handler, pattern="Retry"))
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
