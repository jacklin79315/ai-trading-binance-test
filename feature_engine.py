import os
import math
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone


# =========================================================
# Configuration
# =========================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set")


# True  = recalculate and write all historical features
# False = incremental mode
FORCE_HISTORICAL_BACKFILL = True

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

READ_PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 500
PROGRESS_EVERY = 10000


# =========================================================
# Supabase HTTP
# =========================================================

def supabase_request(
    method,
    path,
    params=None,
    body=None,
    headers=None,
):
    url = SUPABASE_URL.rstrip("/") + path

    if params:
        query = urllib.parse.urlencode(
            params,
            doseq=True,
        )
        url += "?" + query

    request_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if headers:
        request_headers.update(headers)

    data = None

    if body is not None:
        data = json.dumps(
            body,
            separators=(",", ":"),
        ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:

            raw = response.read()

            if not raw:
                return None

            text = raw.decode("utf-8")

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    except urllib.error.HTTPError as exc:

        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Supabase HTTP {exc.code}: "
            f"{error_body}"
        )

    except urllib.error.URLError as exc:

        raise RuntimeError(
            f"Supabase connection error: {exc}"
        )


# =========================================================
# Basic utilities
# =========================================================

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


def iso_to_ms(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return int(
        dt.timestamp() * 1000
    )


def ms_to_iso(ms):

    return datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    ).isoformat().replace(
        "+00:00",
        "Z",
    )


def ratio(
    numerator,
    denominator,
):

    if (
        numerator is None
        or denominator is None
        or denominator == 0
    ):
        return None

    return numerator / denominator


def percent_change(
    current,
    previous,
):

    if (
        current is None
        or previous is None
        or previous == 0
    ):
        return None

    return (
        current - previous
    ) / abs(previous)


def change_value(
    series,
    index,
):

    if index <= 0:
        return None

    current = series[index]
    previous = series[index - 1]

    if (
        current is None
        or previous is None
    ):
        return None

    return current - previous


def acceleration_value(
    series,
    index,
):

    if index < 2:
        return None

    current = series[index]
    previous = series[index - 1]
    previous_previous = series[index - 2]

    if (
        current is None
        or previous is None
        or previous_previous is None
    ):
        return None

    return (
        current
        - 2 * previous
        + previous_previous
    )


# =========================================================
# Supabase reads
# =========================================================

def get_active_symbols():

    rows = supabase_request(
        "GET",
        "/rest/v1/symbols",
        params={
            "select": (
                "id,symbol,market_type,status"
            ),
            "status": "eq.TRADING",
            "order": "symbol.asc",
        },
    )

    if not rows:
        return []

    return [
        row
        for row in rows
        if row.get("market_type") == "spot"
    ]


def get_all_candles(
    symbol_id,
    timeframe,
):

    all_rows = []
    offset = 0

    while True:

        rows = supabase_request(
            "GET",
            "/rest/v1/candles",
            params={
                "select": (
                    "open_time,"
                    "open,"
                    "high,"
                    "low,"
                    "close,"
                    "volume,"
                    "quote_volume,"
                    "trade_count,"
                    "close_time"
                ),
                "symbol_id": f"eq.{symbol_id}",
                "timeframe": f"eq.{timeframe}",
                "order": "open_time.asc",
                "limit": READ_PAGE_SIZE,
                "offset": offset,
            },
        )

        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < READ_PAGE_SIZE:
            break

        offset += READ_PAGE_SIZE

    return all_rows


def get_latest_feature_timestamp(
    symbol_id,
    timeframe,
):

    rows = supabase_request(
        "GET",
        "/rest/v1/features",
        params={
            "select": "timestamp",
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "timestamp.desc",
            "limit": 1,
        },
    )

    if not rows:
        return None

    return iso_to_ms(
        rows[0]["timestamp"]
    )


# =========================================================
# Candle parsing
# =========================================================

def parse_candles(
    rows,
    symbol_id,
):

    candles = []

    for row in rows:

        candles.append(
            {
                "symbol_id": symbol_id,

                "open_time": iso_to_ms(
                    row["open_time"]
                ),

                "close_time": iso_to_ms(
                    row["close_time"]
                ),

                "open": safe_float(
                    row["open"]
                ),

                "high": safe_float(
                    row["high"]
                ),

                "low": safe_float(
                    row["low"]
                ),

                "close": safe_float(
                    row["close"]
                ),

                "volume": safe_float(
                    row["volume"]
                ),

                "quote_volume": safe_float(
                    row.get("quote_volume")
                ),

                "trade_count": (
                    int(row["trade_count"])
                    if row.get("trade_count") is not None
                    else None
                ),
            }
        )

    return candles


def is_closed_candle(candle):

    return (
        candle["close_time"]
        <= int(time.time() * 1000)
    )
# =========================================================
# Rolling calculations
# =========================================================

