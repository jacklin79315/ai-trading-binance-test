import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

BTC_SYMBOL = "BTCUSDT"

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

# 每個 timeframe 抽查幾個歷史時間點
SAMPLE_COUNT = 10

TOLERANCE = 1e-9


def supabase_get(table, params):
    query = urllib.parse.urlencode(params, doseq=True)

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

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


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
            "BTCUSDT symbol not found in symbols table."
        )

    # 優先尋找 SPOT；若資料庫使用不同大小寫，
    # 仍可正確找到 BTCUSDT 的現貨 symbol。
    for row in rows:
        market_type = str(row.get("market_type", "")).upper()

        if market_type == "SPOT":
            return row["id"]

    # 如果沒有 SPOT，輸出實際資料，方便診斷
    print("BTCUSDT found, but no SPOT market_type matched.")
    print("Available rows:")

    for row in rows:
        print(row)

    raise RuntimeError(
        "BTCUSDT SPOT symbol not found. "
        "See rows above for actual market_type."
    )

def get_context_rows(timeframe):
    return supabase_get(
        "btc_market_context",
        {
            "select": "*",
            "timeframe": f"eq.{timeframe}",
            "order": "timestamp.asc",
            "limit": "1000",
        },
    )


def get_candles(symbol_id, timeframe, end_timestamp):
    rows = []

    offset = 0

    while True:
        batch = supabase_get(
            "candles",
            {
                "select": "open_time,close_time,open,high,low,close,volume",
                "symbol_id": f"eq.{symbol_id}",
                "timeframe": f"eq.{timeframe}",
                "close_time": f"lte.{end_timestamp}",
                "order": "open_time.asc",
                "limit": "1000",
                "offset": str(offset),
            },
        )

        if not batch:
            break

        rows.extend(batch)

        if len(batch) < 1000:
            break

        offset += 1000

    return rows


def parse_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_divide(a, b):
    if a is None or b is None or b == 0:
        return None

    return a / b


def rolling_mean(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    window_sum = 0.0
    valid_count = 0

    for i, value in enumerate(values):
        if value is not None:
            window_sum += value
            valid_count += 1

        if i >= period:
            old = values[i - period]

            if old is not None:
                window_sum -= old
                valid_count -= 1

        if i >= period - 1 and valid_count == period:
            result[i] = window_sum / period

    return result


def ema_series(values, period):
    result = [None] * len(values)

    valid_values = []

    for i, value in enumerate(values):
        if value is not None:
            valid_values.append((i, value))

    if len(valid_values) < period:
        return result

    seed_index = valid_values[period - 1][0]

    seed_values = [
        value for _, value in valid_values[:period]
    ]

    ema = sum(seed_values) / period
    result[seed_index] = ema

    multiplier = 2 / (period + 1)

    for i in range(seed_index + 1, len(values)):
        value = values[i]

        if value is None:
            continue

        ema = ((value - ema) * multiplier) + ema
        result[i] = ema

    return result


def rsi_series(values, period):
    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = [None] * len(values)
    losses = [None] * len(values)

    for i in range(1, len(values)):
        if values[i] is None or values[i - 1] is None:
            continue

        change = values[i] - values[i - 1]

        gains[i] = max(change, 0)
        losses[i] = max(-change, 0)

    first_gains = gains[1:period + 1]
    first_losses = losses[1:period + 1]

    if any(x is None for x in first_gains + first_losses):
        return result

    avg_gain = sum(first_gains) / period
    avg_loss = sum(first_losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period + 1, len(values)):
        if gains[i] is None or losses[i] is None:
            continue

        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))

    return result


def true_range_series(candles):
    result = [None] * len(candles)

    for i, candle in enumerate(candles):
        high = parse_float(candle["high"])
        low = parse_float(candle["low"])

        if high is None or low is None:
            continue

        if i == 0:
            result[i] = high - low
            continue

        previous_close = parse_float(candles[i - 1]["close"])

        if previous_close is None:
            continue

        result[i] = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

    return result


