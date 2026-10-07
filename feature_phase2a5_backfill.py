import os
import urllib.parse
import urllib.request
import json

from feature_engine import (
    get_active_symbols,
    get_all_candles,
    calculate_features,
)


SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

BATCH_SIZE = 500


# ============================================================
# Phase 2A-5 新增欄位
# ============================================================

NEW_FEATURE_FIELDS = [
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


# ============================================================
# Supabase
# ============================================================

def supabase_upsert(rows):
    if not rows:
        return

    url = f"{SUPABASE_URL}/rest/v1/features"

    body = json.dumps(rows).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers=HEADERS,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        response.read()


# ============================================================
# 只保留 Phase 2A-5 欄位
# ============================================================

def build_update_rows(feature_rows):
    output = []

    for row in feature_rows:

        # 必須存在的識別欄位
        if (
            row.get("symbol_id") is None
            or row.get("timeframe") is None
            or row.get("timestamp") is None
        ):
            continue

        item = {
            "symbol_id": row["symbol_id"],
            "timeframe": row["timeframe"],
            "timestamp": row["timestamp"],
        }

        for field in NEW_FEATURE_FIELDS:
            if field in row:
                item[field] = row[field]

        output.append(item)

    return output


# ============================================================
# 批次寫入
# ============================================================

def write_batches(rows):
    total = len(rows)
    written = 0

    for start in range(0, total, BATCH_SIZE):

        batch = rows[start:start + BATCH_SIZE]

        supabase_upsert(batch)

        written += len(batch)

        print(
            f"  Written: {written}/{total}"
        )

    return written


# ============================================================
# 單一 symbol + timeframe
# ============================================================

def backfill_one(symbol, timeframe):

    symbol_id = symbol["id"]
    symbol_name = symbol["symbol"]

    print()
    print("=" * 70)
    print(
        f"PHASE 2A-5 BACKFILL: "
        f"{symbol_name} - {timeframe}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # 取得完整歷史 K 線
    # --------------------------------------------------------

    candles = get_all_candles(
        symbol_id,
        timeframe
    )

    print(
        f"Candles loaded: {len(candles)}"
    )

    if not candles:
        print("No candles.")
        return 0

    # --------------------------------------------------------
    # 使用目前正式 Feature Engine 的計算邏輯
    # --------------------------------------------------------

    feature_rows = calculate_features(
        candles
    )

    print(
        f"Features calculated: "
        f"{len(feature_rows)}"
    )

    # --------------------------------------------------------
    # 只留下 Phase 2A-5 新欄位
    # --------------------------------------------------------

    update_rows = build_update_rows(
        feature_rows
    )

    print(
        f"Phase 2A-5 rows: "
        f"{len(update_rows)}"
    )

    if not update_rows:
        print("Nothing to update.")
        return 0

    # --------------------------------------------------------
    # 批次更新
    # --------------------------------------------------------

    written = write_batches(
        update_rows
    )

    print(
        f"Completed: {written}"
    )

    return written


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 70)
    print("PHASE 2A-5 HISTORICAL BACKFILL")
    print("=" * 70)

    symbols = get_active_symbols()

    total_written = 0
    total_jobs = 0
    failed_jobs = 0

    for symbol in symbols:

        for timeframe in TIMEFRAMES:

            total_jobs += 1

            try:

                written = backfill_one(
                    symbol,
                    timeframe
                )

                total_written += written

            except Exception as e:

                failed_jobs += 1

                print()
                print(
                    f"ERROR: "
                    f"{symbol['symbol']} "
                    f"{timeframe}"
                )
                print(str(e))

    print()
    print("=" * 70)
    print("PHASE 2A-5 BACKFILL COMPLETE")
    print("=" * 70)

    print(
        f"Jobs: {total_jobs}"
    )

    print(
        f"Total written: {total_written}"
    )

    print(
        f"Failed jobs: {failed_jobs}"
    )

    if failed_jobs == 0:
        print("OVERALL: PASS")
    else:
        print("OVERALL: FAIL")


if __name__ == "__main__":
    main()
