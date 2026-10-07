import json
import urllib.parse
import urllib.request


BASE_URL = "https://data-api.binance.vision/api/v3/klines"

params = {
    "symbol": "BTCUSDT",
    "interval": "5m",
    "limit": 1000,
}

url = BASE_URL + "?" + urllib.parse.urlencode(params)

print("Fetching Binance Kline data...")
print("URL:", url)

try:
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    print("\nSUCCESS")
    print("Rows:", len(data))

    if data:
        print("\nFirst candle:")
        print(data[0])

        print("\nLast candle:")
        print(data[-1])

        print("\nLatest close price:")
        print(data[-1][4])

except Exception as e:
    print("\nFAILED")
    print("Error:", repr(e))
