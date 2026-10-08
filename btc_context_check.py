import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

EXPECTED_MIN_ROWS = {
    "5m": 100000,
    "15m": 900,
    "1h": 900,
    "4h": 900,
    "1d": 900,
}

NUMERIC_FIELDS = [
    "btc_price",
    "btc_return_1",
    "btc_return_3",
    "btc_return_5",
    "btc_return_10",
    "btc_rsi_6",
    "btc_rsi_12",
    "btc_rsi_24",
    "btc_atr",
    "btc_atr_percent",
    "btc_volume",
    "btc_volume_ratio",
    "btc_price_sma20_ratio",
    "btc_price_sma50_ratio",
    "btc_price_sma200_ratio",
    "btc_sma20_slope",
    "btc_sma50_slope",
    "btc_sma200_slope",
    "btc_trend_alignment_score",
]


def supabase_get(table, params):
    query = urllib.parse.urlencode(params)
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def get_rows(timeframe):
    rows = []
    offset = 0
    page_size = 1000

    while True:
        page = supabase_get(
            "btc_market_context",
            {
                "select": "*",
                "timeframe": f"eq.{timeframe}",
                "order": "timestamp.asc",
                "offset": offset,
                "limit": page_size,
            },
        )

        if not page:
            break

        rows.extend(page)

        if len(page) < page_size:
            break

        offset += page_size

    return rows


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_numeric_integrity(rows, timeframe):
    failures = []

    for row in rows:
        for field in NUMERIC_FIELDS:
            value = row.get(field)

            if value is None:
                continue

            if not is_number(value):
                failures.append(
                    f"{timeframe} {row.get('timestamp')} "
                    f"{field} is not numeric: {value}"
                )
                continue

            if field.startswith("btc_rsi_"):
                if value < 0 or value > 100:
                    failures.append(
                        f"{timeframe} {row.get('timestamp')} "
                        f"{field} out of range: {value}"
                    )

            elif field == "btc_volume_ratio":
                if value < 0:
                    failures.append(
                        f"{timeframe} {row.get('timestamp')} "
                        f"{field} negative: {value}"
                    )

            elif field == "btc_atr":
                if value < 0:
                    failures.append(
                        f"{timeframe} {row.get('timestamp')} "
                        f"{field} negative: {value}"
                    )

            elif field == "btc_atr_percent":
                if value < 0:
                    failures.append(
                        f"{timeframe} {row.get('timestamp')} "
                        f"{field} negative: {value}"
                    )

            elif field == "btc_trend_alignment_score":
                if value < -1 or value > 1:
                    failures.append(
                        f"{timeframe} {row.get('timestamp')} "
                        f"{field} out of range: {value}"
                    )

    return failures


def check_uniqueness(rows, timeframe):
    timestamps = [row.get("timestamp") for row in rows]

    duplicates = len(timestamps) - len(set(timestamps))

    if duplicates > 0:
        return [
            f"{timeframe}: {duplicates} duplicate timestamps"
        ]

    return []


def check_timestamp_order(rows, timeframe):
    failures = []

    previous = None

    for row in rows:
        timestamp = row.get("timestamp")

        if not timestamp:
            failures.append(
                f"{timeframe}: missing timestamp"
            )
            continue

        if previous is not None and timestamp <= previous:
            failures.append(
                f"{timeframe}: timestamp order violation "
                f"{previous} -> {timestamp}"
            )

        previous = timestamp

    return failures


