import json
import time
import websocket
import requests

# ⚠️ Your Telegram bot token and chat ID (directly in the script)
BOT_TOKEN = "8751531182:AAHRVd3Zeo7Z9wUWb9q7ruiH_lppQE_ymak"
CHAT_ID = "8308393231"

def send_signal(message):
    """Send a message to your Telegram bot safely."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=5)
    except Exception as e:
        print("Telegram send error:", e)

def on_message(ws, message):
    """Triggered on every tick from WebSocket."""
    try:
        data = json.loads(message)
        # Every tick sends a signal
        send_signal(f"Tick received: {json.dumps(data)}")
    except Exception as e:
        print("Error parsing tick:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed, reconnecting in 5 seconds...")
    time.sleep(5)
    connect_ws()  # Reconnect automatically

def on_open(ws):
    print("WebSocket connected. Listening for all ticks...")

def connect_ws():
    """Connects to Pocket Option public demo WebSocket."""
    ws = websocket.WebSocketApp(
        "wss://ws.pocketoption.com/socket.io/?EIO=4&transport=websocket",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    connect_ws()
