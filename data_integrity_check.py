import os
import json
import math
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode


# ============================================================
# Configuration
# ============================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

INTERVAL_MINUTES = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

PAGE_SIZE = 1000

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}


# ============================================================
# Supabase GET
# ============================================================

def supabase_get(path, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"

    if params:
        url += "?" + urlencode(params)

    request = Request(
        url,
        headers=HEADERS,
        method="GET",
    )

    with urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")

    return json.loads(body)


# ============================================================
# Get active symbols
# ============================================================

def get_active_symbols():
    params = {
        "select": "id,symbol,exchange,market_type,status",
        "exchange": "eq.binance",
        "market_type": "eq.spot",
        "status": "eq.TRADING",
        "order": "symbol.asc",
    }

    return supabase_get("symbols", params)


# ============================================================
# Get all candles with pagination
# ============================================================

def get_all_candles(symbol_id, timeframe):
    all_rows = []
    offset = 0

    while True:
        params = {
            "select": (
                "open_time,close_time,"
                "open,high,low,close,volume,"
                "quote_volume,trade_count"
            ),
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "open_time.asc",
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }

        rows = supabase_get("candles", params)

        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return all_rows


# ============================================================
# Numeric helpers
# ============================================================

def to_float(value):
    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


# ============================================================
# Timestamp parser
# ============================================================

def parse_timestamp(value):
    if not value:
        return None

    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except Exception:
        return None


# ============================================================
# Check duplicate open_time
# ============================================================

def check_duplicates(candles):
    seen = set()
    duplicates = []

    for candle in candles:
        open_time = candle.get("open_time")

        if open_time in seen:
            duplicates.append(open_time)

        seen.add(open_time)

    return duplicates


# ============================================================
# Check time sequence / gaps
# ============================================================

def check_time_sequence(candles, timeframe):
    interval_minutes = INTERVAL_MINUTES[timeframe]

    gaps = []
    invalid_order = []

    previous_time = None

    for candle in candles:
        current_time = parse_timestamp(candle.get("open_time"))

        if current_time is None:
            continue

        if previous_time is not None:
            diff_minutes = (
                current_time - previous_time
            ).total_seconds() / 60

            if diff_minutes != interval_minutes:
                gap = {
                    "previous": candle_previous_time_text,
                    "current": candle.get("open_time"),
                    "gap_minutes": diff_minutes,
                }

                if diff_minutes > interval_minutes:
                    gaps.append(gap)
                else:
                    invalid_order.append(gap)

        previous_time = current_time
        candle_previous_time_text = candle.get("open_time")

    return gaps, invalid_order


# ============================================================
# Check OHLC
# ============================================================

def check_ohlc(candles):
    errors = []

    for candle in candles:
        open_price = to_float(candle.get("open"))
        high_price = to_float(candle.get("high"))
        low_price = to_float(candle.get("low"))
        close_price = to_float(candle.get("close"))
        volume = to_float(candle.get("volume"))
        quote_volume = to_float(candle.get("quote_volume"))

        open_time = candle.get("open_time")

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):
            errors.append({
                "open_time": open_time,
                "reason": "invalid OHLC numeric value",
            })
            continue

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
        ):
            errors.append({
                "open_time": open_time,
                "reason": "non-positive OHLC",
            })
            continue

        if high_price < max(open_price, close_price):
            errors.append({
                "open_time": open_time,
                "reason": "high below open/close",
            })

        if low_price > min(open_price, close_price):
            errors.append({
                "open_time": open_time,
                "reason": "low above open/close",
            })

        if high_price < low_price:
            errors.append({
                "open_time": open_time,
                "reason": "high below low",
            })

        if volume is None or volume < 0:
            errors.append({
                "open_time": open_time,
                "reason": "invalid volume",
            })

        if quote_volume is None or quote_volume < 0:
            errors.append({
                "open_time": open_time,
                "reason": "invalid quote volume",
            })

    return errors


# ============================================================
# Check trade count
# ============================================================

def check_trade_count(candles):
    errors = []

    for candle in candles:
        trade_count = candle.get("trade_count")

        try:
            value = int(trade_count)

            if value < 0:
                errors.append({
                    "open_time": candle.get("open_time"),
                    "reason": "negative trade_count",
                })

        except (TypeError, ValueError):
            errors.append({
                "open_time": candle.get("open_time"),
                "reason": "invalid trade_count",
            })

    return errors


# ============================================================
# Check latest candle state
# ============================================================

def check_latest_candle(candles, timeframe):
    if not candles:
        return {
            "state": "NO_DATA",
            "open_time": None,
            "close_time": None,
        }

    latest = candles[-1]

    open_time = parse_timestamp(latest.get("open_time"))
    close_time = parse_timestamp(latest.get("close_time"))

    now = datetime.now(timezone.utc)

    if close_time is None:
        state = "INVALID_CLOSE_TIME"

    elif close_time <= now:
        state = "CLOSED"

    else:
        state = "OPEN"

    return {
        "state": state,
        "open_time": latest.get("open_time"),
        "close_time": latest.get("close_time"),
    }


# ============================================================
# Expected interval check
# ============================================================

def calculate_expected_count(earliest, latest, timeframe):
    if not earliest or not latest:
        return None

    start = parse_timestamp(earliest)
    end = parse_timestamp(latest)

    if start is None or end is None:
        return None

    interval_minutes = INTERVAL_MINUTES[timeframe]

    diff_minutes = (
        end - start
    ).total_seconds() / 60

    if diff_minutes < 0:
        return None

    return int(diff_minutes / interval_minutes) + 1


