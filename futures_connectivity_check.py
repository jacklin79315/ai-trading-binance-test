
import json
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://fapi.binance.com"

TESTS = [
    (
        "BTCUSDT Funding",
        "/fapi/v1/fundingRate",
        {"symbol": "BTCUSDT", "limit": 2},
    ),
    (
        "BTCUSDT OI History",
        "/futures/data/openInterestHist",
        {"symbol": "BTCUSDT", "period": "5m", "limit": 2},
    ),
    (
        "PENGUUSDT Funding",
        "/fapi/v1/fundingRate",
        {"symbol": "PENGUUSDT", "limit": 2},
    ),
    (
        "PENGUUSDT OI History",
        "/futures/data/openInterestHist",
        {"symbol": "PENGUUSDT", "period": "5m", "limit": 2},
    ),
]

def main():
    passed = 0

    for name, endpoint, params in TESTS:
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(params)
        print(f"\n--- {name} ---")

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "futures-connectivity-check/1.0"},
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)

                if isinstance(data, list) and data:
                    print("HTTP:", response.status)
                    print("Rows:", len(data))
                    print("Sample:", json.dumps(data[0], ensure_ascii=False))
                    passed += 1
                elif isinstance(data, dict):
                    print("HTTP:", response.status)
                    print("Response:", json.dumps(data, ensure_ascii=False))
                else:
                    print("HTTP:", response.status)
                    print("Empty response:", body[:300])

        except urllib.error.HTTPError as exc:
            print("HTTP ERROR:", exc.code)
            print("Details:", exc.read().decode("utf-8", errors="replace")[:300])
        except Exception as exc:
            print("CONNECTION ERROR:", repr(exc))

    print(f"\nRESULT: {passed}/{len(TESTS)} tests returned data")

if __name__ == "__main__":
    main()
