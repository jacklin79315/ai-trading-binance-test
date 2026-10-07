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

SYMBOL = "BTCUSDT"

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

        print("Supabase HTTP Error:", e.code)
        print("Supabase response:", error_body)

        raise


# ==========================================
# Get Symbol ID
# ==========================================

def get_symbol_id():

    params = urllib.parse.urlencode({
        "symbol": f"eq.{SYMBOL}",
        "limit": "1",
    })

    result = supabase_request(
        f"symbols?{params}"
    )

    if not result:
        raise RuntimeError(
            f"Symbol {SYMBOL} not found."
        )

    return result[0]["id"]


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

        # 價格必須大於 0
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

        # High 不應低於其他價格
        if high_price < max(
            open_price,
            close_price,
            low_price
        ):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid high",
            })

        # Low 不應高於其他價格
        if low_price > min(
            open_price,
            close_price,
            high_price
        ):

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Invalid low",
            })

        # Volume 不應為負
        if volume < 0:

            errors.append({
                "open_time": candle["open_time"],
                "reason": "Negative volume",
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

    print("Checking BTCUSDT...")

    symbol_id = get_symbol_id()

    print(
        f"Symbol ID: {symbol_id}"
    )

    overall_errors = False

    for timeframe, minutes in TIMEFRAMES.items():

        print()
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

            overall_errors = True

            continue

        # ----------------------------------
        # Date range
        # ----------------------------------

        first_time = candles[0]["open_time"]
        latest_time = candles[-1]["open_time"]

        print(
            f"First candle: {first_time}"
        )

        print(
            f"Latest candle: {latest_time}"
        )

        # ----------------------------------
        # Duplicate check
        # ----------------------------------

        duplicates = check_duplicates(
            candles
        )

        print(
            f"Duplicates: {duplicates}"
        )

        if duplicates > 0:
            overall_errors = True

        # ----------------------------------
        # Gap check
        # ----------------------------------

        gaps = check_time_gaps(
            candles,
            minutes
        )

        print(
            f"Time gaps: {len(gaps)}"
        )

        if gaps:

            overall_errors = True

            for gap in gaps[:5]:

                print(
                    "  GAP:",
                    gap
                )

            if len(gaps) > 5:

                print(
                    f"  ... and "
                    f"{len(gaps) - 5} more"
                )

        # ----------------------------------
        # OHLC check
        # ----------------------------------

        ohlc_errors = check_ohlc(
            candles
        )

        print(
            f"OHLC errors: "
            f"{len(ohlc_errors)}"
        )

        if ohlc_errors:

            overall_errors = True

            for error in ohlc_errors[:5]:

                print(
                    "  ERROR:",
                    error
                )

            if len(ohlc_errors) > 5:

                print(
                    f"  ... and "
                    f"{len(ohlc_errors) - 5} more"
                )

        # ----------------------------------
        # Latest candle status
        # ----------------------------------

        latest_status = check_latest_candle(
            candles
        )

        print(
            f"Latest candle status: "
            f"{latest_status}"
        )

        print(
            f"Data quality: "
            f"{'PASS' if not (
                duplicates
                or gaps
                or ohlc_errors
            ) else 'CHECK'}"
        )

    print()
    print("====================================")

    if overall_errors:

        print(
            "OVERALL STATUS: CHECK REQUIRED"
        )

    else:

        print(
            "OVERALL STATUS: PASS"
        )

    print("====================================")


if __name__ == "__main__":
    main()
