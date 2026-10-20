# Milestone 5: Groww customer-feedback analysis

Source: `data/groww_reviews_12_weeks.csv`, English Google Play reviews for `com.nextbillion.groww`, India. Calendar dates are Asia/Kolkata. Window requested: 28 July 2026–20 October 2026. Reviews present: 28 July 2026–19 October 2026.

Google Play may omit eligible reviews. This is not a complete set of every review.

A review can match more than one theme. Percentages use two denominators:

- **All reviews:** 12,800 rows in the 12-week file.
- **Specific reviews:** 3,610 rows with more than 20 characters. Short text rarely names a problem, so this denominator is the fairer base for theme rates.

Matches are keyword rules, not a trained classifier. They miss complaints written only in Hindi and can miss paraphrases. Counts are a lower bound.

## Validation

| Check | Result |
| --- | --- |
| Files | Raw, 12-week, and weekly coverage CSVs exist |
| Rows | 12,800 raw, 12,800 filtered, 13 weekly buckets |
| Review IDs | No missing IDs, no duplicate IDs, raw and filtered ID sets match |
| Dates | Every filtered date is inside 28 July–20 October 2026. Earliest 28 July 2026, latest 19 October 2026 |
| Empty text | 0 |
| Text of 5 characters or fewer | 4,174 (32.6%), flag matches recomputed length |
| Ratings | Present for every row: 1 star 1,335; 2 star 212; 3 star 357; 4 star 1,023; 5 star 9,873 |
| Weekly file | Matches a Monday–Sunday recount of the filtered file, including two partial edge weeks |
| Collector | Not modified. Collection had already stopped at the start boundary, not the safety cap |

Quality issues that can distort interpretation:

- 32.6% of reviews are five characters or fewer. 3,623 of those 4,174 are 5-star, usually “good” or “nice”. The all-review 5-star share (77.1%) is pulled up by that generic praise.
- Among the 3,610 specific reviews, 1,059 (29.3%) are 1-star. Detailed reviews are much more negative than the full file.
- 44 specific reviews contain no Latin letters, so English keyword rules do not see them.
- Developer replies are mostly templates (about 12,497 non-empty replies). They are not evidence that an issue was resolved.
- The week of 19 October has 115 reviews and is only a partial week through 19 October. It is not comparable to full weeks.

## Findings

Observed, not inferred from volume alone:

1. **Most written feedback is generic approval, not a product description.** 9,873 of 12,800 reviews (77.1%) are 5-star. The most common texts of 20 characters or fewer are “good” (2,241), “nice” (538), and “good” plus an emoji (383).
2. **When customers write a specific complaint, support and charges recur.** Customer-support language appears in 260 of 12,800 reviews (2.0%) and 257 of 3,610 specific reviews (7.1%). Of the 260, 217 are 1–2 star. Brokerage or charges language appears in 275 of 12,800 (2.1%) and 252 of 3,610 (7.0%). Of the 275, 165 are 1–2 star.
3. **Customers who praise something specific most often praise ease of use.** “Easy to use”, “user friendly”, or “beginner” appears in 441 of 12,800 (3.4%) and 333 of 3,610 (9.2%). 407 of the 441 are 4–5 star.
4. **Theme rates do not show a reliable shift across the window.** Splitting the 12 full weeks at 7 September 2026, support stays about 2.0% of reviews (139/6,898 early, 119/5,787 later). Charges stay about 2.1% (155/6,898 early, 118/5,787 later). The 1–2 star share by week stays between 8.9% and 14.2%. The week of 24 August is the high end (14.2% of 1,357). That is a high week, not a new regime.

## Themes

Sentiment below is the customer’s own star rating among keyword matches, not a separate sentiment model.

### Customer support — observed problem

- All reviews: 260 / 12,800 (2.0%). Specific reviews: 257 / 3,610 (7.1%).
- 217 of 260 matches are 1–2 star; 33 are 4–5 star.
- Evidence: `30fc6cf8-2776-4b89-b27e-78bb96f38d0b` (1 star, 21 September 2026), “Worst customer care service, no reply for last few of my complaints till now.” `50d1df05-41b7-4276-9818-d25c487977c6` (1 star, 15 August 2026) says portfolio information stayed wrong after screenshots were sent and the complaint was closed with a cache-and-reinstall reply.
- Weekly: about 2% in both halves of the window. No emerging spike.
- Product implication (hypothesis): the repeated story is slow or scripted closure, not only the absence of a channel.
- Confidence: medium. The phrase is distinctive, but keyword search undercounts people who describe a wait without saying “support”.

### Brokerage and charges — observed problem, often paired with support

