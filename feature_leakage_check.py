import os
import json
import math
import random
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# 每個 symbol / timeframe 固定抽查這些位置
SAMPLE_POSITIONS = [30, 100, 300, 600, 900]

EPS = 1e-8


def supabase_get(table, params):
    query = urlencode(params, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"

    req = Request(url, headers=HEADERS, method="GET")

    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def is_finite(value):
    return (
        value is not None
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def almost_equal(a, b, tolerance=EPS):
    if a is None or b is None:
        return a is None and b is None

    if not is_finite(a) or not is_finite(b):
        return False

    scale = max(1.0, abs(float(a)), abs(float(b)))

    return abs(float(a) - float(b)) <= tolerance * scale


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None

    seed = sum(values[:period]) / period
    result = seed

    multiplier = 2 / (period + 1)

    for value in values[period:]:
        result = (value - result) * multiplier + result

    return result


def rsi_wilder(values, period):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr_wilder(highs, lows, closes, period=14):
    if len(closes) <= period:
        return None

    trs = []

    for i in range(len(closes)):
        if i == 0:
            tr = highs[i] - lows[i]
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )

        trs.append(tr)

    atr = sum(trs[:period]) / period

    for i in range(period, len(trs)):
        atr = ((atr * (period - 1)) + trs[i]) / period

    return atr


def bollinger(values, period=20, multiplier=2):
    if len(values) < period:
        return None, None, None, None

    window = values[-period:]

    middle = sum(window) / period

    variance = sum(
        (x - middle) ** 2
        for x in window
    ) / period

    std = math.sqrt(variance)

    upper = middle + multiplier * std
    lower = middle - multiplier * std

    if middle == 0:
        width = None
    else:
        width = (upper - lower) / middle

    return upper, middle, lower, width


def calculate_expected(candles):
    """
    candles 必須只包含「截至目前這一根」的資料。
    絕對不能包含後面的 candle。
    """

    closes = [float(x["close"]) for x in candles]
    highs = [float(x["high"]) for x in candles]
    lows = [float(x["low"]) for x in candles]
    volumes = [float(x["volume"]) for x in candles]

    current = closes[-1]

    result = {}

    # -------------------------------------------------
    # Return
    # -------------------------------------------------

    for period in [1, 3, 5, 10]:
        key = f"return_{period}"

        if len(closes) > period:
            result[key] = current / closes[-1 - period] - 1
        else:
            result[key] = None

    # -------------------------------------------------
    # SMA
    # -------------------------------------------------

    for period in [20, 50, 100, 200]:
        result[f"sma_{period}"] = sma(closes, period)

    # -------------------------------------------------
    # EMA
    # -------------------------------------------------

    for period in [20, 50, 100, 200]:
        result[f"ema_{period}"] = ema(closes, period)

    # -------------------------------------------------
    # RSI
    # -------------------------------------------------

    for period in [6, 12, 24]:
        result[f"rsi_{period}"] = rsi_wilder(closes, period)

    # -------------------------------------------------
    # MACD
    # -------------------------------------------------

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    if ema12 is not None and ema26 is not None:
        # 重新建立完整 MACD 序列
        macd_values = []

        for i in range(len(closes)):
            prefix = closes[: i + 1]

            e12 = ema(prefix, 12)
            e26 = ema(prefix, 26)

            if e12 is not None and e26 is not None:
                macd_values.append(e12 - e26)

        if macd_values:
            macd = macd_values[-1]
            signal = ema(macd_values, 9)

            result["macd"] = macd
            result["macd_signal"] = signal

            if signal is not None:
                result["macd_histogram"] = macd - signal
            else:
                result["macd_histogram"] = None
        else:
            result["macd"] = None
            result["macd_signal"] = None
            result["macd_histogram"] = None
    else:
        result["macd"] = None
        result["macd_signal"] = None
        result["macd_histogram"] = None

    # -------------------------------------------------
    # ATR
    # -------------------------------------------------

    atr = atr_wilder(highs, lows, closes, 14)

    result["atr"] = atr

    if atr is not None and current != 0:
        result["atr_percent"] = atr / current
    else:
        result["atr_percent"] = None

    # -------------------------------------------------
    # Bollinger
    # -------------------------------------------------

    upper, middle, lower, width = bollinger(
        closes,
        20,
        2
    )

    result["bollinger_upper"] = upper
    result["bollinger_middle"] = middle
    result["bollinger_lower"] = lower
    result["bollinger_width"] = width

    # -------------------------------------------------
    # Volume
    # -------------------------------------------------

    result["volume"] = volumes[-1]

    volume_ma = sma(volumes, 20)

    result["volume_ma"] = volume_ma

    if volume_ma is not None and volume_ma != 0:
        result["volume_ratio"] = volumes[-1] / volume_ma
    else:
        result["volume_ratio"] = None

    # -------------------------------------------------
    # Candle Structure
    # -------------------------------------------------

    candle = candles[-1]

    open_price = float(candle["open"])
    high_price = float(candle["high"])
    low_price = float(candle["low"])
    close_price = float(candle["close"])

    result["candle_body"] = abs(close_price - open_price)

    result["upper_wick"] = (
        high_price - max(open_price, close_price)
    )

    result["lower_wick"] = (
        min(open_price, close_price) - low_price
    )

    return result


CHECK_FIELDS = [
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


def check_one(symbol, timeframe, symbol_id):
    print()
    print("=" * 60)
    print(f"Checking {symbol} - {timeframe}")
    print("=" * 60)

    # -------------------------------------------------
    # 讀取 candles
    # -------------------------------------------------

    candles = supabase_get(
        "candles",
        {
            "select": "*",
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "open_time.asc",
            "limit": 1000,
        },
    )

    # -------------------------------------------------
    # 只取已經收盤的 candle
    # -------------------------------------------------

    now = datetime.now(timezone.utc)

    closed_candles = []

    for candle in candles:
        close_time = datetime.fromisoformat(
            candle["close_time"].replace("Z", "+00:00")
        )

        if close_time <= now:
            closed_candles.append(candle)

    # -------------------------------------------------
    # 讀取 features
    # -------------------------------------------------

    features = supabase_get(
        "features",
        {
            "select": "*",
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "timestamp.asc",
            "limit": 1000,
        },
    )

    feature_map = {
        row["timestamp"]: row
        for row in features
    }

    errors = []

    checked = 0

    # -------------------------------------------------
    # 固定抽查幾個位置
    # -------------------------------------------------

    positions = [
        p
        for p in SAMPLE_POSITIONS
        if p < len(closed_candles)
    ]

    # 再固定抽查最後一根
    if closed_candles:
        positions.append(len(closed_candles) - 1)

    positions = sorted(set(positions))

    for pos in positions:

        candle = closed_candles[pos]

        timestamp = candle["close_time"]

        stored = feature_map.get(timestamp)

        if stored is None:
            errors.append(
                f"Missing feature at {timestamp}"
            )
            continue

        # -------------------------------------------------
        # 關鍵：
        #
        # 只把「截至這根 candle」的資料交給計算器
        #
        # 後面的 candle 完全不會進來。
        # -------------------------------------------------

        prefix = closed_candles[: pos + 1]

        expected = calculate_expected(prefix)

        checked += 1

        for field in CHECK_FIELDS:

            actual = stored.get(field)
            exp = expected.get(field)

            if not almost_equal(actual, exp):

                errors.append(
                    f"{timestamp} | "
                    f"{field} | "
                    f"stored={actual} | "
                    f"expected={exp}"
                )

    if errors:

        print(f"STATUS: FAIL")
        print(f"Errors: {len(errors)}")

        for error in errors[:20]:
            print("  ", error)

        return False

    print(f"Candles       : {len(candles)}")
    print(f"Closed candles: {len(closed_candles)}")
    print(f"Features      : {len(features)}")
    print(f"Samples checked: {checked}")
    print("STATUS: PASS")

    return True


def main():

    print("=" * 60)
    print("FEATURE LOOK-AHEAD BIAS CHECK")
    print("=" * 60)

    # -------------------------------------------------
    # 取得所有 active symbols
    # -------------------------------------------------

    symbols = supabase_get(
        "symbols",
        {
            "select": "id,symbol",
            "exchange": "eq.binance",
            "market_type": "eq.spot",
            "status": "eq.TRADING",
            "order": "symbol.asc",
        },
    )

    timeframes = [
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    ]

    total_checks = 0
    total_pass = 0

    for item in symbols:

        symbol = item["symbol"]
        symbol_id = item["id"]

        for timeframe in timeframes:

            total_checks += 1

            try:

                passed = check_one(
                    symbol,
                    timeframe,
                    symbol_id,
                )

                if passed:
                    total_pass += 1

            except Exception as e:

                print()
                print(
                    f"ERROR: {symbol} - {timeframe}"
                )

                print(str(e))

    print()
    print("=" * 60)
    print("FINAL RESULT")
    print("=" * 60)

    print(
        f"Timeframes checked: {total_checks}"
    )

    print(
        f"Passed: {total_pass}"
    )

    print(
        f"Failed: {total_checks - total_pass}"
    )

    if total_pass == total_checks:
        print("OVERALL: PASS")
    else:
        print("OVERALL: FAIL")


if __name__ == "__main__":
    main()
