import json
import urllib.parse
import urllib.request
import time


BASE_URL = "https://data-api.binance.vision/api/v3/klines"

symbol = "BTCUSDT"
intervals = ["5m", "15m", "1h", "4h", "1d"]

for interval in intervals:

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": 1000,
    }

    url = BASE_URL + "?" + urllib.parse.urlencode(params)

    print("\n" + "=" * 50)
    print("Interval:", interval)
    print("Fetching:", url)

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        print("SUCCESS")
        print("Rows:", len(data))

        if data:
            print("First open time:", data[0][0])
            print("Last open time:", data[-1][0])
            print("Latest close:", data[-1][4])
            print("Latest volume:", data[-1][5])
            print("Latest trade count:", data[-1][8])

    except Exception as e:
        print("FAILED")
        print("Error:", repr(e))

    time.sleep(0.5)
