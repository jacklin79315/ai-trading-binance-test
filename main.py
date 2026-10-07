import urllib.request
import json

url = "https://api.binance.com/api/v3/ping"

try:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8")
        print("BINANCE_TEST")
        print("Status:", response.status)
        print("Response:", body)

except Exception as e:
    print("BINANCE_TEST_FAILED")
    print("Error:", repr(e))
