import urllib.request

urls = [
    "https://api.binance.com/api/v3/ping",
    "https://data-api.binance.vision/api/v3/ping",
]

for url in urls:
    print("\nTEST:", url)

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
            print("Status:", response.status)
            print("Response:", body)

    except Exception as e:
        print("FAILED:", repr(e))
