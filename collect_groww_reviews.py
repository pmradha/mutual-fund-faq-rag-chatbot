"""
Groww Google Play reviews collector for M5.

Dependencies, also listed in requirements.txt:
    pip install google-play-scraper pandas

Outputs:
    data/groww_reviews_raw.csv
    data/groww_reviews_12_weeks.csv
    data/groww_weekly_coverage.csv

The script cannot guarantee that Google Play returns the full history.
Inspect the coverage report before using the dataset.

google-play-scraper reviews() accepts sort, count, score, device, and a
continuation token. It has no request date filter, so the configured
window cannot be collected as separate date-bounded queries. Pagination
uses one newest-first continuation chain so review IDs are deduplicated
across pages. Each continuation page is assumed to be older than the
previous page. Further requests stop when a page has crossed the start
date: at least two reviews on that page are on or before the start, or
the whole page is. One older review in an otherwise newer page is not
the start boundary and is not proof that the full period was traversed.
The review cap is a runaway guard sized from the configured window, not
a 10,000-review sample. A date span is not a complete collection of
every eligible review.

Calendar dates use Asia/Kolkata. Weekly coverage buckets are
Monday–Sunday and can include partial weeks at both ends of the window.
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
# reviews() cannot filter by date. A fixed 10,000-review cap stopped
# pagination before this window's start date. The cap scales with the
# configured inclusive window and only stops a runaway fetch.
MAX_REVIEWS_PER_DAY = 1_000
WINDOW_DAYS = (END_DATE - START_DATE).days + 1
MAX_REVIEWS = WINDOW_DAYS * MAX_REVIEWS_PER_DAY
PAUSE_SECONDS = 1

OUTPUT_DIR = Path("data")
RAW_FILE = OUTPUT_DIR / "groww_reviews_raw.csv"
FILTERED_FILE = OUTPUT_DIR / f"groww_reviews_{WEEKS}_weeks.csv"
WEEKLY_FILE = OUTPUT_DIR / "groww_weekly_coverage.csv"
LOCAL_TIMEZONE = "Asia/Kolkata"


def to_kolkata_timestamps(values):
    """Parse timestamps as UTC and convert them to Asia/Kolkata."""
    timestamps = pd.to_datetime(
        pd.Series(values), errors="coerce", utc=True
    )
    return timestamps.dt.tz_convert(LOCAL_TIMEZONE)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_reviews = []
    seen_ids = set()
    continuation_token = None
    fetched_count = 0
    stop_reason = None

    print(f"App: {APP_ID}")
    print(f"Requested period: {START_DATE} to {END_DATE}")
    print(
        f"Safety cap: {MAX_REVIEWS} reviews "
        f"({WINDOW_DAYS} days x {MAX_REVIEWS_PER_DAY} per day)"
    )
    print("Starting collection...")

    # 2. Fetch reviews in batches
    while True:
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
            stop_reason = "error"
            print(f"Collection stopped due to an error while fetching reviews: {exc}")
            print("Saving reviews collected so far, if any.")
            break

        if not batch:
            stop_reason = "no_more_pages"
            print("No more reviews returned.")
            break

        reached_start = False
        try:
            for review in batch:
                review_id = review.get("reviewId")

                if review_id and review_id in seen_ids:
                    continue

                if review_id:
                    seen_ids.add(review_id)

                all_reviews.append(review)

            fetched_count += len(batch)

            batch_dates = to_kolkata_timestamps(
                [item.get("at") for item in batch]
            ).dropna()

            if not batch_dates.empty:
                oldest = batch_dates.min().date()
                newest = batch_dates.max().date()
                print(
                    f"Fetched {len(all_reviews)} reviews; "
                    f"batch dates: {oldest} to {newest}"
                )

                # Newest-first assumption: Sort.NEWEST returns this page from
                # newest to oldest, and the next page is older still. The
                # earliest Asia/Kolkata date is the furthest point this page
                # reached. Stop only when the page has crossed START_DATE,
                # which means the whole page is on or before that date or
                # at least two reviews are. One older review among newer
                # ones can be out of order, so it does not end pagination
                # and does not prove the full period was traversed.
                # Stopping only ends further requests.
                on_or_before_start = sum(
                    day <= START_DATE for day in batch_dates.dt.date
                )
                if newest <= START_DATE or on_or_before_start >= 2:
                    reached_start = True
                elif on_or_before_start == 1:
                    print(
                        "One review is on or before the start date; "
                        "continuing because that review alone is not the "
                        "newest-first start boundary."
                    )
        except Exception as exc:
            stop_reason = "error"
            print(
                "Collection stopped due to an error while processing a batch: "
                f"{exc}"
            )
            print("Saving reviews collected so far, if any.")
            break

        if reached_start:
            stop_reason = "start_date"
            print(
                "Reached the requested start boundary under the "
                "newest-first page order. Further requests are stopping. "
                "This does not mean every eligible review was collected."
            )
            break

        if next_token is None:
            stop_reason = "no_more_pages"
            print("No continuation token returned.")
            break

        if len(all_reviews) >= MAX_REVIEWS or fetched_count >= MAX_REVIEWS:
            stop_reason = "safety_cap"
            print(
                f"Safety cap reached: {MAX_REVIEWS} reviews. "
                f"Collected {len(all_reviews)} unique reviews "
                f"from {fetched_count} returned reviews. Stopping collection."
            )
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

    raw_df["at"] = to_kolkata_timestamps(raw_df["at"])
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

    # 6. Build a weekly coverage report, including zero-count weeks.
    # Buckets are Monday–Sunday (pandas W-SUN). The first and last
    # buckets can be partial weeks at the edges of the requested window.
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

    if valid_df.empty:
        print("Raw earliest date: none")
        print("Raw latest date: none")
        raw_start = None
        raw_end = None
    else:
        raw_start = valid_df["review_date"].min()
        raw_end = valid_df["review_date"].max()
        print(f"Raw earliest date: {raw_start}")
        print(f"Raw latest date: {raw_end}")

    if filtered_df.empty:
        print("Filtered earliest date: none")
        print("Filtered latest date: none")
        filtered_end = None
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

    raw_reaches_start = raw_start is not None and raw_start <= START_DATE
    filtered_on_end_date = (
        filtered_end is not None and filtered_end >= END_DATE
    )
    filtered_within_seven_days = (
        filtered_end is not None
        and filtered_end >= END_DATE - timedelta(days=7)
    )
    # An error or the safety cap did not finish the newest-first walk.
    # Stored dates from that partial run must not count as reaching
    # the start boundary or as full-period coverage.
    collection_reached_start = (
        stop_reason == "start_date"
        or (stop_reason == "no_more_pages" and raw_reaches_start)
    )
    reviews_in_window = not filtered_df.empty
    spans_full_period = (
        stop_reason not in ("error", "safety_cap")
        and collection_reached_start
        and filtered_within_seven_days
    )

    print(
        "Collection reached the requested start boundary: "
        f"{collection_reached_start}"
    )
    print(f"Reviews exist inside the requested window: {reviews_in_window}")
    print(
        "Latest filtered review is within seven days of the requested "
        f"end date: {filtered_within_seven_days}"
    )
    print(
        "Latest filtered review is on the requested end date: "
        f"{filtered_on_end_date}"
    )
    print(
        "Retrieved data spans the full requested period: "
        f"{spans_full_period}"
    )

    zero_weeks = int((weekly_report["review_count"] == 0).sum())
    print(f"Weeks with zero reviews: {zero_weeks}")
    print(
        "Weekly buckets are Monday–Sunday and can include partial weeks "
        "at the start and end of the requested window."
    )
    print("\nWeekly counts:")
    print(weekly_report.to_string(index=False))

    if spans_full_period:
        print(
            "\nThe retrieved dates span the requested period: collection "
            "reached the start boundary, and the latest filtered review "
            "is within seven days of the end date. This does not mean "
            "every eligible review was collected. Use the weekly counts, "
            "including weeks with zero reviews, before treating the "
            "dataset as representative."
        )
    else:
        print(
            "\nThe retrieved data does not span the full requested period. "
            "The dataset is not fully covered, and this is not a complete "
            "collection of every eligible review."
        )

    print("\nSaved files:")
    print(f"Raw CSV: {RAW_FILE}")
    print(f"Filtered CSV: {FILTERED_FILE}")
    print(f"Weekly report: {WEEKLY_FILE}")


if __name__ == "__main__":
    main()
