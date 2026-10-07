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

EXCHANGE = "binance"
MARKET_TYPE = "spot"

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]


# ==========================================
# Supabase Request
# ==========================================

def supabase_request(
    method,
    endpoint,
    data=None,
    prefer=None
):

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    body = None

    if data is not None:

        body = json.dumps(
            data
        ).encode("utf-8")

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

            response_body = (
                response
                .read()
                .decode("utf-8")
            )

            if not response_body:

                return []

            return json.loads(
                response_body
            )

    except urllib.error.HTTPError as e:

        error_body = (
            e.read()
            .decode(
                "utf-8",
                errors="replace"
            )
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
# Get Active Symbols
# ==========================================

def get_active_symbols():

    params = urllib.parse.urlencode({
        "exchange": f"eq.{EXCHANGE}",
        "market_type": f"eq.{MARKET_TYPE}",
        "status": "eq.TRADING",
        "order": "symbol.asc",
    })

    return supabase_request(
        "GET",
        f"symbols?{params}"
    )


# ==========================================
# Get Candles
# ==========================================

def get_candles(
    symbol_id,
    timeframe
):

    params = urllib.parse.urlencode({
        "symbol_id": f"eq.{symbol_id}",
        "timeframe": f"eq.{timeframe}",
        "order": "open_time.asc",
    })

    return supabase_request(
        "GET",
        f"candles?{params}"
    )


# ==========================================
# Get Existing Features
# ==========================================

def get_existing_feature_timestamps(
    symbol_id,
    timeframe
):

    params = urllib.parse.urlencode({
        "symbol_id": f"eq.{symbol_id}",
        "timeframe": f"eq.{timeframe}",
        "select": "timestamp",
    })

    rows = supabase_request(
        "GET",
        f"features?{params}"
    )

    return {
        row["timestamp"]
        for row in rows
    }


# ==========================================
# Parse Timestamp
# ==========================================

def parse_timestamp(value):

    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00"
        )
    )


# ==========================================
# Build Feature
# ==========================================

def build_feature(
    symbol_id,
    timeframe,
    candle,
    previous_candle
):

    open_price = float(
        candle["open"]
    )

    high_price = float(
        candle["high"]
    )

    low_price = float(
        candle["low"]
    )

    close_price = float(
        candle["close"]
    )

    volume = float(
        candle["volume"]
    )

    body = abs(
        close_price - open_price
    )

    upper_wick = (
        high_price
        - max(
            open_price,
            close_price
        )
    )

    lower_wick = (
        min(
            open_price,
            close_price
        )
        - low_price
    )

    return_1 = None

    if previous_candle:

        previous_close = float(
            previous_candle["close"]
        )

        if previous_close != 0:

            return_1 = (
                close_price
                / previous_close
                - 1
            )

    feature = {
        "symbol_id": symbol_id,
        "timeframe": timeframe,

        "timestamp": candle[
            "close_time"
        ],

        "price": close_price,

        "return_1": return_1,

        "volume": volume,

        "candle_body": body,

        "upper_wick": upper_wick,

        "lower_wick": lower_wick,
    }

    return feature


# ==========================================
# Save Features
# ==========================================

def save_features(features):

    if not features:

        return []

    return supabase_request(
        "POST",
        "features",
        data=features,
        prefer="return=representation,resolution=ignore-duplicates"
    )


# ==========================================
# Process One Symbol / Timeframe
# ==========================================

def process_timeframe(
    symbol_record,
    timeframe
):

    symbol_id = symbol_record["id"]
    symbol = symbol_record["symbol"]

    print("------------------------------------")

    print(
        f"{symbol} - {timeframe}"
    )

    candles = get_candles(
        symbol_id,
        timeframe
    )

    print(
        f"Candles loaded: "
        f"{len(candles)}"
    )

    if not candles:

        print(
            "No candles."
        )

        return 0

    now = datetime.now(
        timezone.utc
    )

    closed_candles = []

    for candle in candles:

        close_time = parse_timestamp(
            candle["close_time"]
        )

        if close_time <= now:

            closed_candles.append(
                candle
            )

    print(
        f"Closed candles: "
        f"{len(closed_candles)}"
    )

    if not closed_candles:

        print(
            "No closed candles."
        )

        return 0

    existing = (
        get_existing_feature_timestamps(
            symbol_id,
            timeframe
        )
    )

    print(
        f"Existing features: "
        f"{len(existing)}"
    )

    features = []

    previous_candle = None

    for candle in closed_candles:

        timestamp = candle[
            "close_time"
        ]

        if timestamp in existing:

            previous_candle = candle

            continue

        feature = build_feature(
            symbol_id,
            timeframe,
            candle,
            previous_candle
        )

        features.append(
            feature
        )

        previous_candle = candle

    print(
        f"New features: "
        f"{len(features)}"
    )

    if not features:

        print(
            "No new features."
        )

        return 0

    inserted = save_features(
        features
    )

    print(
        f"Inserted features: "
        f"{len(inserted)}"
    )

    return len(inserted)


# ==========================================
# Process One Symbol
# ==========================================

def process_symbol(
    symbol_record
):

    symbol = symbol_record[
        "symbol"
    ]

    total = 0

    print()
    print("====================================")
    print(
        f"SYMBOL: {symbol}"
    )
    print("====================================")

    for timeframe in TIMEFRAMES:

        try:

            total += process_timeframe(
                symbol_record,
                timeframe
            )

        except Exception as e:

            print(
                f"ERROR: "
                f"{symbol} "
                f"{timeframe}"
            )

            print(e)

    print(
        f"{symbol} total new features: "
        f"{total}"
    )


# ==========================================
# Main
# ==========================================

def main():

    print("====================================")
    print("AI Trading System - Feature Engine")
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

    symbols = get_active_symbols()

    print(
        f"Active symbols: "
        f"{len(symbols)}"
    )

    if not symbols:

        raise RuntimeError(
            "No active symbols found."
        )

    for symbol_record in symbols:

        process_symbol(
            symbol_record
        )

    print()
    print("====================================")
    print(
        "Feature generation completed."
    )
    print("====================================")


if __name__ == "__main__":

    main()
