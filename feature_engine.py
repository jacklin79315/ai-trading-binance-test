import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone


SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def supabase_get(path, params=None):
    if params:
        path += "?" + urllib.parse.urlencode(params, doseq=True)

    url = SUPABASE_URL + "/rest/v1/" + path

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def supabase_post(path, rows):
    if not rows:
        return []

    url = SUPABASE_URL + "/rest/v1/" + path

    body = json.dumps(rows).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation,resolution=ignore-duplicates",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read().decode("utf-8")

        if not raw:
            return []

        return json.loads(raw)


def parse_time(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    return datetime.fromisoformat(value)


def now_utc():
    return datetime.now(timezone.utc)


def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        return value
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------
# Basic calculations
# ---------------------------------------------------------

def sma(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]

        if any(v is None for v in window):
            continue

        result[i] = sum(window) / period

    return result


def ema(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    # Standard SMA seed
    first_window = values[:period]

    if any(v is None for v in first_window):
        return result

    current = sum(first_window) / period
    result[period - 1] = current

    multiplier = 2.0 / (period + 1)

    for i in range(period, len(values)):
        value = values[i]

        if value is None:
            continue

        current = (value - current) * multiplier + current
        result[i] = current

    return result


def wilder_rsi(closes, period):
    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change > 0:
            gains[i] = change
        else:
            losses[i] = -change

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(closes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def true_ranges(highs, lows, closes):
    result = [None] * len(closes)

    if not closes:
        return result

    result[0] = highs[0] - lows[0]

    for i in range(1, len(closes)):
        result[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    return result


def wilder_atr(highs, lows, closes, period):
    tr = true_ranges(highs, lows, closes)
    result = [None] * len(closes)

    if len(closes) <= period:
        return result

    first_window = tr[1:period + 1]

    if any(v is None for v in first_window):
        return result

    current = sum(first_window) / period
    result[period] = current

    for i in range(period + 1, len(closes)):
        current = ((current * (period - 1)) + tr[i]) / period
        result[i] = current

    return result


def percent_return(closes, lookback):
    result = [None] * len(closes)

    for i in range(lookback, len(closes)):
        previous = closes[i - lookback]

        if previous == 0:
            continue

        result[i] = closes[i] / previous - 1.0

    return result


def bollinger(closes, period=20, std_multiplier=2.0):
    middle = sma(closes, period)

    upper = [None] * len(closes)
    lower = [None] * len(closes)
    width = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]

        if any(v is None for v in window):
            continue

        mean = middle[i]

        variance = sum(
            (v - mean) ** 2 for v in window
        ) / period

        std = math.sqrt(variance)

        upper[i] = mean + std_multiplier * std
        lower[i] = mean - std_multiplier * std

        if mean != 0:
            width[i] = (upper[i] - lower[i]) / mean

    return upper, middle, lower, width


# ---------------------------------------------------------
# Feature calculation
# ---------------------------------------------------------

def calculate_features(candles):
    candles = sorted(
        candles,
        key=lambda x: parse_time(x["close_time"])
    )

    opens = [safe_float(x["open"]) for x in candles]
    highs = [safe_float(x["high"]) for x in candles]
    lows = [safe_float(x["low"]) for x in candles]
    closes = [safe_float(x["close"]) for x in candles]
    volumes = [safe_float(x["volume"]) for x in candles]

    # -----------------------------
    # Returns
    # -----------------------------

    returns = {
        1: percent_return(closes, 1),
        3: percent_return(closes, 3),
        5: percent_return(closes, 5),
        10: percent_return(closes, 10),
    }

    # -----------------------------
    # Moving averages
    # -----------------------------

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma100 = sma(closes, 100)
    sma200 = sma(closes, 200)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema100 = ema(closes, 100)
    ema200 = ema(closes, 200)

    # -----------------------------
    # RSI
    # -----------------------------

    rsi6 = wilder_rsi(closes, 6)
    rsi12 = wilder_rsi(closes, 12)
    rsi24 = wilder_rsi(closes, 24)

    # -----------------------------
    # MACD
    # -----------------------------

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    macd = [None] * len(closes)

    for i in range(len(closes)):
        if ema12[i] is not None and ema26[i] is not None:
            macd[i] = ema12[i] - ema26[i]

    valid_macd_values = [
        x for x in macd
        if x is not None
    ]

    macd_signal_temp = ema(valid_macd_values, 9)

    macd_signal = [None] * len(closes)

    valid_index = 0

    for i in range(len(closes)):
        if macd[i] is not None:
            if valid_index < len(macd_signal_temp):
                macd_signal[i] = macd_signal_temp[valid_index]

            valid_index += 1

    macd_histogram = [None] * len(closes)

    for i in range(len(closes)):
        if macd[i] is not None and macd_signal[i] is not None:
            macd_histogram[i] = macd[i] - macd_signal[i]

    # -----------------------------
    # ATR
    # -----------------------------

    atr = wilder_atr(
        highs,
        lows,
        closes,
        14
    )

    atr_percent = [None] * len(closes)

    for i in range(len(closes)):
        if atr[i] is not None and closes[i] != 0:
            atr_percent[i] = atr[i] / closes[i]

    # -----------------------------
    # Bollinger Bands
    # -----------------------------

    (
        bollinger_upper,
        bollinger_middle,
        bollinger_lower,
        bollinger_width,
    ) = bollinger(closes, 20, 2.0)

    # -----------------------------
    # Volume
    # -----------------------------

    volume_ma = sma(volumes, 20)

    volume_ratio = [None] * len(closes)

    for i in range(len(closes)):
        if volume_ma[i] is not None and volume_ma[i] != 0:
            volume_ratio[i] = volumes[i] / volume_ma[i]

    # -----------------------------
    # Build rows
    # -----------------------------

    feature_rows = []

    for i, candle in enumerate(candles):

        open_price = opens[i]
        high_price = highs[i]
        low_price = lows[i]
        close_price = closes[i]

        candle_body = None
        upper_wick = None
        lower_wick = None

        if (
            open_price is not None
            and high_price is not None
            and low_price is not None
            and close_price is not None
        ):
            candle_body = abs(close_price - open_price)

            upper_wick = (
                high_price
                - max(open_price, close_price)
            )

            lower_wick = (
                min(open_price, close_price)
                - low_price
            )

        row = {
            "symbol_id": candle["symbol_id"],
            "timeframe": candle["timeframe"],
            "timestamp": candle["close_time"],
            "price": close_price,

            # Returns
            "return_1": returns[1][i],
            "return_3": returns[3][i],
            "return_5": returns[5][i],
            "return_10": returns[10][i],

            # SMA
            "sma_20": sma20[i],
            "sma_50": sma50[i],
            "sma_100": sma100[i],
            "sma_200": sma200[i],

            # EMA
            "ema_20": ema20[i],
            "ema_50": ema50[i],
            "ema_100": ema100[i],
            "ema_200": ema200[i],

            # RSI
            "rsi_6": rsi6[i],
            "rsi_12": rsi12[i],
            "rsi_24": rsi24[i],

            # MACD
            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram": macd_histogram[i],

            # ATR
            "atr": atr[i],
            "atr_percent": atr_percent[i],

            # Bollinger
            "bollinger_upper": bollinger_upper[i],
            "bollinger_middle": bollinger_middle[i],
            "bollinger_lower": bollinger_lower[i],
            "bollinger_width": bollinger_width[i],

            # Volume
            "volume": volumes[i],
            "volume_ma": volume_ma[i],
            "volume_ratio": volume_ratio[i],

            # Candle structure
            "candle_body": candle_body,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,

            # Not implemented yet
            "support_price": None,
            "resistance_price": None,
            "distance_to_support": None,
            "distance_to_resistance": None,
            "funding_rate": None,
            "funding_rate_change": None,
            "open_interest": None,
            "open_interest_change": None,
            "basis": None,
            "btc_return": None,
            "btc_rsi": None,
            "btc_atr_percent": None,
            "btc_volume_ratio": None,
            "market_regime": None,
        }

        feature_rows.append(row)

    return feature_rows


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

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

    symbols = supabase_get(
        "symbols",
        {
            "exchange": "eq.binance",
            "market_type": "eq.spot",
            "status": "eq.TRADING",
            "select": "id,symbol",
            "order": "symbol.asc",
        },
    )

    print(
        "Active symbols:",
        len(symbols)
    )

    total_new_features = 0

    for symbol in symbols:

        symbol_id = symbol["id"]
        symbol_name = symbol["symbol"]

        print("====================================")
        print(f"SYMBOL: {symbol_name}")
        print("====================================")

        for timeframe in TIMEFRAMES:

            print("------------------------------------")
            print(f"{symbol_name} - {timeframe}")

            candles = supabase_get(
                "candles",
                {
                    "symbol_id": f"eq.{symbol_id}",
                    "timeframe": f"eq.{timeframe}",
                    "select": "*",
                    "order": "close_time.asc",
                    "limit": "1000",
                },
            )

            print(
                "Candles loaded:",
                len(candles)
            )

            # -------------------------------------------------
            # Only use candles that are fully closed.
            # -------------------------------------------------

            current_time = now_utc()

            closed_candles = []

            for candle in candles:

                close_time = parse_time(
                    candle["close_time"]
                )

                if close_time <= current_time:
                    closed_candles.append(candle)

            print(
                "Closed candles:",
                len(closed_candles)
            )

            if not closed_candles:
                print("No closed candles.")
                continue

            # -------------------------------------------------
            # Existing features
            # -------------------------------------------------

            existing = supabase_get(
                "features",
                {
                    "symbol_id": f"eq.{symbol_id}",
                    "timeframe": f"eq.{timeframe}",
                    "select": "timestamp",
                    "limit": "5000",
                },
            )

            existing_timestamps = {
                item["timestamp"]
                for item in existing
            }

            print(
                "Existing features:",
                len(existing_timestamps)
            )

            # -------------------------------------------------
            # Calculate features for the complete available
            # closed-candle window.
            # -------------------------------------------------

            calculated_rows = calculate_features(
                closed_candles
            )

            new_rows = [
                row
                for row in calculated_rows
                if row["timestamp"]
                not in existing_timestamps
            ]

            print(
                "New features:",
                len(new_rows)
            )

            if not new_rows:
                print("No new features.")
                continue

            # -------------------------------------------------
            # Insert in batches
            # -------------------------------------------------

            inserted_count = 0

            batch_size = 500

            for start in range(
                0,
                len(new_rows),
                batch_size
            ):

                batch = new_rows[
                    start:start + batch_size
                ]

                inserted = supabase_post(
                    "features",
                    batch
                )

                inserted_count += len(inserted)

            print(
                "Inserted features:",
                inserted_count
            )

            total_new_features += inserted_count

        print(
            f"{symbol_name} total new features:",
            total_new_features
        )

    print("====================================")
    print("Feature generation completed.")
    print("====================================")


if __name__ == "__main__":
    main()