# ============================================================
# Check one symbol + timeframe
# ============================================================

def check_symbol_timeframe(symbol, symbol_id, timeframe):
    print()
    print("=" * 70)
    print(f"Checking {symbol} - {timeframe}")
    print("=" * 70)

    candles = get_all_candles(symbol_id, timeframe)

    total_rows = len(candles)

    if total_rows == 0:
        print("Candles              : 0")
        print("STATUS               : NO DATA")
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "NO DATA",
        }

    duplicates = check_duplicates(candles)

    gaps, invalid_order = check_time_sequence(
        candles,
        timeframe,
    )

    ohlc_errors = check_ohlc(candles)

    trade_count_errors = check_trade_count(candles)

    earliest = candles[0].get("open_time")
    latest = candles[-1].get("open_time")

    expected_count = calculate_expected_count(
        earliest,
        latest,
        timeframe,
    )

    latest_state = check_latest_candle(
        candles,
        timeframe,
    )

    # --------------------------------------------------------
    # Print summary
    # --------------------------------------------------------

    print(f"Candles              : {total_rows}")
    print(f"Unique open_time     : {total_rows - len(duplicates)}")
    print(f"Duplicate count      : {len(duplicates)}")
    print(f"Gap count            : {len(gaps)}")
    print(f"Invalid order count  : {len(invalid_order)}")
    print(f"OHLC errors          : {len(ohlc_errors)}")
    print(f"Trade count errors   : {len(trade_count_errors)}")
    print(f"Earliest             : {earliest}")
    print(f"Latest               : {latest}")
    print(f"Expected by range    : {expected_count}")
    print(f"Latest candle state  : {latest_state['state']}")

    # --------------------------------------------------------
    # Print first few problems
    # --------------------------------------------------------

    if duplicates:
        print()
        print("DUPLICATES:")
        for item in duplicates[:10]:
            print(f"  {item}")

    if gaps:
        print()
        print("GAPS:")
        for item in gaps[:20]:
            print(
                f"  {item['previous']} -> "
                f"{item['current']} "
                f"({item['gap_minutes']} minutes)"
            )

    if invalid_order:
        print()
        print("INVALID TIME ORDER:")
        for item in invalid_order[:20]:
            print(
                f"  {item['previous']} -> "
                f"{item['current']} "
                f"({item['gap_minutes']} minutes)"
            )

    if ohlc_errors:
        print()
        print("OHLC ERRORS:")
        for item in ohlc_errors[:10]:
            print(
                f"  {item['open_time']} "
                f"{item['reason']}"
            )

    if trade_count_errors:
        print()
        print("TRADE COUNT ERRORS:")
        for item in trade_count_errors[:10]:
            print(
                f"  {item['open_time']} "
                f"{item['reason']}"
            )

    # --------------------------------------------------------
    # Determine status
    # --------------------------------------------------------

    failed = (
        len(duplicates) > 0
        or len(gaps) > 0
        or len(invalid_order) > 0
        or len(ohlc_errors) > 0
        or len(trade_count_errors) > 0
    )

    if failed:
        status = "FAIL"
    else:
        status = "PASS"

    print()
    print(f"STATUS               : {status}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "total_rows": total_rows,
        "duplicate_count": len(duplicates),
        "gap_count": len(gaps),
        "invalid_order_count": len(invalid_order),
        "ohlc_error_count": len(ohlc_errors),
        "trade_count_error_count": len(trade_count_errors),
        "earliest": earliest,
        "latest": latest,
        "expected_count": expected_count,
        "latest_state": latest_state["state"],
    }


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("DATA INTEGRITY CHECK")
    print("=" * 70)
    print("Read-only validation. No database modifications.")
    print("=" * 70)

    symbols = get_active_symbols()

    print()
    print(f"Active symbols: {len(symbols)}")

    results = []

    for symbol_data in symbols:
        symbol = symbol_data["symbol"]
        symbol_id = symbol_data["id"]

        for timeframe in TIMEFRAMES:
            try:
                result = check_symbol_timeframe(
                    symbol,
                    symbol_id,
                    timeframe,
                )

                results.append(result)

            except Exception as exc:
                print()
                print(f"ERROR: {symbol} - {timeframe}")
                print(str(exc))

                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "ERROR",
                })

    # ========================================================
    # Final summary
    # ========================================================

    print()
    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    pass_count = 0
    fail_count = 0
    error_count = 0
    no_data_count = 0

    for result in results:
        symbol = result["symbol"]
        timeframe = result["timeframe"]
        status = result["status"]

        print(
            f"{symbol:<12} "
            f"{timeframe:<5} "
            f"{status}"
        )

        if status == "PASS":
            pass_count += 1

        elif status == "FAIL":
            fail_count += 1

        elif status == "ERROR":
            error_count += 1

        elif status == "NO DATA":
            no_data_count += 1

    print()
    print(f"PASS     : {pass_count}")
    print(f"FAIL     : {fail_count}")
    print(f"ERROR    : {error_count}")
    print(f"NO DATA  : {no_data_count}")

    if fail_count == 0 and error_count == 0 and no_data_count == 0:
        print()
        print("OVERALL: PASS")
    else:
        print()
        print("OVERALL: CHECK REQUIRED")


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
