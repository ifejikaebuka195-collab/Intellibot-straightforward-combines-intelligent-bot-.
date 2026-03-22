# ==========================================
# SMALL DERIV TICK STREAMER (REAL WEBSOCKET)
# ==========================================

import asyncio
import json
import websockets
from collections import deque

# ✅ CONFIG
DERIV_APP_ID = "1089"
DERIV_API_TOKEN = "YOUR_DERIV_API_TOKEN"
DERIV_WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"

# ✅ SYMBOLS
OTC_PAIRS = ["R_100", "R_75", "R_50", "R_25", "R_10", "R_10S", "R_25S"]
CRYPTO_PAIRS = ["cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "cryBCHUSD", "cryEOSUSD", "cryTRXUSD"]

ALL_PAIRS = OTC_PAIRS + CRYPTO_PAIRS

# ✅ GLOBAL STORAGE
TICKS = {pair: deque(maxlen=300) for pair in ALL_PAIRS}

# =========================
# DERIV WEBSOCKET CONNECTOR
# =========================
async def stream_ticks():
    while True:
        try:
            print("🌐 Connecting to Deriv WebSocket...")
            async with websockets.connect(DERIV_WS_URL) as ws:

                # AUTHORIZE ACCOUNT
                await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
                auth_resp = json.loads(await ws.recv())

                if "error" in auth_resp:
                    print("❌ Authorization failed:", auth_resp)
                    await asyncio.sleep(5)
                    continue
                print("✅ Authorized with Deriv WebSocket!")

                # SUBSCRIBE TO ALL PAIRS
                for pair in ALL_PAIRS:
                    await ws.send(json.dumps({"ticks": pair, "subscribe": 1}))

                print("✅ Subscribed to all pairs. Streaming ticks...")

                # STREAM TICKS
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    if "tick" in data:
                        symbol = data["tick"]["symbol"]
                        price = data["tick"]["quote"]
                        TICKS[symbol].append(price)
                        print(f"💹 {symbol}: {price}")

        except Exception as e:
            print("⚠️ Connection lost, reconnecting in 3s...", e)
            await asyncio.sleep(3)

# =========================
# MAIN
# =========================
def main():
    loop = asyncio.get_event_loop()
    loop.create_task(stream_ticks())
    print("🚀 Tick streamer started. Check your deployed console for live ticks.")
    loop.run_forever()

if __name__ == "__main__":
    main()
