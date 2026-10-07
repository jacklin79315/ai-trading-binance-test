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

TIMEFRAMES = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


# ==========================================
# Supabase Request
# ==========================================

def supabase_request(endpoint):

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
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
        "select": (
            "open_time,"
            "close_time,"
            "open,"
            "high,"
            "low,"
            "close,"
            "volume,"
            "trade_count"
        ),
    })

    return supabase_request(
        f"candles?{params}"
    )


# ==========================================
# Check Duplicate
# ==========================================

def check_duplicates(candles):

    seen = set()
    duplicates = 0

    for candle in candles:

        key = candle["open_time"]

        if key in seen:
            duplicates += 1

        seen.add(key)

    return duplicates


# ==========================================
# Check Time Gaps
# ==========================================

def check_time_gaps(
    candles,
    timeframe_minutes
):

    if len(candles) < 2:
        return []

    expected_seconds = (
        timeframe_minutes * 60
    )

    gaps = []

    for i in range(1, len(candles)):

        previous = datetime.fromisoformat(
            candles[i - 1]["open_time"].replace(
                "Z",
                "+00:00"
            )
        )

        current = datetime.fromisoformat(
            candles[i]["open_time"].replace(
                "Z",
                "+00:00"
            )
        )

        actual_seconds = (
            current - previous
        ).total_seconds()

        if actual_seconds != expected_seconds:

            gaps.append({
                "previous": candles[i - 1]["open_time"],
                "current": candles[i]["open_time"],
                "actual_minutes": actual_seconds / 60,
                "expected_minutes": timeframe_minutes,
            })

    return gaps


# ==========================================
# Check OHLC
# ==========================================

def check_ohlc(candles):

    errors = []

    for candle in candles:

        try:

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

        except (TypeError, ValueError):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid numeric value",
            })

            continue

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
        ):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Price <= 0",
            })

            continue

        if high_price < max(
            open_price,
            close_price,
            low_price
        ):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid high",
            })

        if low_price > min(
            open_price,
            close_price,
            high_price
        ):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid low",
            })

        if volume < 0:

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Negative volume",
            })

    return errors


# ==========================================
# Check Time Alignment
# ==========================================

def check_time_alignment(
    candles,
    timeframe
):

    errors = []

    for candle in candles:

        dt = datetime.fromisoformat(
            candle["open_time"].replace(
                "Z",
                "+00:00"
            )
        )

        valid = True

        if timeframe == "5m":

            valid = (
                dt.minute % 5 == 0
                and dt.second == 0
            )

        elif timeframe == "15m":

            valid = (
                dt.minute % 15 == 0
                and dt.second == 0
            )

        elif timeframe == "1h":

            valid = (
                dt.minute == 0
                and dt.second == 0
            )

        elif timeframe == "4h":

            valid = (
                dt.hour % 4 == 0
                and dt.minute == 0
                and dt.second == 0
            )

        elif timeframe == "1d":

            valid = (
                dt.hour == 0
                and dt.minute == 0
                and dt.second == 0
            )

        if not valid:

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid timeframe alignment",
            })

    return errors


# ==========================================
# Check Latest Candle
# ==========================================

def check_latest_candle(candles):

    if not candles:

        return None

    latest = candles[-1]

    close_time = datetime.fromisoformat(
        latest["close_time"].replace(
            "Z",
            "+00:00"
        )
    )

    now = datetime.now(
        timezone.utc
    )

    if close_time <= now:

        return "CLOSED"

    return "OPEN"


# ==========================================
# Check One Symbol
# ==========================================

def check_symbol(symbol_record):

    symbol = symbol_record["symbol"]
    symbol_id = symbol_record["id"]

    print()
    print("====================================")
    print(f"SYMBOL: {symbol}")
    print(f"Symbol ID: {symbol_id}")
    print("====================================")

    symbol_pass = True

    for timeframe, minutes in TIMEFRAMES.items():

        print("------------------------------------")
        print(
            f"Timeframe: {timeframe}"
        )

        candles = get_candles(
            symbol_id,
            timeframe
        )

        print(
            f"Rows: {len(candles)}"
        )

        if not candles:

            print("STATUS: NO DATA")

            symbol_pass = False

            continue

        first_time = candles[0]["open_time"]
        latest_time = candles[-1]["open_time"]

        print(
            f"First candle: {first_time}"
        )

        print(
            f"Latest candle: {latest_time}"
        )

        duplicates = check_duplicates(
            candles
        )

        gaps = check_time_gaps(
            candles,
            minutes
        )

        ohlc_errors = check_ohlc(
            candles
        )

        alignment_errors = (
            check_time_alignment(
                candles,
                timeframe
            )
        )

        latest_status = (
            check_latest_candle(
                candles
            )
        )

        print(
            f"Duplicates: {duplicates}"
        )

        print(
            f"Time gaps: {len(gaps)}"
        )

        print(
            f"OHLC errors: "
            f"{len(ohlc_errors)}"
        )

        print(
            f"Alignment errors: "
            f"{len(alignment_errors)}"
        )

        print(
            f"Latest candle status: "
            f"{latest_status}"
        )

        timeframe_pass = (
            duplicates == 0
            and len(gaps) == 0
            and len(ohlc_errors) == 0
            and len(alignment_errors) == 0
        )

        print(
            f"Data quality: "
            f"{'PASS' if timeframe_pass else 'CHECK'}"
        )

        if not timeframe_pass:

            symbol_pass = False

            for gap in gaps[:3]:

                print(
                    "  GAP:",
                    gap
                )

            for error in ohlc_errors[:3]:

                print(
                    "  OHLC:",
                    error
                )

            for error in alignment_errors[:3]:

                print(
                    "  ALIGNMENT:",
                    error
                )

    print()
    print(
        f"{symbol} OVERALL: "
        f"{'PASS' if symbol_pass else 'CHECK'}"
    )

    return symbol_pass


# ==========================================
# Main
# ==========================================

def main():

    print("====================================")
    print("AI Trading System - Data Quality")
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
        f"Active symbols: {len(symbols)}"
    )

    if not symbols:

        raise RuntimeError(
            "No active symbols found."
        )

    results = []

    for symbol_record in symbols:

        result = check_symbol(
            symbol_record
        )

        results.append({
            "symbol": symbol_record["symbol"],
            "pass": result,
        })

    print()
    print("====================================")
    print("FINAL SUMMARY")
    print("====================================")

    for result in results:

        print(
            f"{result['symbol']}: "
            f"{'PASS' if result['pass'] else 'CHECK'}"
        )

    overall_pass = all(
        result["pass"]
        for result in results
    )

    print("------------------------------------")

    if overall_pass:

        print(
            "OVERALL STATUS: PASS"
        )

    else:

        print(
            "OVERALL STATUS: CHECK REQUIRED"
        )

    print("====================================")


if __name__ == "__main__":

    main()
