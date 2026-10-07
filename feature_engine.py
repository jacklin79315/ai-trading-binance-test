import os
import json
import math
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode


# =========================================================
# CONFIG
# =========================================================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 500

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


# =========================================================
# SUPABASE
# =========================================================

def supabase_get(table, params):
    query = urlencode(params, doseq=True)

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{table}?{query}"
    )

    request = Request(
        url,
        headers=HEADERS,
        method="GET",
    )

    with urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")

    return json.loads(body)


def supabase_upsert_features(rows):
    if not rows:
        return 0

    url = (
        f"{SUPABASE_URL}/rest/v1/features"
        f"?on_conflict=symbol_id,timeframe,timestamp"
    )

    headers = {
        **HEADERS,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    request = Request(
        url,
        headers=headers,
        data=json.dumps(rows).encode("utf-8"),
        method="POST",
    )

    with urlopen(request, timeout=120) as response:
        response.read()

    return len(rows)


# =========================================================
# SYMBOLS
# =========================================================

def get_active_symbols():
    return supabase_get(
        "symbols",
        {
            "select": "id,symbol",
            "exchange": "eq.binance",
            "market_type": "eq.spot",
            "status": "eq.TRADING",
            "order": "symbol.asc",
        },
    )


# =========================================================
# CANDLES
# =========================================================

def get_candles(
    symbol_id,
    timeframe,
    limit=1000,
    before=None,
):
    params = {
        "select": (
            "open_time,close_time,"
            "open,high,low,close,volume,"
            "quote_volume,trade_count"
        ),
        "symbol_id": f"eq.{symbol_id}",
        "timeframe": f"eq.{timeframe}",
        "order": "open_time.desc",
        "limit": str(limit),
    }

    if before is not None:
        params["open_time"] = f"lt.{before}"

    return supabase_get(
        "candles",
        params,
    )


def get_all_candles(
    symbol_id,
    timeframe,
):
    rows = []

    before = None

    while True:

        batch = get_candles(
            symbol_id,
            timeframe,
            PAGE_SIZE,
            before,
        )

        if not batch:
            break

        rows.extend(batch)

        if len(batch) < PAGE_SIZE:
            break

        before = batch[-1]["open_time"]

    rows.sort(
        key=lambda x: x["open_time"]
    )

    return rows


# =========================================================
# BASIC HELPERS
# =========================================================

def to_float(value):
    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def safe_div(a, b):
    if a is None or b is None:
        return None

    if b == 0:
        return None

    value = a / b

    if not math.isfinite(value):
        return None

    return value


def percentage_change(current, previous):
    if current is None or previous is None:
        return None

    if previous == 0:
        return None

    return (current / previous) - 1.0


def difference(current, previous):
    if current is None or previous is None:
        return None

    return current - previous


def iso_timestamp(value):
    return value


def is_closed_candle(candle):
    close_time = candle.get("close_time")

    if not close_time:
        return False

    try:
        dt = datetime.fromisoformat(
            close_time.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt <= datetime.now(
            timezone.utc
        )

    except Exception:
        return False


# =========================================================
# SERIES HELPERS
# =========================================================

def series_values(rows, key):
    return [
        to_float(row.get(key))
        for row in rows
    ]


def rolling_mean(values, period):
    result = [None] * len(values)

    window = []

    for i, value in enumerate(values):

        window.append(value)

        if len(window) > period:
            window.pop(0)

        valid = [
            x for x in window
            if x is not None
        ]

        if len(valid) == period:
            result[i] = (
                sum(valid) / period
            )

    return result


def sma_series(values, period):
    return rolling_mean(
        values,
        period,
    )


def ema_series(values, period):
    result = [None] * len(values)

    multiplier = 2.0 / (
        period + 1
    )

    previous = None

    for i, value in enumerate(values):

        if value is None:
            continue

        if previous is None:

            if i + 1 < period:
                continue

            initial_values = [
                x for x in values[
                    i - period + 1:i + 1
                ]
                if x is not None
            ]

            if len(initial_values) != period:
                continue

            previous = (
                sum(initial_values)
                / period
            )

            result[i] = previous

        else:

            previous = (
                value * multiplier
                + previous
                * (1 - multiplier)
            )

            result[i] = previous

    return result


# =========================================================
# RSI
# =========================================================

def calculate_rsi(values, period):
    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, len(values)):

        current = values[i]
        previous = values[i - 1]

        if (
            current is None
            or previous is None
        ):
            gains.append(None)
            losses.append(None)
            continue

        change = current - previous

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    if len(gains) < period:
        return result

    first_gains = [
        x for x in gains[:period]
        if x is not None
    ]

    first_losses = [
        x for x in losses[:period]
        if x is not None
    ]

    if (
        len(first_gains) != period
        or len(first_losses) != period
    ):
        return result

    avg_gain = (
        sum(first_gains)
        / period
    )

    avg_loss = (
        sum(first_losses)
        / period
    )

    index = period

    if avg_loss == 0:
        result[index] = 100.0

    else:
        rs = avg_gain / avg_loss
        result[index] = (
            100
            - 100 / (1 + rs)
        )

    for i in range(
        period + 1,
        len(values),
    ):

        gain = gains[i - 1]
        loss = losses[i - 1]

        if (
            gain is None
            or loss is None
        ):
            continue

        avg_gain = (
            (
                avg_gain * (period - 1)
            ) + gain
        ) / period

        avg_loss = (
            (
                avg_loss * (period - 1)
            ) + loss
        ) / period

        if avg_loss == 0:
            result[i] = 100.0

        else:
            rs = (
                avg_gain
                / avg_loss
            )

            result[i] = (
                100
                - 100 / (1 + rs)
            )

    return result


# =========================================================
# MACD
# =========================================================

def calculate_macd(values):
    ema12 = ema_series(
        values,
        12,
    )

    ema26 = ema_series(
        values,
        26,
    )

    macd = [None] * len(values)

    for i in range(len(values)):

        if (
            ema12[i] is not None
            and ema26[i] is not None
        ):
            macd[i] = (
                ema12[i]
                - ema26[i]
            )

    signal = ema_series(
        macd,
        9,
    )

    histogram = [None] * len(values)

    for i in range(len(values)):

        if (
            macd[i] is not None
            and signal[i] is not None
        ):
            histogram[i] = (
                macd[i]
                - signal[i]
            )

    return (
        macd,
        signal,
        histogram,
    )


# =========================================================
# ATR
# =========================================================

def calculate_atr(
    highs,
    lows,
    closes,
    period=14,
):
    true_ranges = [
        None
    ] * len(closes)

    for i in range(len(closes)):

        high = highs[i]
        low = lows[i]

        if (
            high is None
            or low is None
        ):
            continue

        if i == 0:
            true_ranges[i] = (
                high - low
            )
            continue

        previous_close = (
            closes[i - 1]
        )

        if previous_close is None:
            continue

        true_ranges[i] = max(
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

    return ema_series(
        true_ranges,
        period,
    )


# =========================================================
# BOLLINGER
# =========================================================

def calculate_bollinger(
    values,
    period=20,
    std_multiplier=2,
):
    middle = rolling_mean(
        values,
        period,
    )

    upper = [None] * len(values)
    lower = [None] * len(values)
    width = [None] * len(values)

    for i in range(len(values)):

        if middle[i] is None:
            continue

        window = values[
            i - period + 1:i + 1
        ]

        valid = [
            x for x in window
            if x is not None
        ]

        if len(valid) != period:
            continue

        mean = middle[i]

        variance = sum(
            (x - mean) ** 2
            for x in valid
        ) / period

        std = math.sqrt(
            variance
        )

        upper[i] = (
            mean
            + std_multiplier * std
        )

        lower[i] = (
            mean
            - std_multiplier * std
        )

        if mean != 0:
            width[i] = (
                upper[i]
                - lower[i]
            ) / mean

    return (
        upper,
        middle,
        lower,
        width,
    )


# =========================================================
# STOCHASTIC
# =========================================================

def calculate_stochastic(
    highs,
    lows,
    closes,
    period=14,
    smooth=3,
):
    raw_k = [None] * len(closes)

    for i in range(len(closes)):

        if i < period - 1:
            continue

        window_highs = highs[
            i - period + 1:i + 1
        ]

        window_lows = lows[
            i - period + 1:i + 1
        ]

        valid_highs = [
            x for x in window_highs
            if x is not None
        ]

        valid_lows = [
            x for x in window_lows
            if x is not None
        ]

        if (
            len(valid_highs) != period
            or len(valid_lows) != period
            or closes[i] is None
        ):
            continue

        highest = max(valid_highs)
        lowest = min(valid_lows)

        denominator = (
            highest - lowest
        )

        if denominator == 0:
            raw_k[i] = 50.0
        else:
            raw_k[i] = (
                (
                    closes[i]
                    - lowest
                )
                / denominator
            ) * 100

    k = rolling_mean(
        raw_k,
        smooth,
    )

    d = rolling_mean(
        k,
        smooth,
    )

    return k, d


# =========================================================
# ADX
# =========================================================

def calculate_adx(
    highs,
    lows,
    closes,
    period=14,
):
    tr = [None] * len(closes)
    plus_dm = [None] * len(closes)
    minus_dm = [None] * len(closes)

    for i in range(1, len(closes)):

        high = highs[i]
        low = lows[i]

        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        prev_close = closes[i - 1]

        if None in (
            high,
            low,
            prev_high,
            prev_low,
            prev_close,
        ):
            continue

        tr[i] = max(
            high - low,
            abs(
                high - prev_close
            ),
            abs(
                low - prev_close
            ),
        )

        up_move = (
            high - prev_high
        )

        down_move = (
            prev_low - low
        )

        plus_dm[i] = (
            up_move
            if (
                up_move > down_move
                and up_move > 0
            )
            else 0
        )

        minus_dm[i] = (
            down_move
            if (
                down_move > up_move
                and down_move > 0
            )
            else 0
        )

    atr = ema_series(
        tr,
        period,
    )

    plus = ema_series(
        plus_dm,
        period,
    )

    minus = ema_series(
        minus_dm,
        period,
    )

    dx = [None] * len(closes)

    for i in range(len(closes)):

        if (
            atr[i] is None
            or plus[i] is None
            or minus[i] is None
        ):
            continue

        if atr[i] == 0:
            continue

        plus_di = (
            100 * plus[i] / atr[i]
        )

        minus_di = (
            100 * minus[i] / atr[i]
        )

        denominator = (
            plus_di + minus_di
        )

        if denominator == 0:
            continue

        dx[i] = (
            100
            * abs(
                plus_di
                - minus_di
            )
            / denominator
        )

    return ema_series(
        dx,
        period,
    )


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    highs,
    lows,
    period=20,
):
    support = [None] * len(lows)
    resistance = [None] * len(highs)

    for i in range(len(highs)):

        if i < period:
            continue

        previous_highs = [
            x for x in highs[
                i - period:i
            ]
            if x is not None
        ]

        previous_lows = [
            x for x in lows[
                i - period:i
            ]
            if x is not None
        ]

        if len(previous_highs) == period:
            resistance[i] = max(
                previous_highs
            )

        if len(previous_lows) == period:
            support[i] = min(
                previous_lows
            )

    return (
        support,
        resistance,
    )


# =========================================================
# FEATURE CALCULATION
# =========================================================

def calculate_features(candles):

    closes = [
        to_float(c["close"])
        for c in candles
    ]

    opens = [
        to_float(c["open"])
        for c in candles
    ]

    highs = [
        to_float(c["high"])
        for c in candles
    ]

    lows = [
        to_float(c["low"])
        for c in candles
    ]

    volumes = [
        to_float(c["volume"])
        for c in candles
    ]

    # -----------------------------------------------------
    # RETURNS
    # -----------------------------------------------------

    returns = {}

    for period in [
        1,
        3,
        5,
        10,
    ]:

        values = [None] * len(
            closes
        )

        for i in range(
            period,
            len(closes),
        ):

            values[i] = (
                percentage_change(
                    closes[i],
                    closes[
                        i - period
                    ],
                )
            )

        returns[period] = values

    # -----------------------------------------------------
    # SMA / EMA
    # -----------------------------------------------------

    sma = {}
    ema = {}

    for period in [
        20,
        50,
        100,
        200,
    ]:

        sma[period] = sma_series(
            closes,
            period,
        )

        ema[period] = ema_series(
            closes,
            period,
        )

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    rsi = {}

    for period in [
        6,
        12,
        24,
    ]:

        rsi[period] = calculate_rsi(
            closes,
            period,
        )

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    (
        macd,
        macd_signal,
        macd_histogram,
    ) = calculate_macd(closes)

    # -----------------------------------------------------
    # STOCHASTIC
    # -----------------------------------------------------

    (
        stochastic_k,
        stochastic_d,
    ) = calculate_stochastic(
        highs,
        lows,
        closes,
    )

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    adx = calculate_adx(
        highs,
        lows,
        closes,
    )

    # -----------------------------------------------------
    # ATR
    # -----------------------------------------------------

    atr = calculate_atr(
        highs,
        lows,
        closes,
    )

    atr_percent = [
        safe_div(
            atr[i],
            closes[i],
        )
        for i in range(len(closes))
    ]

    atr_ma20 = rolling_mean(
        atr,
        20,
    )

    # -----------------------------------------------------
    # BOLLINGER
    # -----------------------------------------------------

    (
        bollinger_upper,
        bollinger_middle,
        bollinger_lower,
        bollinger_width,
    ) = calculate_bollinger(
        closes,
    )

    bollinger_width_ma20 = (
        rolling_mean(
            bollinger_width,
            20,
        )
    )

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    volume_ma = rolling_mean(
        volumes,
        20,
    )

    volume_ratio = [
        safe_div(
            volumes[i],
            volume_ma[i],
        )
        for i in range(
            len(volumes)
        )
    ]

    # -----------------------------------------------------
    # PRICE STRUCTURE
    # -----------------------------------------------------

    support, resistance = (
        calculate_support_resistance(
            highs,
            lows,
        )
    )

    # -----------------------------------------------------
    # BUILD FEATURES
    # -----------------------------------------------------

    features = []

    for i, candle in enumerate(
        candles
    ):

        price = closes[i]

        if price is None:
            continue

        # ---------------------------------------------
        # Candle structure
        # ---------------------------------------------

        candle_body = abs(
            closes[i] - opens[i]
        )

        upper_wick = (
            highs[i]
            - max(
                opens[i],
                closes[i],
            )
        )

        lower_wick = (
            min(
                opens[i],
                closes[i],
            )
            - lows[i]
        )

        # ---------------------------------------------
        # Price / MA ratios
        # ---------------------------------------------

        price_sma20_ratio = safe_div(
            price,
            sma[20][i],
        )

        price_sma50_ratio = safe_div(
            price,
            sma[50][i],
        )

        price_sma100_ratio = safe_div(
            price,
            sma[100][i],
        )

        price_sma200_ratio = safe_div(
            price,
            sma[200][i],
        )

        price_ema20_ratio = safe_div(
            price,
            ema[20][i],
        )

        price_ema50_ratio = safe_div(
            price,
            ema[50][i],
        )

        price_ema100_ratio = safe_div(
            price,
            ema[100][i],
        )

        price_ema200_ratio = safe_div(
            price,
            ema[200][i],
        )

        # ---------------------------------------------
        # MA slope
        #
        # 用百分比變化，不直接使用價格差。
        # 讓不同價格尺度的幣可以比較。
        # ---------------------------------------------

        sma20_slope = (
            percentage_change(
                sma[20][i],
                sma[20][i - 1],
            )
            if i >= 1
            else None
        )

        sma50_slope = (
            percentage_change(
                sma[50][i],
                sma[50][i - 1],
            )
            if i >= 1
            else None
        )

        sma100_slope = (
            percentage_change(
                sma[100][i],
                sma[100][i - 1],
            )
            if i >= 1
            else None
        )

        sma200_slope = (
            percentage_change(
                sma[200][i],
                sma[200][i - 1],
            )
            if i >= 1
            else None
        )

        ema20_slope = (
            percentage_change(
                ema[20][i],
                ema[20][i - 1],
            )
            if i >= 1
            else None
        )

        ema50_slope = (
            percentage_change(
                ema[50][i],
                ema[50][i - 1],
            )
            if i >= 1
            else None
        )

        ema100_slope = (
            percentage_change(
                ema[100][i],
                ema[100][i - 1],
            )
            if i >= 1
            else None
        )

        ema200_slope = (
            percentage_change(
                ema[200][i],
                ema[200][i - 1],
            )
            if i >= 1
            else None
        )

        # ---------------------------------------------
        # Trend alignment
        #
        # 正值 = 偏多排列
        # 負值 = 偏空排列
        # 0 = 沒有明確排列
        #
        # 不直接決策，只提供模型特徵。
        # ---------------------------------------------

        trend_components = []

        for short_period, long_period in [
            (20, 50),
            (50, 100),
            (100, 200),
        ]:

            if (
                sma[short_period][i]
                is not None
                and sma[long_period][i]
                is not None
            ):

                if (
                    sma[short_period][i]
                    > sma[long_period][i]
                ):
                    trend_components.append(
                        1
                    )

                elif (
                    sma[short_period][i]
                    < sma[long_period][i]
                ):
                    trend_components.append(
                        -1
                    )

                else:
                    trend_components.append(
                        0
                    )

        if trend_components:
            trend_alignment_score = (
                sum(trend_components)
                / len(trend_components)
            )
        else:
            trend_alignment_score = None

        # ---------------------------------------------
        # RSI change / acceleration
        # ---------------------------------------------

        rsi6_change = (
            difference(
                rsi[6][i],
                rsi[6][i - 1],
            )
            if i >= 1
            else None
        )

        rsi12_change = (
            difference(
                rsi[12][i],
                rsi[12][i - 1],
            )
            if i >= 1
            else None
        )

        rsi24_change = (
            difference(
                rsi[24][i],
                rsi[24][i - 1],
            )
            if i >= 1
            else None
        )

        rsi6_acceleration = (
            difference(
                rsi6_change,
                (
                    difference(
                        rsi[6][i - 1],
                        rsi[6][i - 2],
                    )
                    if i >= 2
                    else None
                ),
            )
            if i >= 2
            else None
        )

        rsi12_acceleration = (
            difference(
                rsi12_change,
                (
                    difference(
                        rsi[12][i - 1],
                        rsi[12][i - 2],
                    )
                    if i >= 2
                    else None
                ),
            )
            if i >= 2
            else None
        )

        rsi24_acceleration = (
            difference(
                rsi24_change,
                (
                    difference(
                        rsi[24][i - 1],
                        rsi[24][i - 2],
                    )
                    if i >= 2
                    else None
                ),
            )
            if i >= 2
            else None
        )

        # ---------------------------------------------
        # MACD change / acceleration
        # ---------------------------------------------

        macd_change = (
            difference(
                macd[i],
                macd[i - 1],
            )
            if i >= 1
            else None
        )

        macd_signal_change = (
            difference(
                macd_signal[i],
                macd_signal[i - 1],
            )
            if i >= 1
            else None
        )

        macd_histogram_change = (
            difference(
                macd_histogram[i],
                macd_histogram[i - 1],
            )
            if i >= 1
            else None
        )

        previous_macd_change = (
            difference(
                macd[i - 1],
                macd[i - 2],
            )
            if i >= 2
            else None
        )

        previous_histogram_change = (
            difference(
                macd_histogram[i - 1],
                macd_histogram[i - 2],
            )
            if i >= 2
            else None
        )

        macd_acceleration = (
            difference(
                macd_change,
                previous_macd_change,
            )
            if i >= 2
            else None
        )

        macd_histogram_acceleration = (
            difference(
                macd_histogram_change,
                previous_histogram_change,
            )
            if i >= 2
            else None
        )

        # ---------------------------------------------
        # Volatility
        # ---------------------------------------------

        atr_change = (
            percentage_change(
                atr[i],
                atr[i - 1],
            )
            if i >= 1
            else None
        )

        atr_percent_change = (
            percentage_change(
                atr_percent[i],
                atr_percent[i - 1],
            )
            if i >= 1
            else None
        )

        atr_to_atr_ma20 = safe_div(
            atr[i],
            atr_ma20[i],
        )

        bollinger_width_change = (
            percentage_change(
                bollinger_width[i],
                bollinger_width[i - 1],
            )
            if i >= 1
            else None
        )

        bollinger_width_to_ma20 = (
            safe_div(
                bollinger_width[i],
                bollinger_width_ma20[i],
            )
        )

        # ---------------------------------------------
        # Volatility regime
        #
        # 只做描述，不直接產生交易訊號。
        # ---------------------------------------------

        volatility_regime = None

        if (
            atr_to_atr_ma20 is not None
            and bollinger_width_to_ma20
            is not None
        ):

            if (
                atr_to_atr_ma20 >= 1.25
                and bollinger_width_to_ma20
                >= 1.25
            ):
                volatility_regime = (
                    "HIGH_VOLATILITY"
                )

            elif (
                atr_to_atr_ma20 <= 0.80
                and bollinger_width_to_ma20
                <= 0.80
            ):
                volatility_regime = (
                    "LOW_VOLATILITY"
                )

            elif (
                atr_to_atr_ma20 > 1.0
                or bollinger_width_to_ma20
                > 1.0
            ):
                volatility_regime = (
                    "VOLATILITY_EXPANSION"
                )

            else:
                volatility_regime = (
                    "NORMAL_VOLATILITY"
                )

        # ---------------------------------------------
        # Support / resistance distance
        # ---------------------------------------------

        distance_to_support = (
            safe_div(
                price - support[i],
                price,
            )
            if support[i] is not None
            else None
        )

        distance_to_resistance = (
            safe_div(
                resistance[i] - price,
                price,
            )
            if resistance[i] is not None
            else None
        )

        # ---------------------------------------------
        # Feature row
        # ---------------------------------------------

        feature = {
            "symbol_id": candle["symbol_id"]
            if "symbol_id" in candle
            else None,

            "timeframe": candle.get(
                "timeframe"
            ),

            "timestamp": candle[
                "close_time"
            ],

            "price": price,

            "return_1": returns[1][i],
            "return_3": returns[3][i],
            "return_5": returns[5][i],
            "return_10": returns[10][i],

            "sma_20": sma[20][i],
            "sma_50": sma[50][i],
            "sma_100": sma[100][i],
            "sma_200": sma[200][i],

            "ema_20": ema[20][i],
            "ema_50": ema[50][i],
            "ema_100": ema[100][i],
            "ema_200": ema[200][i],

            "rsi_6": rsi[6][i],
            "rsi_12": rsi[12][i],
            "rsi_24": rsi[24][i],

            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram":
                macd_histogram[i],

            "stochastic_k":
                stochastic_k[i],

            "stochastic_d":
                stochastic_d[i],

            "adx": adx[i],

            "atr": atr[i],
            "atr_percent":
                atr_percent[i],

            "bollinger_upper":
                bollinger_upper[i],

            "bollinger_middle":
                bollinger_middle[i],

            "bollinger_lower":
                bollinger_lower[i],

            "bollinger_width":
                bollinger_width[i],

            "volume": volumes[i],

            "volume_ma":
                volume_ma[i],

            "volume_ratio":
                volume_ratio[i],

            "candle_body":
                candle_body,

            "upper_wick":
                upper_wick,

            "lower_wick":
                lower_wick,

            "support_price":
                support[i],

            "resistance_price":
                resistance[i],

            "distance_to_support":
                distance_to_support,

            "distance_to_resistance":
                distance_to_resistance,

            # -----------------------------------------
            # New Phase 2A-5 trend features
            # -----------------------------------------

            "price_sma20_ratio":
                price_sma20_ratio,

            "price_sma50_ratio":
                price_sma50_ratio,

            "price_sma100_ratio":
                price_sma100_ratio,

            "price_sma200_ratio":
                price_sma200_ratio,

            "price_ema20_ratio":
                price_ema20_ratio,

            "price_ema50_ratio":
                price_ema50_ratio,

            "price_ema100_ratio":
                price_ema100_ratio,

            "price_ema200_ratio":
                price_ema200_ratio,

            "sma20_slope":
                sma20_slope,

            "sma50_slope":
                sma50_slope,

            "sma100_slope":
                sma100_slope,

            "sma200_slope":
                sma200_slope,

            "ema20_slope":
                ema20_slope,

            "ema50_slope":
                ema50_slope,

            "ema100_slope":
                ema100_slope,

            "ema200_slope":
                ema200_slope,

            "trend_alignment_score":
                trend_alignment_score,

            # -----------------------------------------
            # Momentum
            # -----------------------------------------

            "rsi6_change":
                rsi6_change,

            "rsi12_change":
                rsi12_change,

            "rsi24_change":
                rsi24_change,

            "rsi6_acceleration":
                rsi6_acceleration,

            "rsi12_acceleration":
                rsi12_acceleration,

            "rsi24_acceleration":
                rsi24_acceleration,

            "macd_change":
                macd_change,

            "macd_signal_change":
                macd_signal_change,

            "macd_histogram_change":
                macd_histogram_change,

            "macd_acceleration":
                macd_acceleration,

            "macd_histogram_acceleration":
                macd_histogram_acceleration,

            # -----------------------------------------
            # Volatility
            # -----------------------------------------

            "atr_change":
                atr_change,

            "atr_percent_change":
                atr_percent_change,

            "atr_ma20":
                atr_ma20[i],

            "atr_to_atr_ma20":
                atr_to_atr_ma20,

            "bollinger_width_change":
                bollinger_width_change,

            "bollinger_width_ma20":
                bollinger_width_ma20[i],

            "bollinger_width_to_ma20":
                bollinger_width_to_ma20,

            "volatility_regime":
                volatility_regime,
        }

        features.append(
            feature
        )

    return features


# =========================================================
# REMOVE NULL SYMBOL / TIMEFRAME ISSUE
# =========================================================

def attach_symbol_metadata(
    candles,
    symbol_id,
    timeframe,
):
    for candle in candles:
        candle["symbol_id"] = symbol_id
        candle["timeframe"] = timeframe

    return candles


# =========================================================
# EXISTING FEATURE TIMESTAMP
# =========================================================

def get_latest_feature_timestamp(
    symbol_id,
    timeframe,
):
    rows = supabase_get(
        "features",
        {
            "select": "timestamp",
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "timestamp.desc",
            "limit": "1",
        },
    )

    if not rows:
        return None

    return rows[0]["timestamp"]


# =========================================================
# PROCESS ONE SYMBOL / TIMEFRAME
# =========================================================

def process_symbol_timeframe(
    symbol,
    symbol_id,
    timeframe,
):
    print()
    print("=" * 70)
    print(
        f"FEATURE ENGINE: "
        f"{symbol} - {timeframe}"
    )
    print("=" * 70)

    candles = get_all_candles(
        symbol_id,
        timeframe,
    )

    if not candles:
        print("No candles found.")
        return 0

    # -----------------------------------------------------
    # 只使用已收盤 K 線
    # -----------------------------------------------------

    candles = [
        candle
        for candle in candles
        if is_closed_candle(candle)
    ]

    if not candles:
        print("No closed candles.")
        return 0

    candles = attach_symbol_metadata(
        candles,
        symbol_id,
        timeframe,
    )

    print(
        f"Closed candles: "
        f"{len(candles)}"
    )

    # -----------------------------------------------------
    # 計算完整歷史特徵
    #
    # 這裡不使用未來資料。
    # 所有 rolling / EMA / RSI 都只使用當下
    # 及之前的資料。
    # -----------------------------------------------------

    features = calculate_features(
        candles
    )

    if not features:
        print("No features generated.")
        return 0

    # -----------------------------------------------------
    # 增量處理
    #
    # 只寫入最新尚未存在的 timestamp。
    # -----------------------------------------------------

    latest_timestamp = (
        get_latest_feature_timestamp(
            symbol_id,
            timeframe,
        )
    )

    if latest_timestamp is not None:

        features = [
            row
            for row in features
            if row["timestamp"]
            > latest_timestamp
        ]

    print(
        f"New features: "
        f"{len(features)}"
    )

    if not features:
        print(
            "No new features "
            "to write."
        )
        return 0

    total_written = 0

    for start in range(
        0,
        len(features),
        WRITE_BATCH_SIZE,
    ):

        batch = features[
            start:
            start + WRITE_BATCH_SIZE
        ]

        written = (
            supabase_upsert_features(
                batch
            )
        )

        total_written += written

        print(
            f"Batch "
            f"{start // WRITE_BATCH_SIZE + 1}: "
            f"{written} rows | "
            f"Total: "
            f"{total_written}"
        )

    print()
    print(
        f"Completed: "
        f"{symbol} "
        f"{timeframe} | "
        f"Written: "
        f"{total_written}"
    )

    return total_written


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 70)
    print("FEATURE ENGINE")
    print("Phase 2A-5")
    print("=" * 70)

    symbols = get_active_symbols()

    print(
        f"Active symbols: "
        f"{len(symbols)}"
    )

    total_written = 0

    for symbol_data in symbols:

        symbol = symbol_data[
            "symbol"
        ]

        symbol_id = symbol_data[
            "id"
        ]

        for timeframe in TIMEFRAMES:

            try:

                total_written += (
                    process_symbol_timeframe(
                        symbol,
                        symbol_id,
                        timeframe,
                    )
                )

            except Exception as exc:

                print()
                print(
                    "=" * 70
                )

                print(
                    f"ERROR: "
                    f"{symbol} "
                    f"{timeframe}"
                )

                print(
                    repr(exc)
                )

                print(
                    "=" * 70
                )

    print()
    print("=" * 70)
    print("FEATURE ENGINE COMPLETE")
    print("=" * 70)

    print(
        f"Total written: "
        f"{total_written}"
    )


if __name__ == "__main__":
    main()