def check_timestamp_alignment(rows, timeframe):
    failures = []

    previous_dt = None

    for row in rows:
        timestamp = row.get("timestamp")

        if not timestamp:
            continue

        try:
            dt = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        except Exception:
            failures.append(
                f"{timeframe}: invalid timestamp {timestamp}"
            )
            continue

        # Binance candle close_time normally ends at
        # xx:xx:59.999 for minute-based intervals.
        #
        # Examples:
        # 5m  -> 22:14:59.999
        # 15m -> 22:29:59.999
        # 1h  -> 22:59:59.999
        # 4h  -> 23:59:59.999
        # 1d  -> 23:59:59.999
        #
        # Therefore alignment must be checked against the
        # END of the candle, not the beginning.

        if dt.microsecond not in (0, 999000):
            failures.append(
                f"{timeframe}: unexpected microsecond "
                f"{dt.microsecond} at {timestamp}"
            )

        if timeframe == "5m":
            if dt.second != 59 or dt.minute % 5 != 4:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

        elif timeframe == "15m":
            if dt.second != 59 or dt.minute % 15 != 14:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

        elif timeframe == "1h":
            if dt.second != 59 or dt.minute != 59:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

        elif timeframe == "4h":
            if dt.second != 59 or dt.minute != 59:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

            # 4h candles close at 03:59, 07:59, 11:59,
            # 15:59, 19:59, 23:59 UTC.
            if (dt.hour + 1) % 4 != 0:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

        elif timeframe == "1d":
            if dt.hour != 23 or dt.minute != 59 or dt.second != 59:
                failures.append(
                    f"{timeframe}: timestamp not aligned: {timestamp}"
                )

        if previous_dt is not None:
            delta_minutes = (
                dt - previous_dt
            ).total_seconds() / 60

            if delta_minutes <= 0:
                failures.append(
                    f"{timeframe}: non-positive timestamp delta"
                )

        previous_dt = dt

    return failures


def check_required_fields(rows, timeframe):
    failures = []

    if not rows:
        return [f"{timeframe}: no rows"]

    required = [
        "timeframe",
        "timestamp",
        "btc_price",
    ]

    for row in rows:
        for field in required:
            if row.get(field) is None:
                failures.append(
                    f"{timeframe}: missing required field "
                    f"{field} at {row.get('timestamp')}"
                )

    return failures


def check_timeframe_values(rows, timeframe):
    failures = []

    for row in rows:
        if row.get("timeframe") != timeframe:
            failures.append(
                f"{timeframe}: incorrect timeframe value "
                f"{row.get('timeframe')}"
            )

    return failures


def check_historical_depth(rows, timeframe):
    if len(rows) < EXPECTED_MIN_ROWS[timeframe]:
        return [
            f"{timeframe}: insufficient rows "
            f"{len(rows)} < {EXPECTED_MIN_ROWS[timeframe]}"
        ]

    return []


def main():
    print("=" * 70)
    print("BTC MARKET CONTEXT CHECK - PHASE 2B-1")
    print("=" * 70)

    total_rows = 0
    failed_timeframes = []
    all_failures = []

    for timeframe in TIMEFRAMES:
        print("=" * 60)
        print(f"Checking BTC Context - {timeframe}")

        rows = get_rows(timeframe)
        total_rows += len(rows)

        print(f"Rows: {len(rows)}")

        failures = []

        failures.extend(
            check_required_fields(rows, timeframe)
        )

        failures.extend(
            check_timeframe_values(rows, timeframe)
        )

        failures.extend(
            check_uniqueness(rows, timeframe)
        )

        failures.extend(
            check_timestamp_order(rows, timeframe)
        )

        failures.extend(
            check_timestamp_alignment(rows, timeframe)
        )

        failures.extend(
            check_numeric_integrity(rows, timeframe)
        )

        failures.extend(
            check_historical_depth(rows, timeframe)
        )

        if failures:
            failed_timeframes.append(timeframe)

            print("STATUS: FAIL")

            for failure in failures[:20]:
                print(f"  - {failure}")

            if len(failures) > 20:
                print(
                    f"  ... and {len(failures) - 20} more"
                )

            all_failures.extend(failures)

        else:
            print("STATUS: PASS")

    print("=" * 70)
    print(f"Total rows checked: {total_rows}")
    print(
        f"Failed timeframes: {len(failed_timeframes)}"
    )

    if failed_timeframes:
        print(
            f"Failed: {', '.join(failed_timeframes)}"
        )
        print("=" * 70)
        print("STATUS: FAIL")
        return

    print("=" * 70)
    print("STATUS: PASS")
    print("=" * 70)


if __name__ == "__main__":
    main()
