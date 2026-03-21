import os
import json
import time
import requests
import websocket
import threading
from dotenv import load_dotenv

# Load environment
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOLS = os.getenv("SYMBOLS", "").split(",")

# Send to Telegram
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram send error:", e)

# Handler for each tick
def on_message(ws, message):
    try:
        data = json.loads(message)
        symbol = data.get("symbol")
        price = data.get("last")
        if symbol and symbol in SYMBOLS:
            text = f"{symbol} → {price}"
            print(text)
            send_telegram(text)
    except Exception as e:
        print("Tick parse error:", e)

def on_error(ws, error):
    print("WS error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WS closed")

def on_open(ws):
    print("WS connected")
    # Subscribe to your symbols
    for sym in SYMBOLS:
        ws.send(json.dumps({"action":"Subscribe","symbol": sym}))

# Start WebSocket
def start_ws():
    wsapp = websocket.WebSocketApp(
        "wss://ws.biquote.io/",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    wsapp.run_forever()

if __name__ == "__main__":
    threading.Thread(target=start_ws).start()
    while True:
        time.sleep(1)
