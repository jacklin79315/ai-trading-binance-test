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


# =========================================================
# IMPORTANT
# =========================================================
# True:
#   完整重算並回補所有歷史 Feature
#
# False:
#   正常增量模式，只處理最新 Feature
#
# 歷史回補完成後一定要改回 False。
# =========================================================

FORCE_HISTORICAL_BACKFILL = False


# =========================================================
# General configuration
# =========================================================

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

WRITE_BATCH_SIZE = 500
READ_PAGE_SIZE = 1000


# =========================================================
# Supabase HTTP helpers
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
        data = json.dumps(body).encode("utf-8")

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
# Utility functions
# =========================================================

def safe_float(value):
    if value is None:
        return None

    try:
        x = float(value)

        if not math.isfinite(x):
            return None

        return x

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
    dt = datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    )

    return dt.isoformat().replace(
        "+00:00",
        "Z",
    )


def is_finite(value):
    if value is None:
        return False

    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clean_number(value):
    value = safe_float(value)

    if value is None:
        return None

    return value


# =========================================================
# Supabase table helpers
# =========================================================

def get_active_symbols():
    rows = supabase_request(
        "GET",
        "/rest/v1/symbols",
        params={
            "select": "id,symbol,market_type,status",
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
    """
    Read all candles for one symbol/timeframe.

    Uses pagination because Supabase may limit
    the number of returned rows.
    """

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
                "order": "open_time.desc",
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

    all_rows.sort(
        key=lambda x: iso_to_ms(
            x["open_time"]
        )
    )

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

def parse_candles(rows):
    candles = []

    for row in rows:

        open_time = iso_to_ms(
            row["open_time"]
        )

        close_time = iso_to_ms(
            row["close_time"]
        )

        candles.append(
            {
                "open_time": open_time,
                "close_time": close_time,
                "open": safe_float(row["open"]),
                "high": safe_float(row["high"]),
                "low": safe_float(row["low"]),
                "close": safe_float(row["close"]),
                "volume": safe_float(row["volume"]),
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
# Math helpers
# =========================================================

def mean(values):
    values = [
        x for x in values
        if x is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def sma(values, period):
    if len(values) < period:
        return None

    window = values[-period:]

    if any(x is None for x in window):
        return None

    return sum(window) / period


def ema_series(values, period):
    result = [
        None
        for _ in values
    ]

    if len(values) < period:
        return result

    initial = values[:period]

    if any(x is None for x in initial):
        return result

    ema = sum(initial) / period

    result[period - 1] = ema

    multiplier = 2.0 / (period + 1)

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


def rsi_series(values, period):
    result = [
        None
        for _ in values
    ]

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, period + 1):

        diff = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = (
            100
            - 100 / (1 + rs)
        )

    for i in range(
        period + 1,
        len(values),
    ):

        diff = (
            values[i]
            - values[i - 1]
        )

        gain = max(diff, 0)
        loss = max(-diff, 0)

        avg_gain = (
            avg_gain * (period - 1)
            + gain
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + loss
        ) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = (
                100
                - 100 / (1 + rs)
            )

    return result


def true_range_series(candles):
    result = []

    previous_close = None

    for candle in candles:

        high = candle["high"]
        low = candle["low"]

        if high is None or low is None:
            result.append(None)
            continue

        if previous_close is None:

            tr = high - low

        else:

            tr = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )

        result.append(tr)

        previous_close = candle["close"]

    return result


def atr_series(candles, period):
    tr = true_range_series(candles)

    return ema_series(
        tr,
        period,
    )


def standard_deviation(values):
    values = [
        x for x in values
        if x is not None
    ]

    if not values:
        return None

    avg = sum(values) / len(values)

    variance = sum(
        (x - avg) ** 2
        for x in values
    ) / len(values)

    return math.sqrt(variance)


def stochastic_series(
    candles,
    period=14,
    smooth=3,
):
    k_values = [
        None
        for _ in candles
    ]

    for i in range(
        period - 1,
        len(candles),
    ):

        window = candles[
            i - period + 1:
            i + 1
        ]

        highs = [
            x["high"]
            for x in window
            if x["high"] is not None
        ]

        lows = [
            x["low"]
            for x in window
            if x["low"] is not None
        ]

        if not highs or not lows:
            continue

        highest = max(highs)
        lowest = min(lows)

        close = candles[i]["close"]

        if highest == lowest:
            k = 50.0
        else:
            k = (
                (close - lowest)
                / (highest - lowest)
                * 100
            )

        k_values[i] = k

    d_values = [
        None
        for _ in candles
    ]

    for i in range(
        smooth - 1,
        len(k_values),
    ):

        window = k_values[
            i - smooth + 1:
            i + 1
        ]

        if any(
            x is None
            for x in window
        ):
            continue

        d_values[i] = (
            sum(window)
            / smooth
        )

    return k_values, d_values


def adx_series(
    candles,
    period=14,
):
    """
    Simplified Wilder-style ADX calculation.
    """

    if len(candles) < period * 2:
        return [
            None
            for _ in candles
        ]

    tr = []
    plus_dm = []
    minus_dm = []

    for i in range(
        len(candles)
    ):

        if i == 0:

            tr.append(
                candles[i]["high"]
                - candles[i]["low"]
            )

            plus_dm.append(0.0)
            minus_dm.append(0.0)
            continue

        high = candles[i]["high"]
        low = candles[i]["low"]

        prev_high = candles[i - 1]["high"]
        prev_low = candles[i - 1]["low"]
        prev_close = candles[i - 1]["close"]

        current_tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        up_move = high - prev_high
        down_move = prev_low - low

        if (
            up_move > down_move
            and up_move > 0
        ):
            pdm = up_move
        else:
            pdm = 0.0

        if (
            down_move > up_move
            and down_move > 0
        ):
            mdm = down_move
        else:
            mdm = 0.0

        tr.append(current_tr)
        plus_dm.append(pdm)
        minus_dm.append(mdm)

    atr = [
        None
        for _ in candles
    ]

    p_dm = [
        None
        for _ in candles
    ]

    m_dm = [
        None
        for _ in candles
    ]

    if len(candles) >= period:

        atr[period - 1] = (
            sum(tr[:period])
            / period
        )

        p_dm[period - 1] = (
            sum(plus_dm[:period])
            / period
        )

        m_dm[period - 1] = (
            sum(minus_dm[:period])
            / period
        )

        for i in range(
            period,
            len(candles),
        ):

            atr[i] = (
                (
                    atr[i - 1]
                    * (period - 1)
                )
                + tr[i]
            ) / period

            p_dm[i] = (
                (
                    p_dm[i - 1]
                    * (period - 1)
                )
                + plus_dm[i]
            ) / period

            m_dm[i] = (
                (
                    m_dm[i - 1]
                    * (period - 1)
                )
                + minus_dm[i]
            ) / period

    dx = [
        None
        for _ in candles
    ]

    for i in range(
        len(candles)
    ):

        if (
            atr[i] is None
            or atr[i] == 0
        ):
            continue

        plus_di = (
            100
            * p_dm[i]
            / atr[i]
        )

        minus_di = (
            100
            * m_dm[i]
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

    adx = [
        None
        for _ in candles
    ]

    valid_dx = [
        x for x in dx
        if x is not None
    ]

    if len(valid_dx) < period:
        return adx

    first_index = None

    for i, value in enumerate(dx):
        if value is not None:
            first_index = i
            break

    if first_index is None:
        return adx

    initial_end = (
        first_index + period
    )

    if initial_end > len(dx):
        return adx

    initial = dx[
        first_index:
        initial_end
    ]

    if any(
        x is None
        for x in initial
    ):
        return adx

    current = (
        sum(initial)
        / period
    )

    adx[
        initial_end - 1
    ] = current

    for i in range(
        initial_end,
        len(dx),
    ):

        if dx[i] is None:
            continue

        current = (
            (
                current
                * (period - 1)
            )
            + dx[i]
        ) / period

        adx[i] = current

    return adx


# =========================================================
# Feature helper functions
# =========================================================

def previous_value(
    series,
    index,
):
    if index <= 0:
        return None

    return series[index - 1]


def change_value(
    series,
    index,
):
    if index <= 0:
        return None

    current = series[index]
    previous = series[index - 1]

    if current is None or previous is None:
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


# =========================================================
# MACD
# =========================================================

def calculate_macd(
    closes,
):
    ema12 = ema_series(
        closes,
        12,
    )

    ema26 = ema_series(
        closes,
        26,
    )

    macd = [
        None
        for _ in closes
    ]

    for i in range(
        len(closes)
    ):

        if (
            ema12[i] is None
            or ema26[i] is None
        ):
            continue

        macd[i] = (
            ema12[i]
            - ema26[i]
        )

    valid_macd = [
        x for x in macd
        if x is not None
    ]

    signal_raw = ema_series(
        valid_macd,
        9,
    )

    signal = [
        None
        for _ in closes
    ]

    valid_index = 0

    for i in range(
        len(closes)
    ):

        if macd[i] is None:
            continue

        if (
            valid_index
            < len(signal_raw)
        ):
            signal[i] = signal_raw[
                valid_index
            ]

        valid_index += 1

    histogram = [
        None
        for _ in closes
    ]

    for i in range(
        len(closes)
    ):

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

    Important:
    - only closed candles are used
    - all indicators use data up to current candle
    - no future candle is used
    """

    closed = [
        candle
        for candle in candles
        if is_closed_candle(candle)
    ]

    if not closed:
        return []

    closes = [
        x["close"]
        for x in closed
    ]

    volumes = [
        x["volume"]
        for x in closed
    ]

    highs = [
        x["high"]
        for x in closed
    ]

    lows = [
        x["low"]
        for x in closed
    ]

    # -----------------------------------------------------
    # Returns
    # -----------------------------------------------------

    returns = {}

    for period in [
        1,
        3,
        5,
        10,
    ]:

        arr = [
            None
            for _ in closes
        ]

        for i in range(
            period,
            len(closes),
        ):

            previous = closes[
                i - period
            ]

            if previous == 0:
                continue

            arr[i] = (
                closes[i]
                - previous
            ) / previous

        returns[period] = arr

    # -----------------------------------------------------
    # Moving averages
    # -----------------------------------------------------

    sma20 = [
        sma(closes, 20)
        if i >= 19
        else None
        for i in range(
            len(closes)
        )
    ]

    sma50 = [
        sma(closes, 50)
        if i >= 49
        else None
        for i in range(
            len(closes)
        )
    ]

    sma100 = [
        sma(closes, 100)
        if i >= 99
        else None
        for i in range(
            len(closes)
        )
    ]

    sma200 = [
        sma(closes, 200)
        if i >= 199
        else None
        for i in range(
            len(closes)
        )
    ]

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

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    (
        macd,
        macd_signal,
        macd_histogram,
    ) = calculate_macd(
        closes
    )

    # -----------------------------------------------------
    # Stochastic
    # -----------------------------------------------------

    stochastic_k, stochastic_d = (
        stochastic_series(
            closed,
            14,
            3,
        )
    )

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    adx = adx_series(
        closed,
        14,
    )

    # -----------------------------------------------------
    # ATR
    # -----------------------------------------------------

    atr = atr_series(
        closed,
        14,
    )

    # -----------------------------------------------------
    # Bollinger
    # -----------------------------------------------------

    bollinger_middle = sma20

    bollinger_upper = [
        None
        for _ in closes
    ]

    bollinger_lower = [
        None
        for _ in closes
    ]

    bollinger_width = [
        None
        for _ in closes
    ]

    for i in range(
        19,
        len(closes),
    ):

        window = closes[
            i - 19:
            i + 1
        ]

        std = standard_deviation(
            window
        )

        middle = sma20[i]

        if (
            std is None
            or middle is None
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

    # -----------------------------------------------------
    # Volume MA
    # -----------------------------------------------------

    volume_ma = [
        sma(volumes, 20)
        if i >= 19
        else None
        for i in range(
            len(volumes)
        )
    ]

    volume_ratio = [
        ratio(
            volumes[i],
            volume_ma[i],
        )
        for i in range(
            len(volumes)
        )
    ]

    # -----------------------------------------------------
    # Price structure
    # -----------------------------------------------------

    support_price = [
        None
        for _ in closes
    ]

    resistance_price = [
        None
        for _ in closes
    ]

    distance_to_support = [
        None
        for _ in closes
    ]

    distance_to_resistance = [
        None
        for _ in closes
    ]

    structure_period = 20

    for i in range(
        structure_period,
        len(closes),
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

        support_price[i] = support
        resistance_price[i] = resistance

        if closes[i] != 0:

            distance_to_support[i] = (
                closes[i] - support
            ) / closes[i]

            distance_to_resistance[i] = (
                resistance - closes[i]
            ) / closes[i]

    # -----------------------------------------------------
    # ATR MA20
    # -----------------------------------------------------

    atr_ma20 = [
        sma(
            [
                x
                for x in atr[
                    max(
                        0,
                        i - 19,
                    ):
                    i + 1
                ]
            ],
            20,
        )
        if i >= 19
        else None
        for i in range(
            len(atr)
        )
    ]

    # -----------------------------------------------------
    # Bollinger width MA20
    # -----------------------------------------------------

    bollinger_width_ma20 = [
        None
        for _ in closes
    ]

    for i in range(
        19,
        len(closes),
    ):

        window = (
            bollinger_width[
                i - 19:
                i + 1
            ]
        )

        if any(
            x is None
            for x in window
        ):
            continue

        bollinger_width_ma20[i] = (
            sum(window) / 20
        )

    # -----------------------------------------------------
    # Build feature rows
    # -----------------------------------------------------

    features = []

    for i, candle in enumerate(
        closed
    ):

        price = closes[i]

        atr_value = atr[i]

        atr_percent = ratio(
            atr_value,
            price,
        )

        # ---------------------------------------------
        # Candle structure
        # ---------------------------------------------

        candle_open = candle["open"]
        candle_high = candle["high"]
        candle_low = candle["low"]
        candle_close = candle["close"]

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

        # ---------------------------------------------
        # Trend ratios
        # ---------------------------------------------

        price_sma20_ratio = ratio(
            price,
            sma20[i],
        )

        price_sma50_ratio = ratio(
            price,
            sma50[i],
        )

        price_sma100_ratio = ratio(
            price,
            sma100[i],
        )

        price_sma200_ratio = ratio(
            price,
            sma200[i],
        )

        price_ema20_ratio = ratio(
            price,
            ema20[i],
        )

        price_ema50_ratio = ratio(
            price,
            ema50[i],
        )

        price_ema100_ratio = ratio(
            price,
            ema100[i],
        )

        price_ema200_ratio = ratio(
            price,
            ema200[i],
        )

        # ---------------------------------------------
        # Moving average slopes
        # ---------------------------------------------

        sma20_slope = (
            percent_change(
                sma20[i],
                sma20[i - 1],
            )
            if i >= 1
            else None
        )

        sma50_slope = (
            percent_change(
                sma50[i],
                sma50[i - 1],
            )
            if i >= 1
            else None
        )

        sma100_slope = (
            percent_change(
                sma100[i],
                sma100[i - 1],
            )
            if i >= 1
            else None
        )

        sma200_slope = (
            percent_change(
                sma200[i],
                sma200[i - 1],
            )
            if i >= 1
            else None
        )

        ema20_slope = (
            percent_change(
                ema20[i],
                ema20[i - 1],
            )
            if i >= 1
            else None
        )

        ema50_slope = (
            percent_change(
                ema50[i],
                ema50[i - 1],
            )
            if i >= 1
            else None
        )

        ema100_slope = (
            percent_change(
                ema100[i],
                ema100[i - 1],
            )
            if i >= 1
            else None
        )

        ema200_slope = (
            percent_change(
                ema200[i],
                ema200[i - 1],
            )
            if i >= 1
            else None
        )

        # ---------------------------------------------
        # Trend alignment
        # ---------------------------------------------

        trend_values = []

        if (
            price is not None
            and sma20[i] is not None
        ):
            trend_values.append(
                1
                if price > sma20[i]
                else -1
            )

        if (
            sma20[i] is not None
            and sma50[i] is not None
        ):
            trend_values.append(
                1
                if sma20[i] > sma50[i]
                else -1
            )

        if (
            sma50[i] is not None
            and sma100[i] is not None
        ):
            trend_values.append(
                1
                if sma50[i] > sma100[i]
                else -1
            )

        if (
            sma100[i] is not None
            and sma200[i] is not None
        ):
            trend_values.append(
                1
                if sma100[i] > sma200[i]
                else -1
            )

        if trend_values:

            trend_alignment_score = (
                sum(trend_values)
                / len(trend_values)
            )

        else:
            trend_alignment_score = None

        # ---------------------------------------------
        # RSI change / acceleration
        # ---------------------------------------------

        rsi6_change = change_value(
            rsi6,
            i,
        )

        rsi12_change = change_value(
            rsi12,
            i,
        )

        rsi24_change = change_value(
            rsi24,
            i,
        )

        rsi6_acceleration = (
            acceleration_value(
                rsi6,
                i,
            )
        )

        rsi12_acceleration = (
            acceleration_value(
                rsi12,
                i,
            )
        )

        rsi24_acceleration = (
            acceleration_value(
                rsi24,
                i,
            )
        )

        # ---------------------------------------------
        # MACD change / acceleration
        # ---------------------------------------------

        macd_change = change_value(
            macd,
            i,
        )

        macd_signal_change = (
            change_value(
                macd_signal,
                i,
            )
        )

        macd_histogram_change = (
            change_value(
                macd_histogram,
                i,
            )
        )

        macd_acceleration = (
            acceleration_value(
                macd,
                i,
            )
        )

        macd_histogram_acceleration = (
            acceleration_value(
                macd_histogram,
                i,
            )
        )

        # ---------------------------------------------
        # ATR changes
        # ---------------------------------------------

        atr_change = change_value(
            atr,
            i,
        )

        atr_percent_change = (
            change_value(
                [
                    ratio(
                        atr[j],
                        closes[j],
                    )
                    for j in range(
                        len(closes)
                    )
                ],
                i,
            )
        )

        atr_to_atr_ma20 = ratio(
            atr[i],
            atr_ma20[i],
        )

        # ---------------------------------------------
        # Bollinger changes
        # ---------------------------------------------

        bollinger_width_change = (
            change_value(
                bollinger_width,
                i,
            )
        )

        bollinger_width_to_ma20 = (
            ratio(
                bollinger_width[i],
                bollinger_width_ma20[i],
            )
        )

        # ---------------------------------------------
        # Volatility regime
        # ---------------------------------------------

        volatility_regime = None

        if (
            atr_to_atr_ma20
            is not None
        ):

            if atr_to_atr_ma20 >= 1.2:

                volatility_regime = (
                    "VOLATILITY_EXPANSION"
                )

            elif atr_to_atr_ma20 <= 0.8:

                volatility_regime = (
                    "VOLATILITY_CONTRACTION"
                )

            else:

                volatility_regime = (
                    "VOLATILITY_NORMAL"
                )

        # ---------------------------------------------
        # Feature row
        # ---------------------------------------------

        feature = {
            "symbol_id": candle.get(
                "symbol_id"
            ),

            "timeframe": timeframe,

            "timestamp": ms_to_iso(
                candle["close_time"]
            ),

            "price": price,

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

            # Stochastic
            "stochastic_k": stochastic_k[i],
            "stochastic_d": stochastic_d[i],

            # ADX
            "adx": adx[i],

            # ATR
            "atr": atr_value,
            "atr_percent": atr_percent,

            # Bollinger
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

            # Volume
            "volume": volumes[i],
            "volume_ma": volume_ma[i],
            "volume_ratio": volume_ratio[i],

            # Candle
            "candle_body": candle_body,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,

            # Structure
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

            # Existing future/context fields
            # These are intentionally left null
            # until their dedicated pipelines
            # are implemented.
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

            # -----------------------------------------
            # Phase 2A-5
            # -----------------------------------------

            "price_sma20_ratio": (
                price_sma20_ratio
            ),
            "price_sma50_ratio": (
                price_sma50_ratio
            ),
            "price_sma100_ratio": (
                price_sma100_ratio
            ),
            "price_sma200_ratio": (
                price_sma200_ratio
            ),

            "price_ema20_ratio": (
                price_ema20_ratio
            ),
            "price_ema50_ratio": (
                price_ema50_ratio
            ),
            "price_ema100_ratio": (
                price_ema100_ratio
            ),
            "price_ema200_ratio": (
                price_ema200_ratio
            ),

            "sma20_slope": sma20_slope,
            "sma50_slope": sma50_slope,
            "sma100_slope": sma100_slope,
            "sma200_slope": sma200_slope,

            "ema20_slope": ema20_slope,
            "ema50_slope": ema50_slope,
            "ema100_slope": ema100_slope,
            "ema200_slope": ema200_slope,

            "trend_alignment_score": (
                trend_alignment_score
            ),

            "rsi6_change": rsi6_change,
            "rsi12_change": rsi12_change,
            "rsi24_change": rsi24_change,

            "rsi6_acceleration": (
                rsi6_acceleration
            ),
            "rsi12_acceleration": (
                rsi12_acceleration
            ),
            "rsi24_acceleration": (
                rsi24_acceleration
            ),

            "macd_change": macd_change,
            "macd_signal_change": (
                macd_signal_change
            ),
            "macd_histogram_change": (
                macd_histogram_change
            ),

            "macd_acceleration": (
                macd_acceleration
            ),
            "macd_histogram_acceleration": (
                macd_histogram_acceleration
            ),

            "atr_change": atr_change,
            "atr_percent_change": (
                atr_percent_change
            ),
            "atr_ma20": atr_ma20[i],
            "atr_to_atr_ma20": (
                atr_to_atr_ma20
            ),

            "bollinger_width_change": (
                bollinger_width_change
            ),
            "bollinger_width_ma20": (
                bollinger_width_ma20[i]
            ),
            "bollinger_width_to_ma20": (
                bollinger_width_to_ma20
            ),

            "volatility_regime": (
                volatility_regime
            ),
        }

        # Remove None symbol_id if necessary.
        feature["symbol_id"] = (
            candle.get(
                "symbol_id"
            )
        )

        features.append(
            feature
        )

    return features


# =========================================================
# Supabase Feature Upsert
# =========================================================

def supabase_upsert_features(
    rows
):
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
# Process one symbol/timeframe
# =========================================================

def process_symbol_timeframe(
    symbol,
    timeframe,
):
    symbol_id = symbol["id"]
    symbol_name = symbol["symbol"]

    print(
        f"Processing: "
        f"{symbol_name} "
        f"{timeframe}"
    )

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
        rows
    )

    # Add symbol_id to every candle
    for candle in candles:
        candle["symbol_id"] = symbol_id

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
    # Calculate full historical feature set
    # -----------------------------------------------------

    features = calculate_features(
        candles,
        symbol_name,
        timeframe,
    )

    print(
        f"Calculated features: "
        f"{len(features)}"
    )

    if not features:

        print(
            "No features calculated."
        )

        return 0

    # -----------------------------------------------------
    # Normal incremental mode
    # -----------------------------------------------------

    if not FORCE_HISTORICAL_BACKFILL:

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
                if iso_to_ms(
                    row["timestamp"]
                )
                > latest_timestamp
            ]

    # -----------------------------------------------------
    # Historical backfill mode
    # -----------------------------------------------------

    else:

        print(
            "FORCE_HISTORICAL_BACKFILL=True"
        )

        print(
            "Writing full historical "
            "feature set."
        )

    print(
        f"New features: "
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

    print(
        f"Completed: "
        f"{symbol_name} "
        f"{timeframe} | "
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

    total_written = 0
    total_jobs = 0
    failed_jobs = 0

    for symbol in symbols:

        symbol_name = symbol[
            "symbol"
        ]

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
                    f"ERROR: "
                    f"{symbol_name} "
                    f"{timeframe}"
                )

                print(
                    repr(exc)
                )

                print()

                # Continue with the next
                # symbol/timeframe instead
                # of terminating the entire job.
                continue

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
    print()


# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    main()
