import json
import os
import urllib.parse
import urllib.request
import urllib.error


BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

print("SUPABASE_URL exists:", bool(os.environ.get("SUPABASE_URL")))
print("SUPABASE_KEY exists:", bool(os.environ.get("SUPABASE_KEY")))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]


def supabase_request(method, path, data=None, params=None):
    url = SUPABASE_URL.rstrip("/") + "/rest/v1/" + path

    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if method == "POST":
        headers["Prefer"] = "return=representation"

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")

            if response_body:
                return json.loads(response_body)

            return None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")

        print("Supabase HTTP Error:", e.code)
        print("Supabase response:", error_body)

        raise




def get_binance_klines():
    params = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "limit": 1000,
    }

    url = BINANCE_URL + "?" + urllib.parse.urlencode(params)

    print("Fetching Binance data...")

    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main():

    symbol = "BTCUSDT"
    exchange = "binance"
    market_type = "spot"

    # 1. 取得 Binance K 線
    klines = get_binance_klines()

    print("Binance rows:", len(klines))

    # 2. 查詢 Supabase 是否已經有 BTCUSDT
    print("Checking Supabase symbols...")

    existing = supabase_request(
        "GET",
        "symbols",
        params={
            "select": "*",
            "symbol": f"eq.{symbol}",
            "exchange": f"eq.{exchange}",
            "market_type": f"eq.{market_type}",
            "limit": "1",
        },
    )

    # 3. 如果沒有 BTCUSDT，就建立
    if existing:
        symbol_id = existing[0]["id"]
        print("Existing symbol ID:", symbol_id)

    else:
        print("Creating BTCUSDT symbol...")

        new_symbol = supabase_request(
            "POST",
            "symbols",
            data={
                "exchange": exchange,
                "symbol": symbol,
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "market_type": market_type,
                "status": "active",
            },
        )

        symbol_id = new_symbol[0]["id"]

        print("Created symbol ID:", symbol_id)

    # 4. 把 Binance 格式轉成 Supabase candles 格式
    candles = []

    for k in klines:
        candles.append({
            "symbol_id": symbol_id,
            "timeframe": "5m",
            "open_time": k[0],
            "open": k[1],
            "high": k[2],
            "low": k[3],
            "close": k[4],
            "volume": k[5],
            "close_time": k[6],
            "quote_volume": k[7],
            "trade_count": k[8],
            "taker_buy_base_volume": k[9],
            "taker_buy_quote_volume": k[10],
        })

    print("Prepared candles:", len(candles))

    # 5. 寫入 Supabase
    print("Writing candles to Supabase...")

    result = supabase_request(
        "POST",
        "candles",
        data=candles,
    )

    print("SUCCESS")
    print("Inserted rows:", len(result) if result else 0)


if __name__ == "__main__":
    main()
