import os
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

BINANCE_BASE = "https://data-api.binance.vision"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------
# 歷史目標
# ---------------------------------------------------------

TARGET_DAYS = {
    "5m": 365,
    "15m": 730,
    "1h": 1095,
    "4h": 1825,
    "1d": 2920,
}

INTERVAL_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

LIMIT = 1000


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

    with urlopen(request, timeout=30) as response:
        return json.loads(
            response.read().decode()
        )


def supabase_insert_candles(rows):
    if not rows:
        return 0

    url = (
        f"{SUPABASE_URL}/rest/v1/candles"
        f"?on_conflict=symbol_id,timeframe,open_time"
    )

    headers = {
        **HEADERS,
        "Prefer": "resolution=ignore-duplicates,return=minimal",
    }

    request = Request(
        url,
        headers=headers,
        data=json.dumps(rows).encode(),
        method="POST",
    )

    with urlopen(request, timeout=60) as response:
        response.read()

    return len(rows)


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


def get_earliest_candle(symbol_id, timeframe):

    rows = supabase_get(
        "candles",
        {
            "select": "open_time",
            "symbol_id": f"eq.{symbol_id}",
            "timeframe": f"eq.{timeframe}",
            "order": "open_time.asc",
            "limit": 1,
        },
    )

    if not rows:
        return None

    return rows[0]["open_time"]


def iso_to_ms(value):

    dt = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    return int(
        dt.timestamp() * 1000
    )


def ms_to_iso(ms):

    dt = datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    )

    return dt.isoformat()


def get_target_start_ms(timeframe):

    days = TARGET_DAYS[timeframe]

    now = datetime.now(timezone.utc)

    target = now - timedelta(
        days=days
    )

    return int(
        target.timestamp() * 1000
    )


def fetch_binance_klines(
    symbol,
    timeframe,
    start_ms,
    end_ms,
):

    params = urlencode(
        {
            "symbol": symbol,
            "interval": timeframe,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": LIMIT,
        }
    )

    url = (
        f"{BINANCE_BASE}/api/v3/klines"
        f"?{params}"
    )

    request = Request(
        url,
        headers={
            "User-Agent": "AI-Trading-System",
        },
        method="GET",
    )

    with urlopen(
        request,
        timeout=30,
    ) as response:

        return json.loads(
            response.read().decode()
        )


def convert_kline(kline, symbol_id, timeframe):

    return {
        "symbol_id": symbol_id,
        "timeframe": timeframe,

        "open_time": datetime.fromtimestamp(
            kline[0] / 1000,
            tz=timezone.utc,
        ).isoformat(),

        "open": float(kline[1]),
        "high": float(kline[2]),
        "low": float(kline[3]),
        "close": float(kline[4]),
        "volume": float(kline[5]),

        "close_time": datetime.fromtimestamp(
            kline[6] / 1000,
            tz=timezone.utc,
        ).isoformat(),

        "quote_volume": float(kline[7]),
        "trade_count": int(kline[8]),
        "taker_buy_base_volume": float(kline[9]),
        "taker_buy_quote_volume": float(kline[10]),
    }


def backfill_one(
    symbol,
    symbol_id,
    timeframe,
):

    print()
    print("=" * 60)
    print(
        f"{symbol} - {timeframe}"
    )
    print("=" * 60)

    target_start = get_target_start_ms(
        timeframe
    )

    earliest = get_earliest_candle(
        symbol_id,
        timeframe,
    )

    if earliest is None:

        print(
            "No existing candles."
        )

        # 如果完全沒有資料，
        # 先從 target_start 開始。
        cursor = target_start

    else:

        earliest_ms = iso_to_ms(
            earliest
        )

        print(
            f"Current earliest: "
            f"{earliest}"
        )

        if earliest_ms <= target_start:

            print(
                "Historical target already reached."
            )

            return 0

        # 往最早資料之前抓
        cursor = target_start

    total_inserted = 0
    total_batches = 0

    interval = INTERVAL_MS[
        timeframe
    ]

    # -----------------------------------------------------
    # 從 target_start 向未來抓到現有最早 candle 前
    # -----------------------------------------------------

    if earliest is not None:

        end_ms = (
            iso_to_ms(earliest)
            - interval
        )

    else:

        # 沒資料時，抓到現在
        end_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp() * 1000
        )

    while cursor < end_ms:

        batch_end = min(
            cursor + interval * (LIMIT - 1),
            end_ms,
        )

        try:

            klines = fetch_binance_klines(
                symbol,
                timeframe,
                cursor,
                batch_end,
            )

        except Exception as e:

            print(
                f"Binance request error: {e}"
            )

            time.sleep(5)
            continue

        if not klines:

            print(
                "No more candles returned."
            )

            break

        rows = []

        for kline in klines:

            open_ms = kline[0]

            # 不超過既定範圍
            if open_ms < target_start:
                continue

            if open_ms >= end_ms:
                continue

            rows.append(
                convert_kline(
                    kline,
                    symbol_id,
                    timeframe,
                )
            )

        if rows:

            supabase_insert_candles(
                rows
            )

            total_inserted += len(rows)
            total_batches += 1

            print(
                f"Batch {total_batches}: "
                f"{len(rows)} candles | "
                f"Total: {total_inserted}"
            )

        last_open_ms = klines[-1][0]

        next_cursor = (
            last_open_ms + interval
        )

        if next_cursor <= cursor:
            print(
                "Cursor did not advance."
            )
            break

        cursor = next_cursor

        time.sleep(0.15)

    print(
        f"Completed: {symbol} "
        f"{timeframe} | "
        f"Inserted/processed: "
        f"{total_inserted}"
    )

    return total_inserted


def main():

    print("=" * 60)
    print("HISTORICAL CANDLE BACKFILL")
    print("=" * 60)

    symbols = get_active_symbols()

    print(
        f"Active symbols: "
        f"{len(symbols)}"
    )

    total = 0

    for item in symbols:

        symbol = item["symbol"]
        symbol_id = item["id"]

        for timeframe in [
            "5m",
            "15m",
            "1h",
            "4h",
            "1d",
        ]:

            try:

                total += backfill_one(
                    symbol,
                    symbol_id,
                    timeframe,
                )

            except Exception as e:

                print()
                print(
                    f"ERROR: "
                    f"{symbol} - "
                    f"{timeframe}"
                )

                print(str(e))

    print()
    print("=" * 60)
    print("HISTORICAL BACKFILL COMPLETE")
    print("=" * 60)

    print(
        f"Total processed: {total}"
    )


if __name__ == "__main__":
    main()
