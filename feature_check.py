import os
import urllib.request
import urllib.parse
import json
import math
from datetime import datetime, timezone


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


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
        method="GET"
    )

    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:

        return json.loads(
            response.read().decode()
        )


# =========================================================
# Helpers
# =========================================================

def is_finite(value):

    if value is None:
        return True

    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def parse_time(value):

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def check_monotonic(values):

    previous = None

    for value in values:

        current = parse_time(value)

        if previous is not None:

            if current <= previous:
                return False

        previous = current

    return True


# =========================================================
# Main
# =========================================================

def main():

    print("=" * 70)
    print("FEATURE QUALITY CHECK")
    print("=" * 70)

    symbols = supabase_get(
        "symbols",
        {
            "select": "id,symbol",
            "exchange": "eq.binance",
            "market_type": "eq.spot",
            "status": "eq.TRADING",
            "order": "symbol.asc",
        }
    )

    overall_pass = True

    total_features = 0
    total_candles = 0

    for symbol in symbols:

        symbol_id = symbol["id"]
        symbol_name = symbol["symbol"]

        print()
        print("=" * 70)
        print(symbol_name)
        print("=" * 70)

        for timeframe in TIMEFRAMES:

            print()
            print(
                f"Checking {symbol_name} - "
                f"{timeframe}"
            )

            # -------------------------------------------------
            # Load candles
            # -------------------------------------------------

            candles = supabase_get(
                "candles",
                {
                    "select":
                        "open_time,close_time,"
                        "open,high,low,close,volume",

                    "symbol_id":
                        f"eq.{symbol_id}",

                    "timeframe":
                        f"eq.{timeframe}",

                    "order":
                        "open_time.asc",

                    "limit": "1000",
                }
            )

            # -------------------------------------------------
            # Load features
            # -------------------------------------------------

            features = supabase_get(
                "features",
                {
                    "select": "*",

                    "symbol_id":
                        f"eq.{symbol_id}",

                    "timeframe":
                        f"eq.{timeframe}",

                    "order":
                        "timestamp.asc",

                    "limit": "1000",
                }
            )

            candle_count = len(candles)
            feature_count = len(features)

            total_candles += candle_count
            total_features += feature_count

            print(
                f"Candles : {candle_count}"
            )

            print(
                f"Features: {feature_count}"
            )

            errors = []

            # -------------------------------------------------
            # 1. Feature timestamp monotonic
            # -------------------------------------------------

            timestamps = [
                row["timestamp"]
                for row in features
            ]

            if timestamps:

                if not check_monotonic(
                    timestamps
                ):

                    errors.append(
                        "Feature timestamps "
                        "not strictly increasing"
                    )

            # -------------------------------------------------
            # 2. Timestamp must correspond
            #    to candle close_time
            # -------------------------------------------------

            candle_close_times = {
                candle["close_time"]
                for candle in candles
            }

            for row in features:

                timestamp = row["timestamp"]

                if timestamp not in candle_close_times:

                    errors.append(
                        f"Feature timestamp "
                        f"not found in candles: "
                        f"{timestamp}"
                    )

                    break

            # -------------------------------------------------
            # 3. Price sanity
            # -------------------------------------------------

            for row in features:

                price = row["price"]

                if price is not None:

                    if (
                        not is_finite(price)
                        or float(price) <= 0
                    ):

                        errors.append(
                            "Invalid feature price"
                        )

                        break

            # -------------------------------------------------
            # 4. RSI range
            # -------------------------------------------------

            for row in features:

                for column in [
                    "rsi_6",
                    "rsi_12",
                    "rsi_24",
                ]:

                    value = row[column]

                    if value is None:
                        continue

                    if (
                        not is_finite(value)
                        or float(value) < 0
                        or float(value) > 100
                    ):

                        errors.append(
                            f"Invalid {column}"
                        )

                        break

                if errors:
                    break

            # -------------------------------------------------
            # 5. Bollinger relationship
            # -------------------------------------------------

            for row in features:

                upper = row["bollinger_upper"]
                middle = row["bollinger_middle"]
                lower = row["bollinger_lower"]

                if (
                    upper is None
                    or middle is None
                    or lower is None
                ):
                    continue

                if not (
                    float(upper)
                    >= float(middle)
                    >= float(lower)
                ):

                    errors.append(
                        "Invalid Bollinger "
                        "relationship"
                    )

                    break

            # -------------------------------------------------
            # 6. ATR must not be negative
            # -------------------------------------------------

            for row in features:

                for column in [
                    "atr",
                    "atr_percent",
                ]:

                    value = row[column]

                    if value is None:
                        continue

                    if (
                        not is_finite(value)
                        or float(value) < 0
                    ):

                        errors.append(
                            f"Invalid {column}"
                        )

                        break

                if errors:
                    break

            # -------------------------------------------------
            # 7. Volume features
            # -------------------------------------------------

            for row in features:

                for column in [
                    "volume",
                    "volume_ma",
                    "volume_ratio",
                ]:

                    value = row[column]

                    if value is None:
                        continue

                    if (
                        not is_finite(value)
                        or float(value) < 0
                    ):

                        errors.append(
                            f"Invalid {column}"
                        )

                        break

                if errors:
                    break

            # -------------------------------------------------
            # 8. Indicator numeric validity
            # -------------------------------------------------

            numeric_columns = [
                "return_1",
                "return_3",
                "return_5",
                "return_10",

                "sma_20",
                "sma_50",
                "sma_100",
                "sma_200",

                "ema_20",
                "ema_50",
                "ema_100",
                "ema_200",

                "rsi_6",
                "rsi_12",
                "rsi_24",

                "macd",
                "macd_signal",
                "macd_histogram",

                "atr",
                "atr_percent",

                "bollinger_upper",
                "bollinger_middle",
                "bollinger_lower",
                "bollinger_width",

                "volume",
                "volume_ma",
                "volume_ratio",

                "candle_body",
                "upper_wick",
                "lower_wick",
            ]

            for row in features:

                for column in numeric_columns:

                    value = row[column]

                    if not is_finite(value):

                        errors.append(
                            f"Non-finite value "
                            f"in {column}"
                        )

                        break

                if errors:
                    break

            # -------------------------------------------------
            # 9. Candle structure sanity
            # -------------------------------------------------

            for row in features:

                for column in [
                    "candle_body",
                    "upper_wick",
                    "lower_wick",
                ]:

                    value = row[column]

                    if value is None:
                        continue

                    if float(value) < 0:

                        errors.append(
                            f"Negative "
                            f"{column}"
                        )

                        break

                if errors:
                    break

            # -------------------------------------------------
            # Result
            # -------------------------------------------------

            if errors:

                overall_pass = False

                print("STATUS: FAIL")

                for error in errors[:10]:

                    print(
                        f"  ERROR: {error}"
                    )

            else:

                print("STATUS: PASS")

    # =========================================================
    # Final
    # =========================================================

    print()
    print("=" * 70)

    print(
        f"Total candle rows checked : "
        f"{total_candles}"
    )

    print(
        f"Total feature rows checked: "
        f"{total_features}"
    )

    if overall_pass:

        print(
            "OVERALL: PASS"
        )

    else:

        print(
            "OVERALL: FAIL"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()
