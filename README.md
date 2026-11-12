# Southeast Property Value Estimator

PropertyValue: two paths, each in three steps (property details -> financial information -> estimate).
- Quick Estimate: property type, market, size, rent, occupancy (and lease structure). Market assumptions fill
  the rest, and every one is listed next to the result.
- Detailed Underwriting: rent roll upload and review, expenses, taxes, leasing terms, comps -> lease-by-lease
  model and Excel workbook.
Apartments, industrial, office and single-family homes; 13 Southeast markets.

## Files
- app.py           the website (Streamlit): landing page, Quick Estimate and Detailed Underwriting flows
- home.py          single-family homes: comparable-sales adjustment grid
- styles.py        the visual design (dark theme, cards, progress bar, summary card, result panel)
- .streamlit/      theme + settings (enables the fonts folder, hides Streamlit's toolbar)
- underwriting.py  the model: lease-by-lease monthly DCF for commercial (expirations, renewal
                   probability, downtime, TI, commissions, free rent, market-rent resets),
                   occupancy-path DCF for apartments, direct cap, sales comparison from owner comps,
                   discount-rate build-up, weighted reconciliation with reasons, tax schedules,
                   scenario range, two sensitivity grids
- checks.py        reasonableness check vs. published sale prices ($/SF, $/unit) and the reliability rating
- validation.py    historical-sales test: python validation.py my_sales.csv (template: --template)
- historical_sales_template.csv  format for your public-sales test file
- quality.py       input checks (rent/expense ranges, vacancy, tax sanity) -> data grade A/B/C
- rentroll.py      reads rent rolls; duplicate-suite/unit checks, rentable-area reconciliation,
                   per-suite market rent, floorplan pricing for vacant apartments
- export.py        Excel underwriting summary (live formulas; ties to the website to the dollar)
- engine.py        direct-cap math for the original spec's worked example (tested)
- market_data.py   dated cap-rate benchmarks with confidence rules, vacancy, tax rates and state
                   reassessment rules, survey discount/exit spreads, leasing and expense-growth
                   assumptions — all sourced (update quarterly: add new CAP_POINTS, bump LATEST)
- test_engine.py   49 checks — run: python -m pytest -q
- sample_*.csv     test rent rolls for each tab

## How the estimate is built
1. Direct cap: stabilized NOI / cap rate, less lease-up costs, repairs and a 15% lease-up risk allowance.
2. DCF: 10 years + sale at the exit cap, discounted at a rate built from the cap rate, an investor-survey
   spread and property-specific risk adjustments (all listed on screen).
3. Sales comparison: only when the owner enters comparable sales.
Weights start 50/50 and shift for stabilization, rollover, lease complexity, data quality and comps;
every shift is explained. The range is scenario-based, not a statistical confidence interval.

## Add a market
Copy any block in MARKETS in market_data.py, change the name and numbers, keep a source.

## Run locally
    pip install -r requirements.txt
    streamlit run app.py

## Deploy
Upload all files AND the .streamlit/ folder to your GitHub repo (replace the old ones).
The .streamlit folder starts with a dot, so some computers hide it — turn on hidden files to see it. Streamlit redeploys automatically.


## Testing accuracy against real sales
1. python validation.py --template   (writes historical_sales_template.csv)
2. Fill one row per sale: price, size, occupancy, contract rent, lease type, rough lease expiry, subtype, and
   (if known) expenses, taxes, market rent, remaining lease term, in-place NOI, market cap rate at the sale date.
   Mark rows with verified operating data as verified=yes.
3. python validation.py my_sales.csv  ->  validation_results.csv + validation_summary.md
The summary compares Quick vs. Detailed vs. Detailed-at-sale-date-cap to separate missing owner inputs, market
assumptions and engine error. Calibrate only on verified rows.
