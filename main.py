import asyncio
import json
import websockets
import logging
from collections import deque

# ----------------------
# CONFIG
# ----------------------
DERIV_WS = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# Example pairs to stream
PAIRS = ["R_100", "R_75", "cryBTCUSD", "cryETHUSD"]

# Max number of ticks to store
MAX_TICKS = 100

# Storage for ticks
ticks = {pair: deque(maxlen=MAX_TICKS) for pair in PAIRS}

logging.basicConfig(level=logging.INFO)

# ----------------------
# STREAM TICKS
# ----------------------
async def stream_ticks():
    while True:
        try:
            async with websockets.connect(DERIV_WS) as ws:
                logging.info("🌐 Connected to Deriv WebSocket")

                # Subscribe to all pairs
                for pair in PAIRS:
                    await ws.send(json.dumps({
                        "ticks": pair,
                        "subscribe": 1
                    }))
                    logging.info(f"✅ Subscribed to {pair}")

                # Receive ticks
                async for msg in ws:
                    data = json.loads(msg)
                    if "tick" in data:
                        symbol = data["tick"]["symbol"]
                        quote = data["tick"]["quote"]
                        ticks[symbol].append(quote)
                        logging.info(f"💹 {symbol}: {quote}")

        except Exception as e:
            logging.error(f"❌ Connection lost: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)

# ----------------------
# RUN
# ----------------------
asyncio.run(stream_ticks())
