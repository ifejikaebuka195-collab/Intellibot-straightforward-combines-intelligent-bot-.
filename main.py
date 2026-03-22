# ONLY KEY FIXES APPLIED:
# 1. Removed blocking sleep inside websocket
# 2. Updated time inside loop
# 3. Safe websocket reconnect
# 4. Prevent crash from NoneType transport

async def system_loop():
    global last_signal_time, signal_count_hour, last_hour, pending_signal, signal_ready

    while True:
        now = datetime.now(TIMEZONE)

        # Reset hourly counter
        if last_hour != now.hour:
            signal_count_hour = 0
            last_hour = now.hour

        weekday = now.weekday()
        hour = now.hour

        if (weekday == 4 and hour >= 21) or weekday in [5,6]:
            symbols = CRYPTO_PAIRS
        else:
            symbols = await get_symbols()

        while True:
            try:
                async with websockets.connect(
                    DERIV_WS,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:

                    for s in symbols:
                        await ws.send(json.dumps({"ticks": s, "subscribe": 1}))

                    async for msg in ws:
                        now = datetime.now(TIMEZONE)  # ✅ FIX: update time live

                        data = json.loads(msg)

                        if "tick" not in data:
                            continue

                        pair = data["tick"]["symbol"]
                        price = data["tick"]["quote"]

                        prices[pair].append(price)

                        if len(prices[pair]) < 60:
                            continue

                        direction, score = analyze_pair(prices[pair])

                        if not direction or score < 75:
                            pending_signal = None
                            signal_ready = False
                            continue

                        # stabilization logic (unchanged)
                        if pending_signal and pending_signal[0] == pair and pending_signal[1] == direction:
                            signal_ready = True
                        else:
                            pending_signal = (pair, direction, score)
                            signal_ready = False

                        if signal_ready:
                            if signal_count_hour >= 2:
                                continue

                            if (now - last_signal_time).total_seconds() < MIN_SIGNAL_INTERVAL:
                                continue

                            accuracy = min(95, int(score))
                            trend_type = "Stable Trend" if score < 90 else "Strong Breakout"

                            send_signal(pair, direction, accuracy, trend_type)

                            last_signal_time = now
                            signal_count_hour += 1

                            pending_signal = None
                            signal_ready = False

                            # ❌ REMOVED blocking sleep
                            # ✅ replaced with non-blocking cooldown
                            await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"WebSocket reconnecting due to: {e}")
                await asyncio.sleep(3)