def rolling_mean(values, period):

    result = [None] * len(values)

    running_sum = 0.0
    valid_count = 0

    for i, value in enumerate(values):

        if value is not None:
            running_sum += value
            valid_count += 1

        if i >= period:

            old_value = values[i - period]

            if old_value is not None:
                running_sum -= old_value
                valid_count -= 1

        if (
            i >= period - 1
            and valid_count == period
        ):
            result[i] = (
                running_sum / period
            )

    return result


def rolling_std(
    values,
    period,
):

    result = [None] * len(values)

    for i in range(
        period - 1,
        len(values),
    ):

        window = values[
            i - period + 1:
            i + 1
        ]

        if any(
            value is None
            for value in window
        ):
            continue

        average = (
            sum(window) / period
        )

        variance = (
            sum(
                (value - average) ** 2
                for value in window
            )
            / period
        )

        result[i] = math.sqrt(
            variance
        )

    return result


def rolling_max(
    values,
    period,
):

    result = [None] * len(values)

    for i in range(
        period - 1,
        len(values),
    ):

        window = values[
            i - period + 1:
            i + 1
        ]

        if any(
            value is None
            for value in window
        ):
            continue

        result[i] = max(window)

    return result


def rolling_min(
    values,
    period,
):

    result = [None] * len(values)

    for i in range(
        period - 1,
        len(values),
    ):

        window = values[
            i - period + 1:
            i + 1
        ]

        if any(
            value is None
            for value in window
        ):
            continue

        result[i] = min(window)

    return result


# =========================================================
# EMA
# =========================================================

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


# =========================================================
# RSI
# =========================================================

def rsi_series(
    values,
    period,
):

    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(
        1,
        period + 1,
    ):

        difference = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(difference, 0)
        )

        losses.append(
            max(-difference, 0)
        )

    average_gain = (
        sum(gains) / period
    )

    average_loss = (
        sum(losses) / period
    )

    if average_loss == 0:
        result[period] = 100.0
    else:
        relative_strength = (
            average_gain
            / average_loss
        )

        result[period] = (
            100
            - 100
            / (1 + relative_strength)
        )

    for i in range(
        period + 1,
        len(values),
    ):

        difference = (
            values[i]
            - values[i - 1]
        )

        gain = max(
            difference,
            0,
        )

        loss = max(
            -difference,
            0,
        )

        average_gain = (
            (
                average_gain
                * (period - 1)
            )
            + gain
        ) / period

        average_loss = (
            (
                average_loss
                * (period - 1)
            )
            + loss
        ) / period

        if average_loss == 0:
            result[i] = 100.0
        else:

            relative_strength = (
                average_gain
                / average_loss
            )

            result[i] = (
                100
                - 100
                / (1 + relative_strength)
            )

    return result


# =========================================================
# True Range / ATR
# =========================================================

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
            previous_close = candle["close"]
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

        previous_close = candle["close"]

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

    result = [None] * len(true_ranges)

    if len(true_ranges) < period:
        return result

    first_window = true_ranges[:period]

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
            (atr * (period - 1))
            + value
        ) / period

        result[i] = atr

    print("ATR calculated.")

    return result


# =========================================================
# MACD
# =========================================================

def macd_series(
    values,
    fast_period=12,
    slow_period=26,
    signal_period=9,
):
    """
    Calculate MACD without allowing leading None values
    to break the signal EMA.

    Returns:
        macd
        signal
        histogram
    """

    count = len(values)

    fast_ema = ema_series(
        values,
        fast_period,
    )

    slow_ema = ema_series(
        values,
        slow_period,
    )

    macd = [
        None
        for _ in range(count)
    ]

    for i in range(count):

        if (
            fast_ema[i] is None
            or slow_ema[i] is None
        ):
            continue

        macd[i] = (
            fast_ema[i]
            - slow_ema[i]
        )

    # -----------------------------------------------------
    # Build compact MACD series for signal EMA
    # -----------------------------------------------------

    valid_macd = []

    valid_indexes = []

    for i in range(count):

        if macd[i] is not None:

            valid_macd.append(
                macd[i]
            )

            valid_indexes.append(i)

    signal_compact = ema_series(
        valid_macd,
        signal_period,
    )

    signal = [
        None
        for _ in range(count)
    ]

    for j, index in enumerate(
        valid_indexes
    ):

        if (
            signal_compact[j]
            is not None
        ):

            signal[index] = (
                signal_compact[j]
            )

    histogram = [
        None
        for _ in range(count)
    ]

    for i in range(count):

        if (
            macd[i] is None
            or signal[i] is None
        ):
            continue

        histogram[i] = (
            macd[i]
            - signal[i]
        )

    return (
        macd,
        signal,
        histogram,
    )

    ema12 = ema_series(
        closes,
        12,
    )

    ema26 = ema_series(
        closes,
        26,
    )

    macd = [None] * len(closes)

    for i in range(
        len(closes)
    ):

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

    histogram = [None] * len(
        closes
    )

    for i in range(
        len(closes)
    ):

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
# Stochastic
# =========================================================

