"""
Groww Google Play reviews collector for M5.

Install dependencies separately when ready:
    pip install google-play-scraper pandas

Outputs:
    data/groww_reviews_raw.csv
    data/groww_reviews_12_weeks.csv
    data/groww_weekly_coverage.csv

The script cannot guarantee that Google Play returns the full history.
Inspect the coverage report before using the dataset.
"""

from datetime import date, timedelta
from pathlib import Path
import time

import pandas as pd
from google_play_scraper import reviews, Sort


# 1. Configuration
APP_ID = "com.nextbillion.groww"
LANGUAGE = "en"
COUNTRY = "in"

WEEKS = 12
END_DATE = date(2026, 10, 20)
START_DATE = END_DATE - timedelta(weeks=WEEKS)

BATCH_SIZE = 200
MAX_REVIEWS = 10_000
PAUSE_SECONDS = 1

OUTPUT_DIR = Path("data")
RAW_FILE = OUTPUT_DIR / "groww_reviews_raw.csv"
FILTERED_FILE = OUTPUT_DIR / f"groww_reviews_{WEEKS}_weeks.csv"
WEEKLY_FILE = OUTPUT_DIR / "groww_weekly_coverage.csv"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_reviews = []
    seen_ids = set()
    continuation_token = None

    print(f"App: {APP_ID}")
    print(f"Requested period: {START_DATE} to {END_DATE}")
    print("Starting collection...")

    # 2. Fetch reviews in batches
    while len(all_reviews) < MAX_REVIEWS:
        try:
            batch, next_token = reviews(
                APP_ID,
                lang=LANGUAGE,
                country=COUNTRY,
                sort=Sort.NEWEST,
                count=BATCH_SIZE,
                continuation_token=continuation_token,
            )
        except Exception as exc:
            print(f"Collection stopped due to an error: {exc}")
            print("Saving reviews collected so far, if any.")
            break

        if not batch:
            print("No more reviews returned.")
            break

        new_count = 0
        for review in batch:
            review_id = review.get("reviewId")

            if review_id and review_id in seen_ids:
                continue

            if review_id:
                seen_ids.add(review_id)

            all_reviews.append(review)
            new_count += 1

        batch_dates = pd.to_datetime(
            [item.get("at") for item in batch],
            errors="coerce",
            utc=True,
        ).dropna()

        if not batch_dates.empty:
            oldest = batch_dates.min().date()
            newest = batch_dates.max().date()
            print(
                f"Fetched {len(all_reviews)} reviews; "
                f"batch dates: {oldest} to {newest}"
            )

            # Reviews are requested newest-first.
            if oldest <= START_DATE:
                print("Reached the requested start date.")
                break

        if next_token is None:
            print("No continuation token returned.")
            break

        if new_count == 0:
            print("No new unique reviews returned; stopping.")
            break

        continuation_token = next_token
        time.sleep(PAUSE_SECONDS)

    if not all_reviews:
        raise RuntimeError(
            "No reviews were collected. Check the package ID, "
            "network access, and scraper compatibility."
        )

    # 3. Save raw data
    raw_df = pd.DataFrame(all_reviews)

    if "at" not in raw_df.columns:
        raise RuntimeError("The returned data has no date column.")

    raw_df["at"] = pd.to_datetime(
        raw_df["at"], errors="coerce", utc=True
    )
    raw_df.to_csv(RAW_FILE, index=False)

    # 4. Validate expected fields
    if "content" not in raw_df.columns:
        raise RuntimeError("The returned data has no review-text column.")

    if "score" not in raw_df.columns:
        print("WARNING: No rating column was returned.")

    valid_df = raw_df.dropna(subset=["at"]).copy()
    valid_df["review_date"] = valid_df["at"].dt.date
    valid_df["content"] = valid_df["content"].fillna("").astype(str)

    # 5. Filter to the requested 12-week window, inclusive
    filtered_df = valid_df[
        (valid_df["review_date"] >= START_DATE)
        & (valid_df["review_date"] <= END_DATE)
    ].copy()

    if "reviewId" in filtered_df.columns:
        filtered_df = filtered_df.drop_duplicates(
            subset=["reviewId"], keep="first"
        )

    filtered_df["text_length"] = (
        filtered_df["content"].str.strip().str.len()
    )
    filtered_df["short_text_flag"] = filtered_df["text_length"] <= 5
    filtered_df["missing_text_flag"] = (
        filtered_df["content"].str.strip().eq("")
    )

    filtered_df.to_csv(FILTERED_FILE, index=False)

    # 6. Build a weekly coverage report, including zero-count weeks
    filtered_df["week_start"] = (
        pd.to_datetime(filtered_df["review_date"])
        .dt.to_period("W-SUN")
        .dt.start_time
    )

    first_week = (
        pd.Timestamp(START_DATE).to_period("W-SUN").start_time
    )
    last_week = (
        pd.Timestamp(END_DATE).to_period("W-SUN").start_time
    )
    all_weeks = pd.date_range(first_week, last_week, freq="7D")

    counts = filtered_df.groupby("week_start").size()

    weekly_report = pd.DataFrame({"week_start": all_weeks})
    weekly_report["week_end"] = (
        weekly_report["week_start"] + pd.Timedelta(days=6)
    )
    weekly_report["review_count"] = (
        weekly_report["week_start"]
        .map(counts)
        .fillna(0)
        .astype(int)
    )
    weekly_report.to_csv(WEEKLY_FILE, index=False)

    # 7. Report actual coverage
    print("\n--- M5 DATASET VALIDATION ---")
    print(f"Total reviews collected: {len(raw_df)}")
    print(f"Reviews with valid dates: {len(valid_df)}")
    print(f"Reviews in target window: {len(filtered_df)}")
    print(f"Requested window: {START_DATE} to {END_DATE}")

    # The filtered frame cannot show whether collection walked back to
    # the start boundary: every row is already on or after START_DATE.
    if valid_df.empty:
        print("Raw earliest date: none")
        print("Raw latest date: none")
        start_reached = False
    else:
        raw_start = valid_df["review_date"].min()
        raw_end = valid_df["review_date"].max()
        print(f"Raw earliest date: {raw_start}")
        print(f"Raw latest date: {raw_end}")
        start_reached = raw_start <= START_DATE

    if filtered_df.empty:
        print("Filtered earliest date: none")
        print("Filtered latest date: none")
        window_has_reviews = False
        recent_enough = False
    else:
        filtered_start = filtered_df["review_date"].min()
        filtered_end = filtered_df["review_date"].max()

        print(f"Filtered earliest date: {filtered_start}")
        print(f"Filtered latest date: {filtered_end}")
        print(
            "Reviews with text <= 5 characters: "
            f"{filtered_df['short_text_flag'].sum()}"
        )
        print(
            "Reviews with empty text: "
            f"{filtered_df['missing_text_flag'].sum()}"
        )

        window_has_reviews = (
            filtered_start >= START_DATE and filtered_end <= END_DATE
        )
        recent_enough = filtered_end >= END_DATE - timedelta(days=7)

    print(f"Start boundary reached in raw data: {start_reached}")
    print(f"Filtered window contains reviews: {window_has_reviews}")

    zero_weeks = int((weekly_report["review_count"] == 0).sum())
    print(f"Weeks with zero reviews: {zero_weeks}")
    print("\nWeekly counts:")
    print(weekly_report.to_string(index=False))

    if start_reached and recent_enough and window_has_reviews:
        print(
            "\nDATE-BOUNDARY CHECK: PASS. "
            "Inspect weekly counts before claiming representativeness."
        )
    else:
        print(
            "\nDATE-BOUNDARY CHECK: FAIL. "
            "The data may not cover the full requested period."
        )

    print("\nSaved files:")
    print(f"Raw CSV: {RAW_FILE}")
    print(f"Filtered CSV: {FILTERED_FILE}")
    print(f"Weekly report: {WEEKLY_FILE}")


if __name__ == "__main__":
    main()
