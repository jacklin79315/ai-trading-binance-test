import os
import math
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

# 每批寫入筆數
BATCH_SIZE = 500


# =========================================================
# Supabase GET
# =========================================================

def supabase_get(table, params=None):

    url = f"{SUPABASE_URL}/rest/v1/{table}"

    if params:
        url += "?" + urllib.parse.urlencode(
            params,
            doseq=True
        )

    req = urllib.request.Request(
        url,
        headers=HEADERS,
        method="GET",
    )

    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:

        return json.loads(
            response.read().decode()
        )


# =========================================================
# Supabase BATCH UPSERT
# =========================================================

def supabase_batch_upsert(rows):

    if not rows:
        return

    url = (
        f"{SUPABASE_URL}/rest/v1/features"
        "?on_conflict=symbol_id,timeframe,timestamp"
    )

    headers = dict(HEADERS)

    headers["Prefer"] = (
        "resolution=merge-duplicates,"
        "return=minimal"
    )

    req = urllib.request.Request(
        url,
        headers=headers,
        data=json.dumps(rows).encode(),
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=120
    ) as response:

        if response.status not in [200, 201]:
            raise RuntimeError(
                f"Supabase upsert failed: "
                f"HTTP {response.status}"
            )


# =========================================================
# Math helpers
# =========================================================

def sma(values, period):

    result = [None] * len(values)

    if len(values) < period:
        return result

    for i in range(period - 1, len(values)):

        window = values[
            i - period + 1:i + 1
        ]

        if any(v is None for v in window):
            continue

        result[i] = sum(window) / period

    return result


def ema(values, period):

    result = [None] * len(values)

    valid_indices = [
        i for i, v in enumerate(values)
        if v is not None
    ]

    if len(valid_indices) < period:
        return result

    seed_indices = valid_indices[:period]

    if seed_indices[-1] != (
        seed_indices[0] + period - 1
    ):
        return result

    seed = sum(
        values[i]
        for i in seed_indices
    ) / period

    start = seed_indices[-1]

    result[start] = seed

    multiplier = 2 / (period + 1)

    for i in range(
        start + 1,
        len(values)
    ):

        if values[i] is None:
            continue

        result[i] = (
            (values[i] - result[i - 1])
            * multiplier
            + result[i - 1]
        )

    return result


def wilder_rsi(closes, period):

    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)

    for i in range(1, len(closes)):

        change = (
            closes[i] - closes[i - 1]
        )

        gains[i] = max(change, 0)
        losses[i] = max(-change, 0)

    avg_gain = (
        sum(gains[1:period + 1])
        / period
    )

    avg_loss = (
        sum(losses[1:period + 1])
        / period
    )

    if avg_loss == 0:
        result[period] = 100.0
    else:

        rs = avg_gain / avg_loss

        result[period] = (
            100 - 100 / (1 + rs)
        )

    for i in range(
        period + 1,
        len(closes)
    ):

        avg_gain = (
            (
                avg_gain * (period - 1)
                + gains[i]
            )
            / period
        )

        avg_loss = (
            (
                avg_loss * (period - 1)
                + losses[i]
            )
            / period
        )

        if avg_loss == 0:

            result[i] = 100.0

        else:

            rs = avg_gain / avg_loss

            result[i] = (
                100 - 100 / (1 + rs)
            )

    return result


def true_range(
    highs,
    lows,
    closes
):

    tr = [None] * len(closes)

    if not closes:
        return tr

    tr[0] = highs[0] - lows[0]

    for i in range(1, len(closes)):

        tr[i] = max(
            highs[i] - lows[i],

            abs(
                highs[i]
                - closes[i - 1]
            ),

            abs(
                lows[i]
                - closes[i - 1]
            ),
        )

    return tr


def wilder_smoothing(
    values,
    period
):

    result = [None] * len(values)

    valid = [
        i for i, v in enumerate(values)
        if v is not None
    ]

    if len(valid) < period:
        return result

    seed_indices = valid[:period]

    if seed_indices[-1] != (
        seed_indices[0] + period - 1
    ):
        return result

    start = seed_indices[-1]

    current = (
        sum(values[i] for i in seed_indices)
        / period
    )

    result[start] = current

    for i in range(
        start + 1,
        len(values)
    ):

        if values[i] is None:
            continue

        current = (
            current * (period - 1)
            + values[i]
        ) / period

        result[i] = current

    return result