def stochastic_series(
    candles,
    period=14,
    smooth=3,
):

    highs = [
        candle["high"]
        for candle in candles
    ]

    lows = [
        candle["low"]
        for candle in candles
    ]

    closes = [
        candle["close"]
        for candle in candles
    ]

    highest = rolling_max(
        highs,
        period,
    )

    lowest = rolling_min(
        lows,
        period,
    )

    stochastic_k = [
        None
    ] * len(candles)

    for i in range(
        len(candles)
    ):

        if (
            highest[i] is None
            or lowest[i] is None
        ):
            continue

        if (
            highest[i]
            == lowest[i]
        ):

            stochastic_k[i] = 50.0

        else:

            stochastic_k[i] = (
                (
                    closes[i]
                    - lowest[i]
                )
                /
                (
                    highest[i]
                    - lowest[i]
                )
                * 100
            )

    stochastic_d = rolling_mean(
        stochastic_k,
        smooth,
    )

    return (
        stochastic_k,
        stochastic_d,
    )


# =========================================================
# ADX
# =========================================================

def adx_series(
    candles,
    period=14,
):

    count = len(candles)

    result = [None] * count

    if count < period * 2:
        return result

    true_ranges = [
        0.0
    ] * count

    plus_dm = [
        0.0
    ] * count

    minus_dm = [
        0.0
    ] * count

    for i in range(count):

        if i == 0:

            true_ranges[i] = (
                candles[i]["high"]
                - candles[i]["low"]
            )

            continue

        high = candles[i]["high"]
        low = candles[i]["low"]

        previous_high = (
            candles[i - 1]["high"]
        )

        previous_low = (
            candles[i - 1]["low"]
        )

        previous_close = (
            candles[i - 1]["close"]
        )

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

        upward_move = (
            high
            - previous_high
        )

        downward_move = (
            previous_low
            - low
        )

        if (
            upward_move
            > downward_move
            and upward_move > 0
        ):

            plus_dm[i] = (
                upward_move
            )

        if (
            downward_move
            > upward_move
            and downward_move > 0
        ):

            minus_dm[i] = (
                downward_move
            )

    atr = [None] * count
    smoothed_plus_dm = [
        None
    ] * count
    smoothed_minus_dm = [
        None
    ] * count

    atr[period - 1] = (
        sum(
            true_ranges[
                :period
            ]
        )
        / period
    )

    smoothed_plus_dm[
        period - 1
    ] = (
        sum(
            plus_dm[:period]
        )
        / period
    )

    smoothed_minus_dm[
        period - 1
    ] = (
        sum(
            minus_dm[:period]
        )
        / period
    )

    for i in range(
        period,
        count,
    ):

        atr[i] = (
            (
                atr[i - 1]
                * (period - 1)
            )
            + true_ranges[i]
        ) / period

        smoothed_plus_dm[i] = (
            (
                smoothed_plus_dm[
                    i - 1
                ]
                * (period - 1)
            )
            + plus_dm[i]
        ) / period

        smoothed_minus_dm[i] = (
            (
                smoothed_minus_dm[
                    i - 1
                ]
                * (period - 1)
            )
            + minus_dm[i]
        ) / period

    dx = [None] * count

    for i in range(
        period - 1,
        count,
    ):

        if (
            atr[i] is None
            or atr[i] == 0
        ):
            continue

        plus_di = (
            100
            * smoothed_plus_dm[i]
            / atr[i]
        )

        minus_di = (
            100
            * smoothed_minus_dm[i]
            / atr[i]
        )

        denominator = (
            plus_di
            + minus_di
        )

        if denominator == 0:

            dx[i] = 0.0

        else:

            dx[i] = (
                100
                * abs(
                    plus_di
                    - minus_di
                )
                / denominator
            )

    first_dx = None

    for i, value in enumerate(dx):

        if value is not None:

            first_dx = i
            break

    if first_dx is None:
        return result

    if (
        first_dx + period
        > count
    ):
        return result

    first_window = dx[
        first_dx:
        first_dx + period
    ]

    if any(
        value is None
        for value in first_window
    ):
        return result

    current_adx = (
        sum(first_window)
        / period
    )

    result[
        first_dx + period - 1
    ] = current_adx

    for i in range(
        first_dx + period,
        count,
    ):

        if dx[i] is None:
            continue

        current_adx = (
            (
                current_adx
                * (period - 1)
            )
            + dx[i]
        ) / period

        result[i] = current_adx

    return result
# =========================================================
# Feature calculation
# =========================================================

