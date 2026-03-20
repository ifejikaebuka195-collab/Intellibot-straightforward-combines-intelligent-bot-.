import websocket

try:
    ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089")
    print("Connection successful!")
    ws.close()
except Exception as e:
    print("Connection failed:", e)