def atr_series(candles, period=14):
    true_ranges = true_range_series(candles)

    result = [None] * len(true_ranges)

    if len(true_ranges) < period:
        return result

    first_window = true_ranges[:period]

    if any(value is None for value in first_window):
        return result

    atr = sum(first_window) / period
    result[period - 1] = atr

    for i in range(period, len(true_ranges)):
        value = true_ranges[i]

        if value is None:
            continue

        atr = ((atr * (period - 1)) + value) / period
        result[i] = atr

    return result


def calculate_context(candles):
    closes = [parse_float(c["close"]) for c in candles]
    volumes = [parse_float(c["volume"]) for c in candles]

    result = []

    returns = {}

    for period in [1, 3, 5, 10]:
        series = [None] * len(closes)

        for i in range(period, len(closes)):
            if closes[i] is None or closes[i - period] is None:
                continue

            series[i] = safe_divide(
                closes[i] - closes[i - period],
                closes[i - period],
            )

        returns[period] = series

    rsi6 = rsi_series(closes, 6)
    rsi12 = rsi_series(closes, 12)
    rsi24 = rsi_series(closes, 24)

    atr = atr_series(candles, 14)

    atr_percent = [None] * len(closes)

    for i in range(len(closes)):
        if atr[i] is not None and closes[i] not in (None, 0):
            atr_percent[i] = atr[i] / closes[i]

    volume_ma20 = rolling_mean(volumes, 20)

    volume_ratio = [None] * len(volumes)

    for i in range(len(volumes)):
        if volumes[i] is not None and volume_ma20[i] not in (None, 0):
            volume_ratio[i] = volumes[i] / volume_ma20[i]

    sma20 = rolling_mean(closes, 20)
    sma50 = rolling_mean(closes, 50)
    sma200 = rolling_mean(closes, 200)

    price_sma20_ratio = [
        safe_divide(closes[i], sma20[i])
        for i in range(len(closes))
    ]

    price_sma50_ratio = [
        safe_divide(closes[i], sma50[i])
        for i in range(len(closes))
    ]

    price_sma200_ratio = [
        safe_divide(closes[i], sma200[i])
        for i in range(len(closes))
    ]

    sma20_slope = [None] * len(closes)
sma50_slope = [None] * len(closes)
sma200_slope = [None] * len(closes)

for i in range(5, len(closes)):
    if (
        sma20[i] is not None
        and sma20[i - 5] is not None
        and sma20[i - 5] != 0
    ):
        sma20_slope[i] = (
            sma20[i] / sma20[i - 5]
        ) - 1.0

    if (
        sma50[i] is not None
        and sma50[i - 5] is not None
        and sma50[i - 5] != 0
    ):
        sma50_slope[i] = (
            sma50[i] / sma50[i - 5]
        ) - 1.0

    if (
        sma200[i] is not None
        and sma200[i - 5] is not None
        and sma200[i - 5] != 0
    ):
        sma200_slope[i] = (
            sma200[i] / sma200[i - 5]
        ) - 1.0

    for i, candle in enumerate(candles):
        trend_alignment_score = None

        if (
            price_sma20_ratio[i] is not None
            and price_sma50_ratio[i] is not None
            and price_sma200_ratio[i] is not None
        ):
            score = 0

            if price_sma20_ratio[i] > 1:
                score += 1
            elif price_sma20_ratio[i] < 1:
                score -= 1

            if price_sma50_ratio[i] > 1:
                score += 1
            elif price_sma50_ratio[i] < 1:
                score -= 1

            if price_sma200_ratio[i] > 1:
                score += 1
            elif price_sma200_ratio[i] < 1:
                score -= 1

            trend_alignment_score = score

        result.append(
            {
                "timestamp": candle["close_time"],
                "btc_price": closes[i],
                "btc_return_1": returns[1][i],
                "btc_return_3": returns[3][i],
                "btc_return_5": returns[5][i],
                "btc_return_10": returns[10][i],
                "btc_rsi_6": rsi6[i],
                "btc_rsi_12": rsi12[i],
                "btc_rsi_24": rsi24[i],
                "btc_atr": atr[i],
                "btc_atr_percent": atr_percent[i],
                "btc_volume": volumes[i],
                "btc_volume_ratio": volume_ratio[i],
                "btc_price_sma20_ratio": price_sma20_ratio[i],
                "btc_price_sma50_ratio": price_sma50_ratio[i],
                "btc_price_sma200_ratio": price_sma200_ratio[i],
                "btc_sma20_slope": sma20_slope[i],
                "btc_sma50_slope": sma50_slope[i],
                "btc_sma200_slope": sma200_slope[i],
                "btc_trend_alignment_score": trend_alignment_score,
            }
        )

    return result


