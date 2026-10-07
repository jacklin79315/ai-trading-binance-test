import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone


# ==========================================
# Configuration
# ==========================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

SYMBOL = "BTCUSDT"
EXCHANGE = "binance"
MARKET_TYPE = "spot"

TIMEFRAMES = [
    "5m",
    "15m",
    "1h",
    "4h",
    "1d",
]

KLINE_LIMIT = 1000


# ==========================================
# Supabase Request
# ==========================================

def supabase_request(method, endpoint, data=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    # 不再依賴 ignore-duplicates。
    # 我們會在寫入前先查詢最新資料，真正做到增量更新。
    if method == "POST":
        headers["Prefer"] = "return=representation"

    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            response_body = response.read().decode("utf-8")

            if not response_body:
                return []

            return json.loads(response_body)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print("Supabase HTTP Error:", e.code)
        print("Supabase response:", error_body)

        raise


# ==========================================
# Binance Klines
# ==========================================

def get_binance_klines(
    symbol,
    interval,
    limit=1000,
    start_time=None
):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    if start_time is not None:
        params["startTime"] = start_time

    query = urllib.parse.urlencode(params)

    url = f"{BINANCE_URL}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            data = response.read().decode("utf-8")

            return json.loads(data)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print("Binance HTTP Error:", e.code)
        print("Binance response:", error_body)

        raise


# ==========================================
# Timestamp Conversion
# ==========================================

def timestamp_to_iso(timestamp_ms):
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc
    ).isoformat()


# ==========================================
# Get or Create Symbol
# ==========================================

def get_or_create_symbol():

    params = urllib.parse.urlencode({
        "exchange": f"eq.{EXCHANGE}",
        "symbol": f"eq.{SYMBOL}",
        "market_type": f"eq.{MARKET_TYPE}",
        "limit": "1",
    })

    result = supabase_request(
        "GET",
        f"symbols?{params}"
    )

    if result:
        symbol_id = result[0]["id"]

        print(
            f"Existing symbol ID: {symbol_id}"
        )

        return symbol_id

    print("Symbol does not exist. Creating...")

    symbol_data = {
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "market_type": MARKET_TYPE,
        "status": "TRADING",
    }

    result = supabase_request(
        "POST",
        "symbols",
        data=symbol_data
    )

    symbol_id = result[0]["id"]

    print(
        f"Created symbol ID: {symbol_id}"
    )

    return symbol_id


# ==========================================
# Get Latest Candle
# ==========================================

def get_latest_candle_time(
    symbol_id,
    timeframe
):

    params = urllib.parse.urlencode({
        "symbol_id": f"eq.{symbol_id}",
        "timeframe": f"eq.{timeframe}",
        "order": "open_time.desc",
        "limit": "1",
    })

    result = supabase_request(
        "GET",
        f"candles?{params}"
    )

    if not result:
        return None

    return result[0]["open_time"]


# ==========================================
# Prepare Candles
# ==========================================

def prepare_candles(
    symbol_id,
    timeframe,
    rows
):

    candles = []

    for k in rows:

        candle = {
            "symbol_id": symbol_id,
            "timeframe": timeframe,

            "open_time": timestamp_to_iso(k[0]),

            "open": k[1],
            "high": k[2],
            "low": k[3],
            "close": k[4],

            "volume": k[5],

            "close_time": timestamp_to_iso(k[6]),

            "quote_volume": k[7],

            "trade_count": k[8],
        }

        candles.append(candle)

    return candles


# ==========================================
# Save Candles
# ==========================================

def save_candles(candles):

    if not candles:
        return []

    result = supabase_request(
        "POST",
        "candles",
        data=candles
    )

    return result


# ==========================================
# Main
# ==========================================

def main():

    print("====================================")
    print("AI Trading System - Data Collector")
    print("====================================")

    print(
        "SUPABASE_URL exists:",
        bool(SUPABASE_URL)
    )

    print(
        "SUPABASE_KEY exists:",
        bool(SUPABASE_KEY)
    )

    if not SUPABASE_URL:
        raise RuntimeError(
            "SUPABASE_URL is not configured."
        )

    if not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_KEY is not configured."
        )

    print("Checking Supabase symbols...")

    # --------------------------------------
    # 重要：
    # symbol_id 必須先取得
    # --------------------------------------

    symbol_id = get_or_create_symbol()

    print(
        f"Using symbol ID: {symbol_id}"
    )

    # --------------------------------------
    # Process every timeframe
    # --------------------------------------

    for timeframe in TIMEFRAMES:

        print("------------------------------------")
        print(f"Timeframe: {timeframe}")

        # ----------------------------------
        # 查詢 Supabase 最新資料
        # ----------------------------------

        latest_open_time = get_latest_candle_time(
            symbol_id,
            timeframe
        )

        # ----------------------------------
        # 已經有資料
        # ----------------------------------

        if latest_open_time:

            print(
                "Latest candle in Supabase:",
                latest_open_time
            )

            latest_dt = datetime.fromisoformat(
                latest_open_time.replace(
                    "Z",
                    "+00:00"
                )
            )

            # 從最新 K 線之後開始抓
            start_time = int(
                latest_dt.timestamp() * 1000
            ) + 1

            print(
                "Fetching only new candles..."
            )

            rows = get_binance_klines(
                SYMBOL,
                timeframe,
                limit=KLINE_LIMIT,
                start_time=start_time
            )

        # ----------------------------------
        # 完全沒有資料
        # ----------------------------------

        else:

            print(
                "No existing candles."
            )

            print(
                "Fetching initial 1000 candles..."
            )

            rows = get_binance_klines(
                SYMBOL,
                timeframe,
                limit=KLINE_LIMIT
            )

        # ----------------------------------
        # Binance 結果
        # ----------------------------------

        print(
            f"Binance rows: {len(rows)}"
        )

        # 沒有新的資料
        if not rows:

            print(
                "No new candles."
            )

            continue

        # ----------------------------------
        # 整理資料
        # ----------------------------------

        candles = prepare_candles(
            symbol_id,
            timeframe,
            rows
        )

        print(
            f"Prepared candles: {len(candles)}"
        )

        # ----------------------------------
        # 寫入 Supabase
        # ----------------------------------

        print(
            f"Writing {len(candles)} "
            "candles to Supabase..."
        )

        inserted = save_candles(
            candles
        )

        print(
            f"SUCCESS - Inserted rows: "
            f"{len(inserted)}"
        )

    print("------------------------------------")
    print("Data collection completed.")
    print("====================================")


# ==========================================
# Entry Point
# ==========================================

if __name__ == "__main__":
    main()
