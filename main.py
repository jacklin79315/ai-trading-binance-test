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


def get_binance_klines(symbol, interval, limit=1000, start_time=None):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    if start_time is not None:
        params["startTime"] = start_time

    query = urllib.parse.urlencode(params)

    url = f"{BINANCE_URL}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data


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

def get_latest_candle_time(symbol_id, timeframe):
    params = urllib.parse.urlencode({
        "symbol_id": f"eq.{symbol_id}",
        "timeframe": f"eq.{timeframe}",
        "order": "open_time.desc",
        "limit": "1",
    })

    result = supabase_request(
        "GET",
        f"candles?{params}"
    )

    if not result:
        return None

    return result[0]["open_time"]
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
    print(f"Timeframe: {timeframe}")

    latest_open_time = get_latest_candle_time(
        symbol_id,
        timeframe
    )

    if latest_open_time:
        print(f"Latest candle in Supabase: {latest_open_time}")

        latest_dt = datetime.fromisoformat(
            latest_open_time.replace("Z", "+00:00")
        )

        # 從下一根 K 線開始抓
        start_time = int(
            latest_dt.timestamp() * 1000
        ) + 1

        print("Fetching only new candles...")
        rows = get_binance_klines(
            SYMBOL,
            timeframe,
            limit=KLINE_LIMIT,
            start_time=start_time
        )

    else:
        print("No existing candles. Fetching initial 1000 candles...")

        rows = get_binance_klines(
            SYMBOL,
            timeframe,
            limit=KLINE_LIMIT
        )

    print(f"Binance rows: {len(rows)}")

    if not rows:
        print("No new candles.")
        continue

    candles = prepare_candles(
        symbol_id,
        timeframe,
        rows
    )

    print(f"Prepared candles: {len(candles)}")

    inserted = save_candles(candles)

    print(f"Inserted rows: {len(inserted)}")


if __name__ == "__main__":
    main()