def values_match(a, b):
    if a is None and b is None:
        return True

    if a is None or b is None:
        return False

    try:
        return math.isclose(
            float(a),
            float(b),
            rel_tol=TOLERANCE,
            abs_tol=TOLERANCE,
        )
    except (TypeError, ValueError):
        return False


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


def main():
    print("=" * 70)
    print("BTC MARKET CONTEXT LEAKAGE CHECK - PHASE 2B-1")
    print("=" * 70)

    symbol_id = get_btc_symbol_id()

    failed_timeframes = 0
    total_checked = 0

    for timeframe in TIMEFRAMES:
        print("=" * 60)
        print(f"Checking BTC Context Leakage - {timeframe}")

        stored_rows = get_context_rows(timeframe)

        if not stored_rows:
            print("STATUS: FAIL")
            print("Reason: no stored context rows.")
            failed_timeframes += 1
            continue

        # 均勻抽樣歷史時間點
        if len(stored_rows) <= SAMPLE_COUNT:
            samples = stored_rows
        else:
            step = len(stored_rows) // SAMPLE_COUNT
            samples = [
                stored_rows[i]
                for i in range(0, len(stored_rows), step)
            ][:SAMPLE_COUNT]

        failures = []

        for stored in samples:
            timestamp = stored["timestamp"]

            candles = get_candles(
                symbol_id,
                timeframe,
                timestamp,
            )

            # candle close_time 必須剛好包含該 context timestamp
            candles = [
                candle
                for candle in candles
                if candle["close_time"] <= timestamp
            ]

            if not candles:
                failures.append(
                    f"{timestamp}: no historical candles found"
                )
                continue

            recalculated_rows = calculate_context(candles)

            recalculated = None

            for row in reversed(recalculated_rows):
                if row["timestamp"] == timestamp:
                    recalculated = row
                    break

            if recalculated is None:
                failures.append(
                    f"{timestamp}: recalculated context not found"
                )
                continue

            for field in CHECK_FIELDS:
                stored_value = stored.get(field)
                recalculated_value = recalculated.get(field)

                if not values_match(
                    stored_value,
                    recalculated_value,
                ):
                    failures.append(
                        f"{timestamp} {field}: "
                        f"stored={stored_value}, "
                        f"recalculated={recalculated_value}"
                    )

        total_checked += len(samples)

        if failures:
            print(f"Samples checked: {len(samples)}")
            print("FAILURES:")

            for failure in failures[:20]:
                print(f"  {failure}")

            if len(failures) > 20:
                print(
                    f"  ... and {len(failures) - 20} more"
                )

            print("STATUS: FAIL")
            failed_timeframes += 1

        else:
            print(f"Samples checked: {len(samples)}")
            print("STATUS: PASS")

    print("=" * 70)
    print(f"Total samples checked: {total_checked}")
    print(f"Failed timeframes: {failed_timeframes}")
    print("=" * 70)

    if failed_timeframes == 0:
        print("STATUS: PASS")
    else:
        print("STATUS: FAIL")


if __name__ == "__main__":
    main()
