import os
import json
import math
import urllib.request
import urllib.parse

from btc_context_engine import calculate_context


SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

BTC_SYMBOL = "BTCUSDT"

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

SAMPLE_COUNT = 10

TOLERANCE = 1e-9

CHECK_FIELDS = [
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
    query = urllib.parse.urlencode(
        params,
        doseq=True,
    )

    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=60,
    ) as response:
        raw = response.read()

        if not raw:
            return []

        return json.loads(
            raw.decode("utf-8")
        )


def get_btc_symbol_id():
    rows = supabase_get(
        "symbols",
        {
            "select": "id,symbol,market_type",
            "symbol": f"eq.{BTC_SYMBOL}",
            "limit": "10",
        },
    )

    if not rows:
        raise RuntimeError(
            "BTCUSDT symbol not found."
        )

    for row in rows:
        market_type = str(
            row.get("market_type", "")
        ).lower()

        if market_type == "spot":
            return row["id"]

    print("BTCUSDT rows found:")

    for row in rows:
        print(row)

    raise RuntimeError(
        "BTCUSDT SPOT symbol not found."
    )


def get_all_rows(
    table,
    params,
):
    rows = []
    offset = 0

    while True:
        request_params = dict(params)

        request_params["limit"] = "1000"
        request_params["offset"] = str(
            offset
        )

        batch = supabase_get(
            table,
            request_params,
        )

        if not batch:
            break

        rows.extend(batch)

        if len(batch) < 1000:
            break

        offset += 1000

    return rows


def get_context_rows(timeframe):
    return get_all_rows(
        "btc_market_context",
        {
            "select": "*",
            "timeframe": (
                f"eq.{timeframe}"
            ),
            "order": "timestamp.asc",
        },
    )


def parse_float(value):
    if value is None:
        return None

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        return value

    except (
        TypeError,
        ValueError,
    ):
        return None


def get_all_candles(
    symbol_id,
    timeframe,
):
    rows = get_all_rows(
        "candles",
        {
            "select": (
                "open_time,"
                "close_time,"
                "open,"
                "high,"
                "low,"
                "close,"
                "volume"
            ),
            "symbol_id": (
                f"eq.{symbol_id}"
            ),
            "timeframe": (
                f"eq.{timeframe}"
            ),
            "order": "open_time.asc",
        },
    )

    candles = []

    for row in rows:
        candle = {
            "timeframe": timeframe,
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "open": parse_float(
                row["open"]
            ),
            "high": parse_float(
                row["high"]
            ),
            "low": parse_float(
                row["low"]
            ),
            "close": parse_float(
                row["close"]
            ),
            "volume": parse_float(
                row["volume"]
            ),
        }

        if any(
            candle[key] is None
            for key in [
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ):
            continue

        candles.append(candle)

    return candles


def values_match(
    stored,
    recalculated,
):
    if stored is None and recalculated is None:
        return True

    if stored is None or recalculated is None:
        return False

    try:
        return math.isclose(
            float(stored),
            float(recalculated),
            rel_tol=TOLERANCE,
            abs_tol=TOLERANCE,
        )

    except (
        TypeError,
        ValueError,
    ):
        return False


def select_samples(rows):
    if len(rows) <= SAMPLE_COUNT:
        return rows

    samples = []

    for i in range(SAMPLE_COUNT):
        index = (
            i * (len(rows) - 1)
        ) // (SAMPLE_COUNT - 1)

        samples.append(rows[index])

    return samples


def main():
    print("=" * 70)
    print(
        "BTC MARKET CONTEXT LEAKAGE CHECK - PHASE 2B-1"
    )
    print("=" * 70)

    symbol_id = get_btc_symbol_id()

    failed_timeframes = 0
    total_samples = 0

    for timeframe in TIMEFRAMES:

        print("=" * 60)
        print(
            f"Checking BTC Context Leakage - "
            f"{timeframe}"
        )

        print(
            "Loading stored context..."
        )

        stored_rows = get_context_rows(
            timeframe
        )

        print(
            f"Context rows: "
            f"{len(stored_rows)}"
        )

        if not stored_rows:
            print("STATUS: FAIL")
            print(
                "Reason: no stored "
                "context rows."
            )

            failed_timeframes += 1
            continue

        print(
            "Loading BTC candles..."
        )

        all_candles = get_all_candles(
            symbol_id,
            timeframe,
        )

        print(
            f"BTC candles: "
            f"{len(all_candles)}"
        )

        if not all_candles:
            print("STATUS: FAIL")
            print(
                "Reason: no BTC candles."
            )

            failed_timeframes += 1
            continue

        samples = select_samples(
            stored_rows
        )

        failures = []

        for sample_number, stored in enumerate(
            samples,
            start=1,
        ):
            timestamp = stored[
                "timestamp"
            ]

            print(
                f"  Sample "
                f"{sample_number}/"
                f"{len(samples)}: "
                f"{timestamp}"
            )

            historical_candles = []

            for candle in all_candles:
                if (
                    candle["close_time"]
                    <= timestamp
                ):
                    historical_candles.append(
                        candle
                    )
                else:
                    break

            if not historical_candles:
                failures.append(
                    f"{timestamp}: "
                    f"no historical candles"
                )
                continue

            recalculated_rows = (
                calculate_context(
                    historical_candles
                )
            )

            recalculated = None

            for row in reversed(
                recalculated_rows
            ):
                if (
                    row["timestamp"]
                    == timestamp
                ):
                    recalculated = row
                    break

            if recalculated is None:
                failures.append(
                    f"{timestamp}: "
                    f"recalculated context "
                    f"not found"
                )
                continue

            for field in CHECK_FIELDS:

                stored_value = stored.get(
                    field
                )

                recalculated_value = (
                    recalculated.get(field)
                )

                if not values_match(
                    stored_value,
                    recalculated_value,
                ):
                    failures.append(
                        f"{timestamp} "
                        f"{field}: "
                        f"stored="
                        f"{stored_value}, "
                        f"recalculated="
                        f"{recalculated_value}"
                    )

        total_samples += len(samples)

        if failures:

            print("FAILURES:")

            for failure in failures[:20]:
                print(
                    f"  {failure}"
                )

            if len(failures) > 20:
                print(
                    f"  ... and "
                    f"{len(failures) - 20} "
                    f"more"
                )

            print(
                "STATUS: FAIL"
            )

            failed_timeframes += 1

        else:
            print(
                f"Samples checked: "
                f"{len(samples)}"
            )

            print(
                "STATUS: PASS"
            )

    print("=" * 70)

    print(
        f"Total samples checked: "
        f"{total_samples}"
    )

    print(
        f"Failed timeframes: "
        f"{failed_timeframes}"
    )

    print("=" * 70)

    if failed_timeframes == 0:
        print(
            "STATUS: PASS"
        )
    else:
        print(
            "STATUS: FAIL"
        )


if __name__ == "__main__":
    main()
