import json
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone


BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]


SYMBOL = "BTCUSDT"
EXCHANGE = "binance"
MARKET_TYPE = "spot"

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

KLINE_LIMIT = 1000


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
         headers["Prefer"] = "resolution=ignore-duplicates,return=representation"

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
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")

            if response_body:
                return json.loads(response_body)

            return None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")

        print("Supabase HTTP Error:", e.code)
        print("Supabase response:", error_body)

        raise


def get_binance_klines(symbol, timeframe, limit=1000):
    params = {
        "symbol": symbol,
        "interval": timeframe,
        "limit": limit,
    }

    url = BINANCE_URL + "?" + urllib.parse.urlencode(params)

    print(f"Fetching Binance {symbol} {timeframe}...")

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def timestamp_to_iso(timestamp_ms):
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc
    ).isoformat()


def get_or_create_symbol():
    print("Checking Supabase symbols...")

    existing = supabase_request(
        "GET",
        "symbols",
        params={
            "select": "*",
            "symbol": f"eq.{SYMBOL}",
            "exchange": f"eq.{EXCHANGE}",
            "market_type": f"eq.{MARKET_TYPE}",
            "limit": "1",
        },
    )

    if existing:
        symbol_id = existing[0]["id"]
        print("Existing symbol ID:", symbol_id)
        return symbol_id

    print("Creating BTCUSDT symbol...")

    new_symbol = supabase_request(
        "POST",
        "symbols",
        data={
            "exchange": EXCHANGE,
            "symbol": SYMBOL,
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "market_type": MARKET_TYPE,
            "status": "TRADING",
        },
    )

    symbol_id = new_symbol[0]["id"]

    print("Created symbol ID:", symbol_id)

    return symbol_id


def prepare_candles(symbol_id, timeframe, klines):
    candles = []

    for k in klines:
        candles.append({
            "symbol_id": symbol_id,
            "timeframe": timeframe,

            "open_time": timestamp_to_iso(k[0]),

            "open": k[1],
            "high": k[2],
            "low": k[3],
            "close": k[4],

            "volume": k[5],

            "close_time": timestamp_to_iso(k[6]),

            "quote_volume": k[7],
            "trade_count": k[8],
        })

    return candles


def save_candles(candles):
    if not candles:
        return 0

    print(f"Writing {len(candles)} candles to Supabase...")

    result = supabase_request(
        "POST",
        "candles",
        data=candles,
    )

    return len(result) if result else 0


def main():
    print("====================================")
    print("AI Trading System - Data Collector")
    print("====================================")

    print("SUPABASE_URL exists:", bool(os.environ.get("SUPABASE_URL")))
    print("SUPABASE_KEY exists:", bool(os.environ.get("SUPABASE_KEY")))

    symbol_id = get_or_create_symbol()

    total_inserted = 0

    for timeframe in TIMEFRAMES:

        print("------------------------------------")
        print("Timeframe:", timeframe)

        klines = get_binance_klines(
            SYMBOL,
            timeframe,
            KLINE_LIMIT,
        )

        print("Binance rows:", len(klines))

        candles = prepare_candles(
            symbol_id,
            timeframe,
            klines,
        )

        print("Prepared candles:", len(candles))

        inserted = save_candles(candles)

        print("Inserted rows:", inserted)

        total_inserted += inserted

    print("====================================")
    print("Collector finished")
    print("Total inserted:", total_inserted)
    print("====================================")


if __name__ == "__main__":
    main()
