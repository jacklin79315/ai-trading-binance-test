
import csv
import io
import os
import zipfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from supabase import create_client


# ============================================================
# Phase 2B-2: Futures Funding Rate Historical Backfill
# Initial test: BTCUSDT, September 2026
# Default: DRY RUN (does not write to Supabase)
# ============================================================

SYMBOL = "BTCUSDT"
MONTH = "2026-09"

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() != "false"
BATCH_SIZE = 500

ZIP_URL = (
    "https://data.binance.vision/data/futures/um/monthly/"
    f"fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{MONTH}.zip"
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
)


def require_environment():
    if not SUPABASE_URL:
        raise RuntimeError("Missing environment variable: SUPABASE_URL")

    if not SUPABASE_KEY:
        raise RuntimeError(
            "Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY"
        )


def download_csv():
    print(f"Downloading: {ZIP_URL}")

    request = Request(
        ZIP_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urlopen(request, timeout=60) as response:
        zip_bytes = response.read()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        csv_files = [
            name for name in archive.namelist()
            if name.lower().endswith(".csv")
        ]

        if len(csv_files) != 1:
            raise RuntimeError(
                f"Expected exactly one CSV, found {len(csv_files)}"
            )

        with archive.open(csv_files[0]) as file:
            content = file.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(content))

    required_columns = {
        "calc_time",
        "funding_interval_hours",
        "last_funding_rate",
    }

    if not reader.fieldnames or not required_columns.issubset(
        set(reader.fieldnames)
    ):
        raise RuntimeError(
            f"Unexpected CSV columns: {reader.fieldnames}"
        )

    return list(reader)


def normalize_rows(csv_rows, symbol_id):
    result = []
    seen_timestamps = set()

    for line_number, row in enumerate(csv_rows, start=2):
        try:
            timestamp_ms = int(row["calc_time"])
            interval_hours = int(row["funding_interval_hours"])
            funding_rate = row["last_funding_rate"].strip()

            if interval_hours <= 0:
                raise ValueError("Invalid funding interval")

            # Keep the original rate as a decimal string to avoid
            # introducing Python floating-point rounding.
            rate_value = float(funding_rate)
            if not (-1 < rate_value < 1):
                raise ValueError("Funding rate outside expected range")

            funding_dt = datetime.fromtimestamp(
                timestamp_ms / 1000,
                tz=timezone.utc,
            )

            # Only process records belonging to the requested month.
            if funding_dt.strftime("%Y-%m") != MONTH:
                raise ValueError(
                    f"Timestamp outside requested month: {funding_dt}"
                )

            if timestamp_ms in seen_timestamps:
                raise ValueError(
                    f"Duplicate timestamp: {timestamp_ms}"
                )

            seen_timestamps.add(timestamp_ms)

            result.append({
                "symbol_id": symbol_id,
                "funding_time": funding_dt.isoformat(),
                "funding_rate": funding_rate,
                "mark_price": None,
                "index_price": None,
            })

        except Exception as exc:
            raise RuntimeError(
                f"Invalid CSV data at line {line_number}: {exc}"
            ) from exc

    if not result:
        raise RuntimeError("No funding rate rows found")

    result.sort(key=lambda item: item["funding_time"])
    return result


def main():
    require_environment()

    print("=" * 60)
    print("Futures Funding Rate Backfill")
    print(f"Symbol: {SYMBOL}")
    print(f"Month: {MONTH}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE WRITE'}")
    print("=" * 60)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    symbol_result = (
        client.table("symbols")
        .select("id, symbol, market_type, status")
        .eq("exchange", "binance")
        .eq("symbol", SYMBOL)
        .eq("market_type", "futures")
        .execute()
    )

    symbols = symbol_result.data or []

    if len(symbols) != 1:
        raise RuntimeError(
            f"Expected one Futures symbol record; found {len(symbols)}"
        )

    symbol = symbols[0]

    if symbol["status"] != "TRADING":
        raise RuntimeError(
            f"Symbol is not TRADING: {symbol['status']}"
        )

    symbol_id = symbol["id"]
    print(f"Symbol ID: {symbol_id}")

    csv_rows = download_csv()
    rows = normalize_rows(csv_rows, symbol_id)

    print(f"CSV records: {len(csv_rows)}")
    print(f"Validated records: {len(rows)}")
    print(f"First funding time (UTC): {rows[0]['funding_time']}")
    print(f"Last funding time (UTC): {rows[-1]['funding_time']}")
    print(f"First funding rate: {rows[0]['funding_rate']}")
    print(f"Last funding rate: {rows[-1]['funding_rate']}")

    if DRY_RUN:
        print("\nDRY RUN completed. No database rows were written.")
        print("Review the output before enabling live writes.")
        return

    inserted_batches = 0

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]

        (
            client.table("funding_rates")
            .upsert(
                batch,
                on_conflict="symbol_id,funding_time",
            )
            .execute()
        )

        inserted_batches += 1
        print(
            f"Processed batch {inserted_batches}: "
            f"{min(start + BATCH_SIZE, len(rows))}/{len(rows)}"
        )

    print("\nFunding Rate backfill completed.")
    print(f"Processed records: {len(rows)}")


if __name__ == "__main__":
    main()