def calculate_features(
    candles,
    symbol,
    timeframe,
):
    """
    Calculate all currently implemented features.

    Rules:
    - only closed candles are used
    - no future candle is used
    - indicators are calculated sequentially
    - Phase 2A-5 features are included
    """

    closed = [
        candle
        for candle in candles
        if is_closed_candle(candle)
    ]

    if not closed:
        return []

    count = len(closed)

    print(
        f"Building features: "
        f"{symbol} {timeframe}"
    )

    print(
        f"Closed candles available: "
        f"{count}"
    )

    closes = [
        candle["close"]
        for candle in closed
    ]

    highs = [
        candle["high"]
        for candle in closed
    ]

    lows = [
        candle["low"]
        for candle in closed
    ]

    volumes = [
        candle["volume"]
        for candle in closed
    ]

    # -----------------------------------------------------
    # Returns
    # -----------------------------------------------------

    returns = {}

    for period in (
        1,
        3,
        5,
        10,
    ):

        result = [
            None
            for _ in range(count)
        ]

        for i in range(
            period,
            count,
        ):

            previous = closes[
                i - period
            ]

            if (
                previous is None
                or previous == 0
            ):
                continue

            result[i] = (
                closes[i]
                - previous
            ) / previous

        returns[period] = result

    # -----------------------------------------------------
    # Moving averages
    # -----------------------------------------------------

    sma20 = rolling_mean(
        closes,
        20,
    )

    sma50 = rolling_mean(
        closes,
        50,
    )

    sma100 = rolling_mean(
        closes,
        100,
    )

    sma200 = rolling_mean(
        closes,
        200,
    )

    ema20 = ema_series(
        closes,
        20,
    )

    ema50 = ema_series(
        closes,
        50,
    )

    ema100 = ema_series(
        closes,
        100,
    )

    ema200 = ema_series(
        closes,
        200,
    )

    print("Moving averages calculated.")

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

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

    print("RSI calculated.")

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    (
        macd,
        macd_signal,
        macd_histogram,
    ) = macd_series(
        closes
    )

    print("MACD calculated.")

    # -----------------------------------------------------
    # Stochastic
    # -----------------------------------------------------

    (
        stochastic_k,
        stochastic_d,
    ) = stochastic_series(
        closed,
        14,
        3,
    )

    print("Stochastic calculated.")

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    adx = adx_series(
        closed,
        14,
    )

    print("ADX calculated.")

    # -----------------------------------------------------
    # ATR
    # -----------------------------------------------------

    atr = atr_series(
        closed,
        14,
    )

    atr_percent = [
        ratio(
            atr[i],
            closes[i],
        )
        for i in range(count)
    ]

    print("ATR calculated.")

    # -----------------------------------------------------
    # ATR MA20
    # -----------------------------------------------------

    atr_ma20 = rolling_mean(
        atr,
        20,
    )

    atr_to_atr_ma20 = [
        ratio(
            atr[i],
            atr_ma20[i],
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Bollinger Bands
    # -----------------------------------------------------

    bollinger_middle = sma20

    bollinger_std = rolling_std(
        closes,
        20,
    )

    bollinger_upper = [
        None
        for _ in range(count)
    ]

    bollinger_lower = [
        None
        for _ in range(count)
    ]

    bollinger_width = [
        None
        for _ in range(count)
    ]

    for i in range(count):

        middle = (
            bollinger_middle[i]
        )

        std = (
            bollinger_std[i]
        )

        if (
            middle is None
            or std is None
        ):
            continue

        upper = (
            middle
            + 2 * std
        )

        lower = (
            middle
            - 2 * std
        )

        bollinger_upper[i] = upper
        bollinger_lower[i] = lower

        if middle != 0:

            bollinger_width[i] = (
                upper - lower
            ) / middle

    bollinger_width_ma20 = (
        rolling_mean(
            bollinger_width,
            20,
        )
    )

    print(
        "Bollinger Bands calculated."
    )

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    volume_ma = rolling_mean(
        volumes,
        20,
    )

    volume_ratio = [
        ratio(
            volumes[i],
            volume_ma[i],
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Price structure
    #
    # Important:
    # Use PREVIOUS 20 candles.
    # Current candle is excluded.
    # This prevents look-ahead contamination.
    # -----------------------------------------------------

    support_price = [
        None
        for _ in range(count)
    ]

    resistance_price = [
        None
        for _ in range(count)
    ]

    distance_to_support = [
        None
        for _ in range(count)
    ]

    distance_to_resistance = [
        None
        for _ in range(count)
    ]

    structure_period = 20

    for i in range(
        structure_period,
        count,
    ):

        previous_lows = lows[
            i - structure_period:
            i
        ]

        previous_highs = highs[
            i - structure_period:
            i
        ]

        support = min(
            previous_lows
        )

        resistance = max(
            previous_highs
        )

        support_price[i] = (
            support
        )

        resistance_price[i] = (
            resistance
        )

        if (
            closes[i] is not None
            and closes[i] != 0
        ):

            distance_to_support[i] = (
                closes[i] - support
            ) / closes[i]

            distance_to_resistance[i] = (
                resistance - closes[i]
            ) / closes[i]

    # -----------------------------------------------------
    # Phase 2A-5 precomputed changes
    #
    # IMPORTANT:
    # Everything here is calculated once.
    #
    # The old implementation rebuilt the entire ATR%
    # array inside every candle iteration.
    # That created an O(n²) bottleneck.
    # -----------------------------------------------------

    rsi6_change = [
        change_value(
            rsi6,
            i,
        )
        for i in range(count)
    ]

    rsi12_change = [
        change_value(
            rsi12,
            i,
        )
        for i in range(count)
    ]

    rsi24_change = [
        change_value(
            rsi24,
            i,
        )
        for i in range(count)
    ]

    rsi6_acceleration = [
        acceleration_value(
            rsi6,
            i,
        )
        for i in range(count)
    ]

    rsi12_acceleration = [
        acceleration_value(
            rsi12,
            i,
        )
        for i in range(count)
    ]

    rsi24_acceleration = [
        acceleration_value(
            rsi24,
            i,
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # MACD changes
    # -----------------------------------------------------

    macd_change = [
        change_value(
            macd,
            i,
        )
        for i in range(count)
    ]

    macd_signal_change = [
        change_value(
            macd_signal,
            i,
        )
        for i in range(count)
    ]

    macd_histogram_change = [
        change_value(
            macd_histogram,
            i,
        )
        for i in range(count)
    ]

    macd_acceleration = [
        acceleration_value(
            macd,
            i,
        )
        for i in range(count)
    ]

    macd_histogram_acceleration = [
        acceleration_value(
            macd_histogram,
            i,
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # ATR changes
    # -----------------------------------------------------

    atr_change = [
        change_value(
            atr,
            i,
        )
        for i in range(count)
    ]

    # FIX:
    # Calculate ATR% once for the entire series.
    # Do NOT rebuild it inside the candle loop.

    atr_percent_change = [
        change_value(
            atr_percent,
            i,
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Bollinger changes
    # -----------------------------------------------------

    bollinger_width_change = [
        change_value(
            bollinger_width,
            i,
        )
        for i in range(count)
    ]

    bollinger_width_to_ma20 = [
        ratio(
            bollinger_width[i],
            bollinger_width_ma20[i],
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Trend ratios
    # -----------------------------------------------------

    price_sma20_ratio = [
        ratio(
            closes[i],
            sma20[i],
        )
        for i in range(count)
    ]

    price_sma50_ratio = [
        ratio(
            closes[i],
            sma50[i],
        )
        for i in range(count)
    ]

    price_sma100_ratio = [
        ratio(
            closes[i],
            sma100[i],
        )
        for i in range(count)
    ]

    price_sma200_ratio = [
        ratio(
            closes[i],
            sma200[i],
        )
        for i in range(count)
    ]

    price_ema20_ratio = [
        ratio(
            closes[i],
            ema20[i],
        )
        for i in range(count)
    ]

    price_ema50_ratio = [
        ratio(
            closes[i],
            ema50[i],
        )
        for i in range(count)
    ]

    price_ema100_ratio = [
        ratio(
            closes[i],
            ema100[i],
        )
        for i in range(count)
    ]

    price_ema200_ratio = [
        ratio(
            closes[i],
            ema200[i],
        )
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Moving average slopes
    # -----------------------------------------------------

    sma20_slope = [
        percent_change(
            sma20[i],
            sma20[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    sma50_slope = [
        percent_change(
            sma50[i],
            sma50[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    sma100_slope = [
        percent_change(
            sma100[i],
            sma100[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    sma200_slope = [
        percent_change(
            sma200[i],
            sma200[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    ema20_slope = [
        percent_change(
            ema20[i],
            ema20[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    ema50_slope = [
        percent_change(
            ema50[i],
            ema50[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    ema100_slope = [
        percent_change(
            ema100[i],
            ema100[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    ema200_slope = [
        percent_change(
            ema200[i],
            ema200[i - 1],
        )
        if i >= 1
        else None
        for i in range(count)
    ]

    # -----------------------------------------------------
    # Trend alignment
    # -----------------------------------------------------

    trend_alignment_score = [
        None
        for _ in range(count)
    ]

    for i in range(count):

        values = []

        if (
            closes[i] is not None
            and sma20[i] is not None
        ):

            values.append(
                1
                if closes[i] > sma20[i]
                else -1
            )

        if (
            sma20[i] is not None
            and sma50[i] is not None
        ):

            values.append(
                1
                if sma20[i] > sma50[i]
                else -1
            )

        if (
            sma50[i] is not None
            and sma100[i] is not None
        ):

            values.append(
                1
                if sma50[i] > sma100[i]
                else -1
            )

        if (
            sma100[i] is not None
            and sma200[i] is not None
        ):

            values.append(
                1
                if sma100[i] > sma200[i]
                else -1
            )

        if values:

            trend_alignment_score[i] = (
                sum(values)
                / len(values)
            )

    # -----------------------------------------------------
    # Volatility regime
    # -----------------------------------------------------

    volatility_regime = [
        None
        for _ in range(count)
    ]

    for i in range(count):

        value = (
            atr_to_atr_ma20[i]
        )

        if value is None:
            continue

        if value >= 1.2:

            volatility_regime[i] = (
                "VOLATILITY_EXPANSION"
            )

        elif value <= 0.8:

            volatility_regime[i] = (
                "VOLATILITY_CONTRACTION"
            )

        else:

            volatility_regime[i] = (
                "VOLATILITY_NORMAL"
            )

    print(
        "Phase 2A-5 arrays calculated."
    )

    # -----------------------------------------------------
    # Build feature rows
    # -----------------------------------------------------

    features = []

    for i, candle in enumerate(
        closed
    ):

        if (
            i > 0
            and i % PROGRESS_EVERY == 0
        ):

            print(
                f"Feature progress: "
                f"{i} / {count}"
            )

        price = closes[i]

        candle_open = (
            candle["open"]
        )

        candle_high = (
            candle["high"]
        )

        candle_low = (
            candle["low"]
        )

        candle_close = (
            candle["close"]
        )

        # -------------------------------------------------
        # Candle structure
        # -------------------------------------------------

        candle_body = abs(
            candle_close
            - candle_open
        )

        upper_wick = max(
            0,
            candle_high
            - max(
                candle_open,
                candle_close,
            ),
        )

        lower_wick = max(
            0,
            min(
                candle_open,
                candle_close,
            )
            - candle_low,
        )

        # -------------------------------------------------
        # Feature row
        # -------------------------------------------------

        feature = {

            "symbol_id": candle.get(
                "symbol_id"
            ),

            "timeframe": timeframe,

            "timestamp": ms_to_iso(
                candle["close_time"]
            ),

            "price": price,

            # ---------------------------------------------
            # Returns
            # ---------------------------------------------

            "return_1": returns[1][i],
            "return_3": returns[3][i],
            "return_5": returns[5][i],
            "return_10": returns[10][i],

            # ---------------------------------------------
            # SMA
            # ---------------------------------------------

            "sma_20": sma20[i],
            "sma_50": sma50[i],
            "sma_100": sma100[i],
            "sma_200": sma200[i],

            # ---------------------------------------------
            # EMA
            # ---------------------------------------------

            "ema_20": ema20[i],
            "ema_50": ema50[i],
            "ema_100": ema100[i],
            "ema_200": ema200[i],

            # ---------------------------------------------
            # RSI
            # ---------------------------------------------

            "rsi_6": rsi6[i],
            "rsi_12": rsi12[i],
            "rsi_24": rsi24[i],

            # ---------------------------------------------
            # MACD
            # ---------------------------------------------

            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram": (
                macd_histogram[i]
            ),

            # ---------------------------------------------
            # Stochastic
            # ---------------------------------------------

            "stochastic_k": (
                stochastic_k[i]
            ),

            "stochastic_d": (
                stochastic_d[i]
            ),

            # ---------------------------------------------
            # ADX
            # ---------------------------------------------

            "adx": adx[i],

            # ---------------------------------------------
            # ATR
            # ---------------------------------------------

            "atr": atr[i],

            "atr_percent": (
                atr_percent[i]
            ),

            # ---------------------------------------------
            # Bollinger
            # ---------------------------------------------

            "bollinger_upper": (
                bollinger_upper[i]
            ),

            "bollinger_middle": (
                bollinger_middle[i]
            ),

            "bollinger_lower": (
                bollinger_lower[i]
            ),

            "bollinger_width": (
                bollinger_width[i]
            ),

            # ---------------------------------------------
            # Volume
            # ---------------------------------------------

            "volume": volumes[i],

            "volume_ma": (
                volume_ma[i]
            ),

            "volume_ratio": (
                volume_ratio[i]
            ),

            # ---------------------------------------------
            # Candle structure
            # ---------------------------------------------

            "candle_body": (
                candle_body
            ),

            "upper_wick": (
                upper_wick
            ),

            "lower_wick": (
                lower_wick
            ),

            # ---------------------------------------------
            # Price structure
            # ---------------------------------------------

            "support_price": (
                support_price[i]
            ),

            "resistance_price": (
                resistance_price[i]
            ),

            "distance_to_support": (
                distance_to_support[i]
            ),

            "distance_to_resistance": (
                distance_to_resistance[i]
            ),

            # ---------------------------------------------
            # Futures/context fields
            #
            # Dedicated pipelines will populate these
            # later.
            # ---------------------------------------------

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

            # ---------------------------------------------
            # Phase 2A-5
            # ---------------------------------------------

            "price_sma20_ratio": (
                price_sma20_ratio[i]
            ),

            "price_sma50_ratio": (
                price_sma50_ratio[i]
            ),

            "price_sma100_ratio": (
                price_sma100_ratio[i]
            ),

            "price_sma200_ratio": (
                price_sma200_ratio[i]
            ),

            "price_ema20_ratio": (
                price_ema20_ratio[i]
            ),

            "price_ema50_ratio": (
                price_ema50_ratio[i]
            ),

            "price_ema100_ratio": (
                price_ema100_ratio[i]
            ),

            "price_ema200_ratio": (
                price_ema200_ratio[i]
            ),

            "sma20_slope": (
                sma20_slope[i]
            ),

            "sma50_slope": (
                sma50_slope[i]
            ),

            "sma100_slope": (
                sma100_slope[i]
            ),

            "sma200_slope": (
                sma200_slope[i]
            ),

            "ema20_slope": (
                ema20_slope[i]
            ),

            "ema50_slope": (
                ema50_slope[i]
            ),

            "ema100_slope": (
                ema100_slope[i]
            ),

            "ema200_slope": (
                ema200_slope[i]
            ),

            "trend_alignment_score": (
                trend_alignment_score[i]
            ),

            "rsi6_change": (
                rsi6_change[i]
            ),

            "rsi12_change": (
                rsi12_change[i]
            ),

            "rsi24_change": (
                rsi24_change[i]
            ),

            "rsi6_acceleration": (
                rsi6_acceleration[i]
            ),

            "rsi12_acceleration": (
                rsi12_acceleration[i]
            ),

            "rsi24_acceleration": (
                rsi24_acceleration[i]
            ),

            "macd_change": (
                macd_change[i]
            ),

            "macd_signal_change": (
                macd_signal_change[i]
            ),

            "macd_histogram_change": (
                macd_histogram_change[i]
            ),

            "macd_acceleration": (
                macd_acceleration[i]
            ),

            "macd_histogram_acceleration": (
                macd_histogram_acceleration[i]
            ),

            "atr_change": (
                atr_change[i]
            ),

            "atr_percent_change": (
                atr_percent_change[i]
            ),

            "atr_ma20": (
                atr_ma20[i]
            ),

            "atr_to_atr_ma20": (
                atr_to_atr_ma20[i]
            ),

            "bollinger_width_change": (
                bollinger_width_change[i]
            ),

            "bollinger_width_ma20": (
                bollinger_width_ma20[i]
            ),

            "bollinger_width_to_ma20": (
                bollinger_width_to_ma20[i]
            ),

            "volatility_regime": (
                volatility_regime[i]
            ),
        }

        features.append(
            feature
        )

    print(
        f"Feature calculation complete: "
        f"{len(features)} rows"
    )

    return features
# =========================================================
# Supabase Feature Upsert
# =========================================================

def supabase_upsert_features(rows):
    if not rows:
        return 0

    response = supabase_request(
        "POST",
        "/rest/v1/features",
        params={
            "on_conflict": (
                "symbol_id,timeframe,timestamp"
            ),
        },
        body=rows,
        headers={
            "Prefer": (
                "resolution=merge-duplicates,"
                "return=minimal"
            ),
        },
    )

    return len(rows)


# =========================================================
# Process one symbol / timeframe
# =========================================================

def process_symbol_timeframe(
    symbol,
    timeframe,
):
    symbol_id = symbol["id"]
    symbol_name = symbol["symbol"]

    print()
    print(
        "----------------------------------------"
    )
    print(
        f"Processing: "
        f"{symbol_name} {timeframe}"
    )
    print(
        "----------------------------------------"
    )

    # -----------------------------------------------------
    # Load candles
    # -----------------------------------------------------

    rows = get_all_candles(
        symbol_id,
        timeframe,
    )

    if not rows:
        print(
            "No candles found."
        )
        return 0

    candles = parse_candles(
        rows,
        symbol_id,
    )

    # Add symbol_id to every candle


    closed_count = sum(
        1
        for candle in candles
        if is_closed_candle(candle)
    )

    print(
        f"Closed candles: "
        f"{closed_count}"
    )

    if closed_count == 0:
        print(
            "No closed candles."
        )
        return 0

    # -----------------------------------------------------
    # Calculate features
    #
    # We calculate the complete historical sequence
    # because indicators such as EMA / RSI / ATR require
    # previous candles.
    #
    # Phase 2A-5 has been rewritten so the expensive
    # calculations are performed once instead of once
    # per candle.
    # -----------------------------------------------------

    start_time = time.time()

    features = calculate_features(
        candles,
        symbol_name,
        timeframe,
    )

    elapsed = (
        time.time()
        - start_time
    )

    print(
        f"Calculated features: "
        f"{len(features)}"
    )

    print(
        f"Calculation time: "
        f"{elapsed:.2f} sec"
    )

    if not features:
        print(
            "No features calculated."
        )
        return 0

    # -----------------------------------------------------
    # Incremental mode
    # -----------------------------------------------------

    if not FORCE_HISTORICAL_BACKFILL:

        latest_timestamp = (
            get_latest_feature_timestamp(
                symbol_id,
                timeframe,
            )
        )

        if latest_timestamp is not None:

            original_count = len(
                features
            )

            filtered_features = []

            for row in features:

                row_timestamp = (
                    iso_to_ms(
                        row["timestamp"]
                    )
                )

                if (
                    row_timestamp
                    > latest_timestamp
                ):
                    filtered_features.append(
                        row
                    )

            features = filtered_features

            print(
                f"Existing features: "
                f"{original_count - len(features)}"
            )

            print(
                f"New features: "
                f"{len(features)}"
            )

        else:

            print(
                "No existing features "
                "found."
            )

            print(
                f"Writing all "
                f"{len(features)} "
                f"historical features."
            )

    # -----------------------------------------------------
    # Historical backfill mode
    # -----------------------------------------------------

    else:

        print()
        print(
            "FORCE_HISTORICAL_BACKFILL=True"
        )

        print(
            "Writing full historical "
            "feature set."
        )

        print(
            f"Historical features: "
            f"{len(features)}"
        )

    if not features:

        print(
            "No new features to write."
        )

        return 0

    # -----------------------------------------------------
    # Batch upsert
    # -----------------------------------------------------

    total_written = 0

    total_batches = (
        (
            len(features)
            + WRITE_BATCH_SIZE
            - 1
        )
        // WRITE_BATCH_SIZE
    )

    for start in range(
        0,
        len(features),
        WRITE_BATCH_SIZE,
    ):

        batch = features[
            start:
            start + WRITE_BATCH_SIZE
        ]

        batch_number = (
            start // WRITE_BATCH_SIZE
        ) + 1

        written = (
            supabase_upsert_features(
                batch
            )
        )

        total_written += written

        print(
            f"Batch "
            f"{batch_number}/"
            f"{total_batches}: "
            f"{written} rows | "
            f"Total: "
            f"{total_written}"
        )

    print()
    print(
        f"Completed: "
        f"{symbol_name} "
        f"{timeframe}"
    )

    print(
        f"Written: "
        f"{total_written}"
    )

    return total_written


# =========================================================
# Main
# =========================================================

def main():

    print()
    print(
        "========================================"
    )
    print(
        "FEATURE ENGINE START"
    )
    print(
        "========================================"
    )
    print()

    # -----------------------------------------------------
    # Mode
    # -----------------------------------------------------

    if FORCE_HISTORICAL_BACKFILL:

        print(
            "WARNING:"
        )

        print(
            "FORCE_HISTORICAL_BACKFILL=True"
        )

        print(
            "All historical features "
            "will be recalculated."
        )

        print()

    else:

        print(
            "Incremental mode enabled."
        )

        print()

    # -----------------------------------------------------
    # Get active symbols
    # -----------------------------------------------------

    symbols = get_active_symbols()

    if not symbols:

        print(
            "No active symbols found."
        )

        return

    print(
        f"Active symbols: "
        f"{len(symbols)}"
    )

    print()

    # -----------------------------------------------------
    # Process all symbols / timeframes
    # -----------------------------------------------------

    total_written = 0

    total_jobs = 0

    failed_jobs = 0

    overall_start = time.time()

    for symbol in symbols:

        symbol_name = (
            symbol["symbol"]
        )

        for timeframe in TIMEFRAMES:

            total_jobs += 1

            try:

                written = (
                    process_symbol_timeframe(
                        symbol,
                        timeframe,
                    )
                )

                total_written += written

            except Exception as exc:

                failed_jobs += 1

                print()
                print(
                    "ERROR:"
                )

                print(
                    f"{symbol_name} "
                    f"{timeframe}"
                )

                print(
                    repr(exc)
                )

                print()

                # Continue with the next
                # symbol/timeframe.
                continue

    overall_elapsed = (
        time.time()
        - overall_start
    )

    # -----------------------------------------------------
    # Final summary
    # -----------------------------------------------------

    print()

    print(
        "========================================"
    )

    print(
        "FEATURE ENGINE COMPLETE"
    )

    print(
        "========================================"
    )

    print(
        f"Total jobs: "
        f"{total_jobs}"
    )

    print(
        f"Failed jobs: "
        f"{failed_jobs}"
    )

    print(
        f"Total written: "
        f"{total_written}"
    )

    print(
        f"Total runtime: "
        f"{overall_elapsed:.2f} sec"
    )

    print()

    if failed_jobs == 0:

        print(
            "OVERALL: PASS"
        )

    else:

        print(
            "OVERALL: FAIL"
        )

    print()


# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    main()
