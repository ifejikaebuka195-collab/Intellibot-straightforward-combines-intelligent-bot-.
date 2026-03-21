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

# WebSocket URL for all CoinCap assets
WS_URL = "wss://ws.coincap.io/prices?assets=ALL"

# Your 15 target cryptocurrencies (CoinCap IDs)
TARGETS = {
    "bitcoin",
    "ethereum",
    "solana",
    "cardano",
    "ripple",
    "dogecoin",
    "litecoin",
    "chainlink",
    "polygon",
    "tron",
    "stellar",
    "monero",
    "binancecoin",
    "avalanche",
    "polkadot"
}

def send_signal(message):
    """Send a message to your Telegram channel."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=5)
    except Exception as e:
        print("Telegram error:", e)

def on_message(ws, message):
    """Handle every tick from CoinCap WebSocket."""
    try:
        tick = json.loads(message)
        for coin, price in tick.items():
            if coin.lower() in TARGETS:
                msg = f"{coin.upper()} → {price}"
                print(msg)
                send_signal(msg)
    except Exception as e:
        print("Parse error:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed, reconnecting in 5 seconds...")
    time.sleep(5)
    connect_ws()

def on_open(ws):
    print("WebSocket connected. Listening for crypto ticks...")

def connect_ws():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    connect_ws()
