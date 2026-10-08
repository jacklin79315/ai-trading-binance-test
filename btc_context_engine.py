import os
import math
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

BTC_SYMBOL = "BTCUSDT"

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

FORCE_HISTORICAL_BACKFILL = True

BATCH_SIZE = 500


# ============================================================
# Supabase
# ============================================================

def supabase_request(
    method,
    table,
    params=None,
    payload=None,
    prefer=None,
):
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL is not set")

    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_KEY is not set")

    url = (
        SUPABASE_URL.rstrip("/")
        + "/rest/v1/"
        + table
    )

    if params:
        query = urllib.parse.urlencode(
            params,
            doseq=True,
        )
        url += "?" + query

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method=method,
    )

    request.add_header(
        "apikey",
        SUPABASE_KEY,
    )

    request.add_header(
        "Authorization",
        "Bearer " + SUPABASE_KEY,
    )

    request.add_header(
        "Content-Type",
        "application/json",
    )

    if prefer:
        request.add_header(
            "Prefer",
            prefer,
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


# ============================================================
# Helpers
# ============================================================

def is_finite(value):
    return (
        value is not None
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def safe_divide(a, b):
    if (
        not is_finite(a)
        or not is_finite(b)
        or b == 0
    ):
        return None

    return a / b


def parse_float(value):
    if value is None:
        return None

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        return value

    except (TypeError, ValueError):
        return None


# ============================================================
# Candle loading
# ============================================================

def get_all_candles(
    timeframe,
):
    rows = []

    offset = 0

    while True:

        params = {
            "select": (
                "open_time,"
                "close_time,"
                "open,"
                "high,"
                "low,"
                "close,"
                "volume"
            ),
            "symbol_id": "eq." + get_btc_symbol_id(),
            "timeframe": "eq." + timeframe,
            "order": "open_time.asc",
            "limit": "1000",
            "offset": str(offset),
        }

        batch = supabase_request(
            "GET",
            "candles",
            params=params,
        )

        if not batch:
            break

        rows.extend(batch)

        if len(batch) < 1000:
            break

        offset += 1000

    return rows


def get_btc_symbol_id():
    params = {
        "select": "id",
        "symbol": "eq." + BTC_SYMBOL,
        "market_type": "eq.spot",
        "limit": "1",
    }

    rows = supabase_request(
        "GET",
        "symbols",
        params=params,
    )

    if not rows:
        raise RuntimeError(
            "BTCUSDT spot symbol not found"
        )

    return rows[0]["id"]


# ============================================================
# Closed candles
# ============================================================

def filter_closed_candles(
    candles,
):
    now = datetime.now(
        timezone.utc
    )

    result = []

    for candle in candles:

        close_time = candle.get(
            "close_time"
        )

        if not close_time:
            continue

        try:
            close_dt = datetime.fromisoformat(
                close_time.replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError:
            continue

        if close_dt <= now:
            result.append(candle)

    return result


# ============================================================
# Indicator functions
# ============================================================

def rolling_mean(
    values,
    period,
):
    result = [None] * len(values)

    if len(values) < period:
        return result

    running_sum = 0.0

    for i, value in enumerate(values):

        if value is None:
            continue

        running_sum += value

        if i >= period:

            old = values[i - period]

            if old is not None:
                running_sum -= old

        if i >= period - 1:

            window = values[
                i - period + 1:
                i + 1
            ]

            if all(
                value is not None
                for value in window
            ):
                result[i] = (
                    sum(window)
                    / period
                )

    return result


def ema_series(
    values,
    period,
):
    result = [None] * len(values)

    if len(values) < period:
        return result

    first_window = values[:period]

    if any(
        value is None
        for value in first_window
    ):
        return result

    ema = (
        sum(first_window)
        / period
    )

    result[period - 1] = ema

    multiplier = (
        2.0 / (period + 1)
    )

    for i in range(
        period,
        len(values),
    ):

        value = values[i]

        if value is None:
            continue

        ema = (
            value * multiplier
            + ema * (1 - multiplier)
        )

        result[i] = ema

    return result


def rsi_series(
    closes,
    period,
):
    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    gains = []
    losses = []

    for i in range(
        1,
        len(closes),
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        gains.append(
            max(change, 0.0)
        )

        losses.append(
            max(-change, 0.0)
        )

    if len(gains) < period:
        return result

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    index = period

    if avg_loss == 0:
        result[index] = 100.0
    else:
        rs = (
            avg_gain
            / avg_loss
        )

        result[index] = (
            100.0
            - 100.0 / (1.0 + rs)
        )

    for i in range(
        period,
        len(gains),
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

        result_index = i + 1

        if avg_loss == 0:
            result[result_index] = 100.0
        else:
            rs = (
                avg_gain
                / avg_loss
            )

            result[result_index] = (
                100.0
                - 100.0 / (1.0 + rs)
            )

    return result


def true_range_series(
    candles,
):
    result = []

    previous_close = None

    for candle in candles:

        high = candle["high"]
        low = candle["low"]

        if (
            high is None
            or low is None
        ):
            result.append(None)

            previous_close = candle[
                "close"
            ]

            continue

        if previous_close is None:

            true_range = (
                high - low
            )

        else:

            true_range = max(
                high - low,
                abs(
                    high
                    - previous_close
                ),
                abs(
                    low
                    - previous_close
                ),
            )

        result.append(
            true_range
        )

        previous_close = candle[
            "close"
        ]

    return result


def atr_series(
    candles,
    period=14,
):
    true_ranges = (
        true_range_series(
            candles
        )
    )

    result = [
        None
    ] * len(true_ranges)

    if len(true_ranges) < period:
        return result

    first_window = (
        true_ranges[:period]
    )

    if any(
        value is None
        for value in first_window
    ):
        return result

    atr = (
        sum(first_window)
        / period
    )

    result[period - 1] = atr

    for i in range(
        period,
        len(true_ranges),
    ):

        value = true_ranges[i]

        if value is None:
            continue

        atr = (
            (
                atr * (period - 1)
            )
            + value
        ) / period

        result[i] = atr

    return result


# ============================================================
# BTC Context calculation
# ============================================================

def calculate_context(
    candles,
):
    closes = [
        candle["close"]
        for candle in candles
    ]

    volumes = [
        candle["volume"]
        for candle in candles
    ]

    sma20 = rolling_mean(
        closes,
        20,
    )

    sma50 = rolling_mean(
        closes,
        50,
    )

    sma200 = rolling_mean(
        closes,
        200,
    )

    rsi6 = rsi_series(
        closes,
        6,
    )

    rsi12 = rsi_series(
        closes,
        12,
    )

    rsi24 = rsi_series(
        closes,
        24,
    )

    atr = atr_series(
        candles,
        14,
    )

    volume_ma20 = rolling_mean(
        volumes,
        20,
    )

    result = []

    for i, candle in enumerate(
        candles
    ):

        close = candle["close"]

        def return_n(period):
            if i < period:
                return None

            previous = closes[
                i - period
            ]

            if previous == 0:
                return None

            return (
                close / previous
            ) - 1.0

        btc_atr = atr[i]

        btc_atr_percent = safe_divide(
            btc_atr,
            close,
        )

        volume_ratio = safe_divide(
            volumes[i],
            volume_ma20[i],
        )

        price_sma20_ratio = (
            safe_divide(
                close,
                sma20[i],
            )
        )

        price_sma50_ratio = (
            safe_divide(
                close,
                sma50[i],
            )
        )

        price_sma200_ratio = (
            safe_divide(
                close,
                sma200[i],
            )
        )

        sma20_slope = None

        if (
            i >= 5
            and sma20[i] is not None
            and sma20[i - 5] is not None
            and sma20[i - 5] != 0
        ):
            sma20_slope = (
                sma20[i]
                / sma20[i - 5]
            ) - 1.0

        sma50_slope = None

        if (
            i >= 5
            and sma50[i] is not None
            and sma50[i - 5] is not None
            and sma50[i - 5] != 0
        ):
            sma50_slope = (
                sma50[i]
                / sma50[i - 5]
            ) - 1.0

        sma200_slope = None

        if (
            i >= 5
            and sma200[i] is not None
            and sma200[i - 5] is not None
            and sma200[i - 5] != 0
        ):
            sma200_slope = (
                sma200[i]
                / sma200[i - 5]
            ) - 1.0

        trend_alignment_score = None

        if (
            price_sma20_ratio is not None
            and price_sma50_ratio is not None
            and price_sma200_ratio is not None
        ):

            score = 0

            if price_sma20_ratio > 1:
                score += 1
            elif price_sma20_ratio < 1:
                score -= 1

            if price_sma50_ratio > 1:
                score += 1
            elif price_sma50_ratio < 1:
                score -= 1

            if price_sma200_ratio > 1:
                score += 1
            elif price_sma200_ratio < 1:
                score -= 1

            trend_alignment_score = score

        result.append({
            "timeframe": candle[
                "timeframe"
            ],
            "timestamp": candle[
                "close_time"
            ],

            "btc_price": close,

            "btc_return_1": return_n(1),
            "btc_return_3": return_n(3),
            "btc_return_5": return_n(5),
            "btc_return_10": return_n(10),

            "btc_rsi_6": rsi6[i],
            "btc_rsi_12": rsi12[i],
            "btc_rsi_24": rsi24[i],

            "btc_atr": btc_atr,
            "btc_atr_percent": btc_atr_percent,

            "btc_volume": volumes[i],
            "btc_volume_ratio": volume_ratio,

            "btc_price_sma20_ratio":
                price_sma20_ratio,

            "btc_price_sma50_ratio":
                price_sma50_ratio,

            "btc_price_sma200_ratio":
                price_sma200_ratio,

            "btc_sma20_slope":
                sma20_slope,

            "btc_sma50_slope":
                sma50_slope,

            "btc_sma200_slope":
                sma200_slope,

            "btc_trend_alignment_score":
                trend_alignment_score,
        })

    return result


# ============================================================
# Database write
# ============================================================

def upsert_rows(
    rows,
):
    if not rows:
        return 0

    written = 0

    for start in range(
        0,
        len(rows),
        BATCH_SIZE,
    ):

        batch = rows[
            start:
            start + BATCH_SIZE
        ]

        supabase_request(
            "POST",
            "btc_market_context",
            params={
                "on_conflict":
                    "timeframe,timestamp"
            },
            payload=batch,
            prefer=(
                "resolution=merge-duplicates,"
                "return=minimal"
            ),
        )

        written += len(batch)

    return written


# ============================================================
# Process
# ============================================================

def process_timeframe(
    timeframe,
):
    print(
        "============================================================"
    )

    print(
        f"BTC Context - {timeframe}"
    )

    rows = get_all_candles(
        timeframe
    )

    print(
        f"Candles loaded: {len(rows)}"
    )

    if not rows:
        print("No candles found.")
        return 0

    candles = []

    for row in rows:

        candle = {
            "timeframe": timeframe,
            "open_time": row[
                "open_time"
            ],
            "close_time": row[
                "close_time"
            ],
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

        candles.append(
            candle
        )

    candles = filter_closed_candles(
        candles
    )

    print(
        f"Closed candles: {len(candles)}"
    )

    if not candles:
        return 0

    context_rows = calculate_context(
        candles
    )

    if not FORCE_HISTORICAL_BACKFILL:

        existing = supabase_request(
            "GET",
            "btc_market_context",
            params={
                "select": "timestamp",
                "timeframe":
                    "eq." + timeframe,
                "order":
                    "timestamp.desc",
                "limit": "1",
            },
        )

        if existing:

            latest_timestamp = (
                existing[0]["timestamp"]
            )

            context_rows = [
                row
                for row in context_rows
                if row["timestamp"]
                > latest_timestamp
            ]

    written = upsert_rows(
        context_rows
    )

    print(
        f"Written: {written}"
    )

    return written


# ============================================================
# Main
# ============================================================

def main():

    print(
        "======================================================================"
    )

    print(
        "BTC MARKET CONTEXT ENGINE - PHASE 2B-1"
    )

    print(
        "======================================================================"
    )

    total_written = 0

    failed = 0

    for timeframe in TIMEFRAMES:

        try:

            written = process_timeframe(
                timeframe
            )

            total_written += written

        except Exception as exc:

            failed += 1

            print(
                f"ERROR {timeframe}: {exc}"
            )

    print(
        "======================================================================"
    )

    print(
        "BTC MARKET CONTEXT COMPLETE"
    )

    print(
        f"Total written: {total_written}"
    )

    print(
        f"Failed timeframes: {failed}"
    )

    print(
        "======================================================================"
    )

    if failed == 0:
        print(
            "STATUS: PASS"
        )
    else:
        print(
            "STATUS: FAIL"
        )


if __name__ == "__main__":
    main()
