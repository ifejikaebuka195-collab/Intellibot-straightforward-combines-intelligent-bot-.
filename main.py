import asyncio
import websockets

async def test_ws():
    try:
        async with websockets.connect("wss://ws.binaryws.com/websockets/v3?app_id=1089") as ws:
            print("Connection successful!")
    except Exception as e:
        print("Connection failed:", e)

asyncio.run(test_ws())