- All reviews: 275 / 12,800 (2.1%). Specific reviews: 252 / 3,610 (7.0%).
- 165 of 275 are 1–2 star; 82 are 4–5 star. Some 4–5 star reviews still ask for lower brokerage, so the star is not a pure complaint tag.
- Evidence: `80902ca3-7757-4566-a348-c18b33fd04d6` (1 star, 19 October 2026), “Brokerage charges very high after 2025... why?” `977ac19c-b8a7-4709-aef3-4c0c059210e9` (1 star, 17 October 2026) names service charges, hidden charges, and slow customer service together. `3cfb3c39-de11-43dd-baf3-ab48b1444dd6` (1 star, 13 September 2026) says hidden charges on cancelled or unexecuted orders consume F&O profit and that withdrawals take 5–7 days.
- Weekly: no reliable increase. Early 2.25%, later 2.04%.
- Product implication (hypothesis): customers are disputing transparency of charges on orders that do not execute, not only the headline brokerage rate.
- Confidence: medium. “Charges” is broader than brokerage. The cancelled-order claim is one review, not a measured fee audit.

### Ease of use — observed value

- All reviews: 441 / 12,800 (3.4%). Specific reviews: 333 / 3,610 (9.2%).
- 407 of 441 are 4–5 star.
- Evidence: `44cf2908-a553-4a3b-8909-604f853d4b63` (4 star, 28 August 2026), “This app has a clean user interface and is very easy to use.” The same review asks for cancelled SIPs and sold orders to drop out of the active view. `f1ca2f35-cdbb-4955-9bd8-8ca9f0241def` (4 star, 3 August 2026) praises first-time stock-market use and says an SIP amount cannot be increased immediately.
- Subtheme: simplicity for a new investor is the value. Unmet needs inside otherwise positive reviews are portfolio cleanup and SIP changes.
- Confidence: medium-high for the praise. The SIP-timing detail is one report.

### Mutual funds — mostly positive mentions, with findability gaps

- All reviews: 186 / 12,800 (1.5%). Specific reviews: 176 / 3,610 (4.9%).
- 130 of 186 are 4–5 star; 44 are 1–2 star.
- Evidence: `370afd8b-f51f-47fa-a662-b51a6be2e0a8` (1 star, 30 August 2026) likes ease of use but says there is no dedicated section for international mutual funds and that funds closed to new SIPs or lump sums do not appear in search.
- Product implication (hypothesis): fund discovery, not the existence of mutual funds, is the unmet need in the negative mutual-fund texts.
- Confidence: low-medium. The keyword includes both praise and complaints.

### Charts, updates, and order controls — concrete but less frequent

- Charts or the back button: 180 / 12,800 (1.4%); 176 / 3,610 (4.9%); 90 of 180 are 1–2 star.
- Update, crash, lag, or “not working”: 155 / 12,800 (1.2%); 148 / 3,610 (4.1%); 108 of 155 are 1–2 star.
- Stop-loss, rejected or pending orders, GTT, or limit order: 37 / 12,800 (0.3%); all 37 are specific reviews; 18 are 1–2 star.
- Evidence: `7f42e7d6-9711-4bb8-8790-fb2e49f737b2` (1 star, 28 August 2026) says a new update hides the phone back button on charts, opens scalper mode by mistake, and autofills the limit order. `c40902ef-8b8d-4bc5-8917-3f1731d873dd` (1 star, 7 August 2026) says stop-loss triggers before the price reaches the level or only after it has moved past it.
- These did not rise reliably between the two halves (charts 1.55% then 1.23%; update language 1.20% then 1.23%; orders 0.29% in both).
- Product implication (hypothesis): chart navigation after releases and stop-loss trigger behavior are worth a product check because the descriptions are specific. Frequency alone does not show how many trades were affected.
- Confidence: low-medium. Small counts, and “not working” is broad.

### Funds movement, account access, and IPOs — investigation items, not established trends

- Funds language (withdrawal, refund, money stuck or deducted, add money, payment failed): 81 / 12,800 (0.6%); 51 of 81 are 1–2 star. Later full weeks are 47/5,787 (0.81%) versus 34/6,898 (0.49%) earlier. The absolute gap is 13 reviews. That is a watch item, not a confirmed increase.
- Account, KYC, login, OTP, or demat language: 96 / 12,800 (0.75%); flat across halves (0.74% then 0.76%).
- IPO or UPI mandate: 71 / 12,800 (0.55%). `49f7b2af-b8bd-4c56-b0c7-c695df1a99bd` (1 star, 24 September 2026) says IPO applications on Groww will not receive an allotment. That is one customer’s claim, not evidence about allotment outcomes.
- `4b9a15df-0e1d-4104-b236-296344af258b` (1 star, 16 September 2026) describes a bank account blocked after an unexpected Groww credit and says EMIs and SIPs could not be paid. One report. Treat as an incident to verify, not as a pattern.
- Confidence: low.

## What not to conclude

- Do not treat the 77.1% 5-star share as proof that specific problems are rare. Specific text is much more negative.
- Do not treat a keyword percentage as the share of customers harmed. It is the share of collected reviews whose text matched a rule.
- Do not read the two empty weeks from the earlier 10,000-review run as “no reviews”. The regenerated file has reviews in every Monday–Sunday bucket. The first and last buckets are partial weeks.
- Do not claim every eligible Google Play review was collected.
