import os
import math
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

NEW_FEATURES = [
    "price_sma20_ratio",
    "price_sma50_ratio",
    "price_sma100_ratio",
    "price_sma200_ratio",

    "price_ema20_ratio",
    "price_ema50_ratio",
    "price_ema100_ratio",
    "price_ema200_ratio",

    "sma20_slope",
    "sma50_slope",
    "sma100_slope",
    "sma200_slope",

    "ema20_slope",
    "ema50_slope",
    "ema100_slope",
    "ema200_slope",

    "trend_alignment_score",

    "rsi6_change",
    "rsi12_change",
    "rsi24_change",

    "rsi6_acceleration",
    "rsi12_acceleration",
    "rsi24_acceleration",

    "macd_change",
    "macd_signal_change",
    "macd_histogram_change",

    "macd_acceleration",
    "macd_histogram_acceleration",

    "atr_change",
    "atr_percent_change",
    "atr_ma20",
    "atr_to_atr_ma20",

    "bollinger_width_change",
    "bollinger_width_ma20",
    "bollinger_width_to_ma20",

    "volatility_regime",
]

NUMERIC_FEATURES = [
    x for x in NEW_FEATURES
    if x != "volatility_regime"
]


def get_json(path, params=None):
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{SUPABASE_URL}{path}?{query}"
    else:
        url = f"{SUPABASE_URL}{path}"

    req = urllib.request.Request(
        url,
        headers=HEADERS,
        method="GET"
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_active_symbols():
    rows = get_json(
        "/rest/v1/symbols",
        {
            "select": "id,symbol,status",
            "status": "eq.TRADING",
            "order": "symbol.asc",
        }
    )
    return rows


def get_features(symbol_id, timeframe):
    rows = []

    limit = 1000
    offset = 0

    while True:
        batch = get_json(
            "/rest/v1/features",
            {
                "select": "id,symbol_id,timeframe,timestamp,price,"
                          + ",".join(NEW_FEATURES),
                "symbol_id": f"eq.{symbol_id}",
                "timeframe": f"eq.{timeframe}",
                "order": "timestamp.asc",
                "limit": str(limit),
                "offset": str(offset),
            }
        )

        rows.extend(batch)

        if len(batch) < limit:
            break

        offset += limit

    return rows


def is_finite_number(value):
    if value is None:
        return True

    if isinstance(value, bool):
        return False

    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def check_timestamp_order(rows):
    timestamps = [r["timestamp"] for r in rows]

    for i in range(1, len(timestamps)):
        if timestamps[i] <= timestamps[i - 1]:
            return False, timestamps[i - 1], timestamps[i]

    return True, None, None


def check_price(rows):
    errors = []

    for r in rows:
        value = r.get("price")

        if value is None:
            errors.append(
                f"{r['timestamp']}: price is NULL"
            )
            continue

        try:
            value = float(value)
        except Exception:
            errors.append(
                f"{r['timestamp']}: invalid price"
            )
            continue

        if not math.isfinite(value) or value <= 0:
            errors.append(
                f"{r['timestamp']}: invalid price={value}"
            )

    return errors


def check_numeric_features(rows):
    errors = []

    for feature in NUMERIC_FEATURES:
        for r in rows:
            value = r.get(feature)

            if value is None:
                continue

            if not is_finite_number(value):
                errors.append(
                    f"{r['timestamp']}: {feature}={value}"
                )

    return errors


def check_ratio_features(rows):
    errors = []

    ratio_features = [
        "price_sma20_ratio",
        "price_sma50_ratio",
        "price_sma100_ratio",
        "price_sma200_ratio",
        "price_ema20_ratio",
        "price_ema50_ratio",
        "price_ema100_ratio",
        "price_ema200_ratio",
        "atr_to_atr_ma20",
        "bollinger_width_to_ma20",
    ]

    for feature in ratio_features:
        for r in rows:
            value = r.get(feature)

            if value is None:
                continue

            try:
                value = float(value)
            except Exception:
                errors.append(
                    f"{r['timestamp']}: {feature} invalid"
                )
                continue

            if not math.isfinite(value):
                errors.append(
                    f"{r['timestamp']}: {feature} not finite"
                )

            if feature.startswith("price_") and value <= 0:
                errors.append(
                    f"{r['timestamp']}: {feature} <= 0 ({value})"
                )

            if feature in [
                "atr_to_atr_ma20",
                "bollinger_width_to_ma20",
            ] and value < 0:
                errors.append(
                    f"{r['timestamp']}: {feature} < 0 ({value})"
                )

    return errors


def check_trend_alignment(rows):
    errors = []

    for r in rows:
        value = r.get("trend_alignment_score")

        if value is None:
            continue

        try:
            value = float(value)
        except Exception:
            errors.append(
                f"{r['timestamp']}: invalid trend_alignment_score"
            )
            continue

        if value < -1 or value > 1:
            errors.append(
                f"{r['timestamp']}: "
                f"trend_alignment_score={value}, expected -1~1"
            )

    return errors


def check_volatility_regime(rows):
    errors = []

    allowed = {
        None,
        "LOW_VOLATILITY",
        "NORMAL_VOLATILITY",
        "HIGH_VOLATILITY",
    }

    for r in rows:
        value = r.get("volatility_regime")

        if value not in allowed:
            errors.append(
                f"{r['timestamp']}: "
                f"invalid volatility_regime={value}"
            )

    return errors


def check_new_feature_coverage(rows):
    result = {}

    total = len(rows)

    for feature in NEW_FEATURES:
        non_null = sum(
            1 for r in rows
            if r.get(feature) is not None
        )

        result[feature] = {
            "total": total,
            "non_null": non_null,
            "coverage": (
                non_null / total * 100
                if total > 0 else 0
            ),
        }

    return result


def main():
    print("=" * 70)
    print("FEATURE CHECK: PHASE 2A-5")
    print("=" * 70)

    symbols = get_active_symbols()

    total_checks = 0
    total_failures = 0
    total_rows = 0

    coverage_summary = {}

    for symbol in symbols:
        symbol_id = symbol["id"]
        symbol_name = symbol["symbol"]

        for timeframe in TIMEFRAMES:

            print()
            print("-" * 70)
            print(f"{symbol_name} - {timeframe}")

            rows = get_features(
                symbol_id,
                timeframe
            )

            total_checks += 1
            total_rows += len(rows)

            print(f"Feature rows: {len(rows)}")

            failures = []

            # 1. Timestamp order
            ok, previous_ts, current_ts = check_timestamp_order(rows)

            if not ok:
                failures.append(
                    f"timestamp order error: "
                    f"{previous_ts} -> {current_ts}"
                )

            # 2. Price
            failures.extend(
                check_price(rows)
            )

            # 3. Numeric finite
            failures.extend(
                check_numeric_features(rows)
            )

            # 4. Ratio sanity
            failures.extend(
                check_ratio_features(rows)
            )

            # 5. Trend alignment
            failures.extend(
                check_trend_alignment(rows)
            )

            # 6. Volatility regime
            failures.extend(
                check_volatility_regime(rows)
            )

            coverage = check_new_feature_coverage(rows)

            coverage_summary[
                f"{symbol_name}-{timeframe}"
            ] = coverage

            if failures:
                total_failures += 1

                print("FAIL")
                print(f"Errors: {len(failures)}")

                for error in failures[:10]:
                    print("  ", error)

                if len(failures) > 10:
                    print(
                        f"  ... and "
                        f"{len(failures) - 10} more"
                    )

            else:
                print("PASS")

            # 顯示新欄位覆蓋率
            important_features = [
                "price_sma20_ratio",
                "sma20_slope",
                "trend_alignment_score",
                "rsi6_change",
                "rsi6_acceleration",
                "macd_change",
                "atr_change",
                "atr_to_atr_ma20",
                "bollinger_width_change",
                "bollinger_width_to_ma20",
                "volatility_regime",
            ]

            print("Coverage:")

            for feature in important_features:
                info = coverage[feature]

                print(
                    f"  {feature}: "
                    f"{info['non_null']}/{info['total']} "
                    f"({info['coverage']:.2f}%)"
                )

    print()
    print("=" * 70)
    print("PHASE 2A-5 FEATURE CHECK COMPLETE")
    print("=" * 70)

    print(f"Timeframes checked: {total_checks}")
    print(f"Total feature rows: {total_rows}")
    print(f"Failed timeframes: {total_failures}")

    if total_failures == 0:
        print("OVERALL: PASS")
    else:
        print("OVERALL: FAIL")


if __name__ == "__main__":
    main()