def standard_deviation(values):

    mean = sum(values) / len(values)

    variance = sum(
        (x - mean) ** 2
        for x in values
    ) / len(values)

    return math.sqrt(variance)


# =========================================================
# Feature calculation
# =========================================================

def calculate_features(candles):

    opens = [
        float(x["open"])
        for x in candles
    ]

    highs = [
        float(x["high"])
        for x in candles
    ]

    lows = [
        float(x["low"])
        for x in candles
    ]

    closes = [
        float(x["close"])
        for x in candles
    ]

    volumes = [
        float(x["volume"])
        for x in candles
    ]

    n = len(candles)

    # -----------------------------------------------------
    # Returns
    # -----------------------------------------------------

    returns = {}

    for period in [1, 3, 5, 10]:

        arr = [None] * n

        for i in range(period, n):

            if closes[i - period] != 0:

                arr[i] = (
                    closes[i]
                    / closes[i - period]
                    - 1
                )

        returns[period] = arr

    # -----------------------------------------------------
    # SMA
    # -----------------------------------------------------

    sma_values = {
        p: sma(closes, p)
        for p in [20, 50, 100, 200]
    }

    # -----------------------------------------------------
    # EMA
    # -----------------------------------------------------

    ema_values = {
        p: ema(closes, p)
        for p in [20, 50, 100, 200]
    }

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    rsi_values = {
        p: wilder_rsi(closes, p)
        for p in [6, 12, 24]
    }

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    macd = [None] * n

    for i in range(n):

        if (
            ema12[i] is not None
            and ema26[i] is not None
        ):

            macd[i] = (
                ema12[i] - ema26[i]
            )

    macd_signal = ema(
        macd,
        9
    )

    macd_histogram = [None] * n

    for i in range(n):

        if (
            macd[i] is not None
            and macd_signal[i] is not None
        ):

            macd_histogram[i] = (
                macd[i]
                - macd_signal[i]
            )

    # -----------------------------------------------------
    # ATR
    # -----------------------------------------------------

    tr = true_range(
        highs,
        lows,
        closes
    )

    atr = wilder_smoothing(
        tr,
        14
    )

    atr_percent = [None] * n

    for i in range(n):

        if (
            atr[i] is not None
            and closes[i] != 0
        ):

            atr_percent[i] = (
                atr[i] / closes[i]
            )

    # -----------------------------------------------------
    # Bollinger
    # -----------------------------------------------------

    bb_upper = [None] * n
    bb_middle = [None] * n
    bb_lower = [None] * n
    bb_width = [None] * n

    period = 20

    for i in range(
        period - 1,
        n
    ):

        window = closes[
            i - period + 1:i + 1
        ]

        middle = (
            sum(window)
            / period
        )

        std = standard_deviation(
            window
        )

        upper = (
            middle + 2 * std
        )

        lower = (
            middle - 2 * std
        )

        bb_middle[i] = middle
        bb_upper[i] = upper
        bb_lower[i] = lower

        if middle != 0:

            bb_width[i] = (
                (upper - lower)
                / middle
            )

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    volume_ma = sma(
        volumes,
        20
    )

    volume_ratio = [None] * n

    for i in range(n):

        if (
            volume_ma[i] is not None
            and volume_ma[i] != 0
        ):

            volume_ratio[i] = (
                volumes[i]
                / volume_ma[i]
            )

    # -----------------------------------------------------
    # Candle structure
    # -----------------------------------------------------

    candle_body = [None] * n
    upper_wick = [None] * n
    lower_wick = [None] * n

    for i in range(n):

        candle_body[i] = abs(
            closes[i] - opens[i]
        )

        upper_wick[i] = (
            highs[i]
            - max(
                opens[i],
                closes[i]
            )
        )

        lower_wick[i] = (
            min(
                opens[i],
                closes[i]
            )
            - lows[i]
        )

    # -----------------------------------------------------
    # Build rows
    # -----------------------------------------------------

    result = []

    for i, candle in enumerate(candles):

        row = {
            "symbol_id": candle["symbol_id"],
            "timeframe": candle["timeframe"],
            "timestamp": candle["close_time"],

            "price": closes[i],

            "return_1": returns[1][i],
            "return_3": returns[3][i],
            "return_5": returns[5][i],
            "return_10": returns[10][i],

            "sma_20": sma_values[20][i],
            "sma_50": sma_values[50][i],
            "sma_100": sma_values[100][i],
            "sma_200": sma_values[200][i],

            "ema_20": ema_values[20][i],
            "ema_50": ema_values[50][i],
            "ema_100": ema_values[100][i],
            "ema_200": ema_values[200][i],

            "rsi_6": rsi_values[6][i],
            "rsi_12": rsi_values[12][i],
            "rsi_24": rsi_values[24][i],

            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram": macd_histogram[i],

            "atr": atr[i],
            "atr_percent": atr_percent[i],

            "bollinger_upper": bb_upper[i],
            "bollinger_middle": bb_middle[i],
            "bollinger_lower": bb_lower[i],
            "bollinger_width": bb_width[i],

            "volume": volumes[i],
            "volume_ma": volume_ma[i],
            "volume_ratio": volume_ratio[i],

            "candle_body": candle_body[i],
            "upper_wick": upper_wick[i],
            "lower_wick": lower_wick[i],
        }

        result.append(row)

    return result


