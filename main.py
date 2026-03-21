import os
import json
import time
import websocket
import requests
from dotenv import load_dotenv

# Load your .env variables
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# List of 15 crypto pairs you want to track
CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "BNB/USD", "ADA/USD", "SOL/USD",
    "XRP/USD", "DOGE/USD", "LTC/USD", "DOT/USD", "MATIC/USD",
    "BCH/USD", "XLM/USD", "TRX/USD", "ETC/USD", "FIL/USD"
]

def send_signal(message):
    """Send a message to your Telegram channel."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=5
        )
    except Exception as e:
        print("Telegram error:", e)

def on_message(ws, message):
    """Called on every tick from the WebSocket."""
    try:
        data = json.loads(message)
        # Only send signals for the crypto pairs we care about
        if "pair" in data and data["pair"] in CRYPTO_PAIRS:
            send_signal(f"Tick for {data['pair']}: {data}")
    except Exception as e:
        print("Error parsing tick:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed, reconnecting in 5 seconds...")
    time.sleep(5)
    connect_ws()  # Auto-reconnect

def on_open(ws):
    print("WebSocket connected. Listening for crypto ticks...")

def connect_ws():
    # Public CoinCap WebSocket
    ws = websocket.WebSocketApp(
        "wss://ws.coincap.io/prices?assets=" + ",".join([p.split("/")[0].lower() for p in CRYPTO_PAIRS]),
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    # Run forever
    ws.run_forever(ping_interval=30, ping_timeout=10)

if __name__ == "__main__":
    connect_ws()
