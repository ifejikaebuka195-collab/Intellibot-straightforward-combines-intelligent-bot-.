import os
import json
import time
import websocket
import requests
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Function to send Telegram message
def send_signal(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=5)
    except Exception as e:
        print("Telegram error:", e)

# Called every time a WebSocket message (tick) is received
def on_message(ws, message):
    try:
        data = json.loads(message)
        # Every tick sends a signal to Telegram
        send_signal(f"Tick: {json.dumps(data)}")
    except Exception as e:
        print("Error parsing tick:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed. Reconnecting in 5 seconds...")
    time.sleep(5)
    connect_ws()  # reconnect automatically

def on_open(ws):
    print("WebSocket connected. Listening for every tick...")

# Connect to CoinCap WebSocket for your crypto pairs
def connect_ws():
    ws = websocket.WebSocketApp(
        "wss://ws.coincap.io/prices?assets=bitcoin,ethereum,cardano,algorand,avax,bat,bch,bnb,ltc,doge,sol,trx,xmr,xlm",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    connect_ws()