# =========================================================
# Main
# =========================================================

def main():

    print("=" * 60)
    print("FEATURE BACKFILL - BATCH VERSION")
    print("=" * 60)

    symbols = supabase_get(
        "symbols",
        {
            "select":
                "id,symbol,exchange,market_type,status",

            "exchange": "eq.binance",
            "market_type": "eq.spot",
            "status": "eq.TRADING",

            "order": "symbol.asc",
        },
    )

    print(
        f"Active symbols: {len(symbols)}"
    )

    total_updated = 0

    for symbol in symbols:

        symbol_id = symbol["id"]
        symbol_name = symbol["symbol"]

        print()
        print("=" * 60)
        print(symbol_name)
        print("=" * 60)

        for timeframe in TIMEFRAMES:

            print()
            print(
                f"{symbol_name} - {timeframe}"
            )

            # -------------------------------------------------
            # Load candles
            # -------------------------------------------------

            candles = supabase_get(
                "candles",
                {
                    "select": "*",

                    "symbol_id":
                        f"eq.{symbol_id}",

                    "timeframe":
                        f"eq.{timeframe}",

                    "order":
                        "open_time.asc",

                    "limit": "1000",
                },
            )

            print(
                f"Candles loaded: "
                f"{len(candles)}"
            )

            if not candles:
                print("No candles. Skip.")
                continue

            # -------------------------------------------------
            # Closed candles only
            # -------------------------------------------------

            now = datetime.now(
                timezone.utc
            )

            closed_candles = []

            for candle in candles:

                close_time = datetime.fromisoformat(
                    candle["close_time"]
                    .replace(
                        "Z",
                        "+00:00"
                    )
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
                    "No closed candles. Skip."
                )
                continue

            # -------------------------------------------------
            # Calculate
            # -------------------------------------------------

            feature_rows = calculate_features(
                closed_candles
            )

            print(
                f"Calculated rows: "
                f"{len(feature_rows)}"
            )

            # -------------------------------------------------
            # Batch upsert
            # -------------------------------------------------

            updated = 0

            for start in range(
                0,
                len(feature_rows),
                BATCH_SIZE
            ):

                batch = feature_rows[
                    start:
                    start + BATCH_SIZE
                ]

                supabase_batch_upsert(
                    batch
                )

                updated += len(batch)

                print(
                    f"Batch updated: "
                    f"{updated}/"
                    f"{len(feature_rows)}"
                )

            print(
                f"Updated rows: {updated}"
            )

            total_updated += updated

    print()
    print("=" * 60)
    print(
        f"TOTAL UPDATED: "
        f"{total_updated}"
    )
    print("=" * 60)

    print(
        "Feature backfill completed."
    )


if __name__ == "__main__":
    main()
