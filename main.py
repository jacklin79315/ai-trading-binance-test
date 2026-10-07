import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone


# ==========================================
# Configuration
# ==========================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

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


# ==========================================
# Supabase Request
# ==========================================

def supabase_request(method, endpoint, data=None):

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"

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

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            response_body = response.read().decode(
                "utf-8"
            )

            if not response_body:
                return []

            return json.loads(response_body)

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            "Supabase HTTP Error:",
            e.code
        )

        print(
            "Supabase response:",
            error_body
        )

        raise


# ==========================================
# Binance Klines
# ==========================================

def get_binance_klines(
    symbol,
    interval,
    limit=1000,
    start_time=None
):

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

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            data = response.read().decode(
                "utf-8"
            )

            return json.loads(data)

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            "Binance HTTP Error:",
            e.code
        )

        print(
            "Binance response:",
            error_body
        )

        raise


# ==========================================
# Timestamp Conversion
# ==========================================

def timestamp_to_iso(timestamp_ms):

    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc
    ).isoformat()


# ==========================================
# Get Active Symbols
# ==========================================

def get_active_symbols():

    params = urllib.parse.urlencode({
        "exchange": f"eq.{EXCHANGE}",
        "market_type": f"eq.{MARKET_TYPE}",
        "status": "eq.TRADING",
        "order": "symbol.asc",
    })

    result = supabase_request(
        "GET",
        f"symbols?{params}"
    )

    return result


# ==========================================
# Get Latest Candle
# ==========================================

def get_latest_candle_time(
    symbol_id,
    timeframe
):

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


# ==========================================
# Prepare Candles
# ==========================================

def prepare_candles(
    symbol_id,
    timeframe,
    rows
):

    candles = []

    for k in rows:

        candle = {
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
        }

        candles.append(candle)

    return candles


# ==========================================
# Save Candles
# ==========================================

def save_candles(candles):

    if not candles:

        return []

    result = supabase_request(
        "POST",
        "candles",
        data=candles
    )

    return result


# ==========================================
# Collect One Symbol
# ==========================================

def collect_symbol(symbol_record):

    symbol_id = symbol_record["id"]
    symbol = symbol_record["symbol"]

    print()
    print("====================================")
    print(
        f"Symbol: {symbol}"
    )
    print(
        f"Symbol ID: {symbol_id}"
    )
    print("====================================")

    for timeframe in TIMEFRAMES:

        print("------------------------------------")

        print(
            f"{symbol} - Timeframe: "
            f"{timeframe}"
        )

        latest_open_time = (
            get_latest_candle_time(
                symbol_id,
                timeframe
            )
        )

        if latest_open_time:

            print(
                "Latest candle in Supabase:",
                latest_open_time
            )

            latest_dt = datetime.fromisoformat(
                latest_open_time.replace(
                    "Z",
                    "+00:00"
                )
            )

            start_time = int(
                latest_dt.timestamp() * 1000
            ) + 1

            print(
                "Fetching only new candles..."
            )

            rows = get_binance_klines(
                symbol,
                timeframe,
                limit=KLINE_LIMIT,
                start_time=start_time
            )

        else:

            print(
                "No existing candles."
            )

            print(
                "Fetching initial "
                "1000 candles..."
            )

            rows = get_binance_klines(
                symbol,
                timeframe,
                limit=KLINE_LIMIT
            )

        print(
            f"Binance rows: {len(rows)}"
        )

        if not rows:

            print(
                "No new candles."
            )

            continue

        candles = prepare_candles(
            symbol_id,
            timeframe,
            rows
        )

        print(
            f"Prepared candles: "
            f"{len(candles)}"
        )

        print(
            f"Writing {len(candles)} "
            "candles to Supabase..."
        )

        inserted = save_candles(
            candles
        )

        print(
            f"SUCCESS - Inserted rows: "
            f"{len(inserted)}"
        )


# ==========================================
# Main
# ==========================================

def main():

    print("====================================")
    print("AI Trading System - Data Collector")
    print("====================================")

    print(
        "SUPABASE_URL exists:",
        bool(SUPABASE_URL)
    )

    print(
        "SUPABASE_KEY exists:",
        bool(SUPABASE_KEY)
    )

    if not SUPABASE_URL:

        raise RuntimeError(
            "SUPABASE_URL is not configured."
        )

    if not SUPABASE_KEY:

        raise RuntimeError(
            "SUPABASE_KEY is not configured."
        )

    print(
        "Loading active symbols "
        "from Supabase..."
    )

    symbols = get_active_symbols()

    if not symbols:

        raise RuntimeError(
            "No active symbols found."
        )

    print(
        f"Active symbols: "
        f"{len(symbols)}"
    )

    for symbol_record in symbols:

        try:

            collect_symbol(
                symbol_record
            )

        except Exception as e:

            symbol = symbol_record["symbol"]

            print(
                f"ERROR collecting "
                f"{symbol}: {e}"
            )

            print(
                "Continuing with "
                "next symbol..."
            )

    print()
    print("------------------------------------")
    print(
        "Data collection completed."
    )
    print("====================================")


if __name__ == "__main__":

    main()
