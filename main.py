import os
import json
import time
import websocket
import requests
from dotenv import load_dotenv

# Load env
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Binance stream (ALL pairs)
STREAMS = [
    "btcusdt@trade",
    "ethusdt@trade",
    "bnbusdt@trade",
    "solusdt@trade",
    "adausdt@trade",
    "xrpusdt@trade",
    "dogeusdt@trade",
    "dotusdt@trade",
    "ltcusdt@trade",
    "linkusdt@trade",
    "maticusdt@trade",
    "filusdt@trade",
    "bchusdt@trade",
    "trxusdt@trade",
    "xlmusdt@trade"
]

WS_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(STREAMS)


def send_signal(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": message
        }, timeout=5)
    except Exception as e:
        print("Telegram error:", e)


def on_message(ws, message):
    try:
        data = json.loads(message)

        if "data" in data:
            tick = data["data"]
            symbol = tick.get("s")
            price = tick.get("p")

            msg = f"{symbol} → {price}"
            print(msg)

            # SEND EVERY TICK
            send_signal(msg)

    except Exception as e:
        print("Parse error:", e)


def on_error(ws, error):
    print("WebSocket error:", error)


def on_close(ws, close_status_code, close_msg):
    print("Disconnected. Reconnecting in 5 seconds...")
    time.sleep(5)
    connect()


def on_open(ws):
    print("Connected to Binance. Streaming ticks...")


def connect():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()


if __name__ == "__main__":
    connect()
