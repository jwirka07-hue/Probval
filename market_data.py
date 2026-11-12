"""
Market assumptions the owner doesn't have to know — Southeast US.
Every number carries its source. Update quarterly; add a market by adding a row.
Last updated: Nov 11, 2026.

CAP RATES
  Each sector uses a LOCAL, transaction-based cap rate for that property type where one is published
  (mf_cap / ind_cap / off_cap). Only where no local figure exists does the model fall back to
  local multifamily + a national sector spread, and the app labels that cap rate "estimated".
  A class adjustment (A / B / C) is then applied; the owner picks the class (or "Not sure", which
  widens the value range instead of guessing).

PROPERTY TAXES
  Effective tax rates (tax / market value) are from the Lincoln Institute study. How taxes behave
  after a sale depends on the state — see TAX_RULES.
"""

LINCOLN = "Lincoln Institute / MCFE 50-State Property Tax Comparison Study (taxes paid 2025)"
MATTHEWS, LEE = "Matthews", "Lee & Associates"

MARKETS = {
    # ---------------- Georgia ----------------
    "Atlanta, GA": {
        "state": "GA",
        "mf_vac": 0.059, "ind_vac": 0.090, "off_vac": 0.251,
        "vac_source": f"{MATTHEWS} MF Q2 2026 (5.9%); {LEE} Industrial Q3 2026 (9.0%) and Office Q3 2026 (25.1%)",
        "tax_commercial": 0.0162, "tax_apartment": 0.0161,
        "tax_source": f"{LINCOLN}: Atlanta commercial 1.62%, apartment 1.61%",
    },
    "Athens, GA": {
        "state": "GA",
        "tax_commercial": 0.01242, "tax_apartment": 0.01242,
        "tax_source": "Athens-Clarke 12.25 + Clarke Co. Schools 18.80 = 31.05 mills × 40% assessment = 1.24% of value",
    },
    # ---------------- North Carolina ----------------
    "Charlotte, NC": {
        "state": "NC",
        "ind_vac": 0.091, "off_vac": 0.132,
        "vac_source": f"{MATTHEWS} Industrial Q3 2026 (9.1%); {LEE} Office Q2 2026 (13.2%)",
        "tax_commercial": 0.0070, "tax_apartment": 0.0068,
        "tax_source": f"{LINCOLN}: Charlotte commercial 0.70%, apartment 0.68%",
    },
    "Raleigh-Durham, NC": {
        "state": "NC",
        "mf_vac": 0.094, "ind_vac": 0.077, "off_vac": 0.100,
        "vac_source": f"{LEE} Raleigh MF Q2 2026 (9.4%), Industrial Q3 2026 (7.7%), Office Q3 2026 (10.0%)",
        "tax_commercial": 0.0084, "tax_apartment": 0.0084,
        "tax_source": f"{LINCOLN}: Raleigh commercial 0.84% (apartment rate assumed equal)",
    },
    # ---------------- Tennessee ----------------
    "Nashville, TN": {
        "state": "TN", "next_reval_calendar_year": 2029,
        "mf_vac": 0.096, "ind_vac": 0.073,
        "vac_source": f"{LEE} MF Q2 2026 (9.6%); {MATTHEWS} Industrial Q3 2026 (7.3%)",
        "tax_commercial": 0.0108, "tax_apartment": 0.0111,
        "tax_source": f"{LINCOLN}: Nashville commercial 1.08%, apartment 1.11%",
    },
    "Memphis, TN": {
        "state": "TN",
        "mf_vac": 0.056, "ind_vac": 0.078,
        "vac_source": f"{MATTHEWS} MF Q3 2026 (5.6%) and Industrial Q3 2026 (7.8%)",
        "tax_commercial": 0.0202, "tax_apartment": 0.0202,
        "tax_source": f"{LINCOLN}: Memphis commercial 2.02% (apartment rate assumed equal)",
    },
    # ---------------- Florida ----------------
    "Miami / South Florida, FL": {
        "state": "FL",
        "mf_vac": 0.064, "off_vac": 0.083,
        "vac_source": f"{LEE} MF Q2 2026 (6.4%) and Office Q2 2026 (8.3%)",
        "tax_commercial": 0.0179, "tax_apartment": 0.0179,
        "tax_source": f"{LINCOLN}: Miami commercial 1.79% (apartment rate assumed equal)",
    },
    "Tampa, FL": {
        "state": "FL",
        "ind_vac": 0.076, "off_vac": 0.135,
        "vac_source": f"{LEE} Industrial Q3 2026 (7.6%) and Office Q2 2026 (13.5%)",
        "tax_commercial": 0.0187, "tax_apartment": 0.0187,
        "tax_source": f"{LINCOLN}: Tampa commercial 1.87% (apartment rate assumed equal)",
    },
    "Orlando, FL": {
        "state": "FL",
        "ind_vac": 0.095, "off_vac": 0.166,
        "vac_source": f"{MATTHEWS} Industrial Q3 2026 (9.5%); CBRE Office Q3 2026 (16.6%)",
        "tax_commercial": 0.0178, "tax_apartment": 0.0178,
        "tax_source": f"ASSUMPTION — average of Jacksonville, Miami and Tampa commercial rates ({LINCOLN})",
    },
    "Jacksonville, FL": {
        "state": "FL",
        "ind_vac": 0.099, "vac_source": f"{MATTHEWS} Industrial Q3 2026 (9.9%)",
        "tax_commercial": 0.0168, "tax_apartment": 0.0165,
        "tax_source": f"{LINCOLN}: Jacksonville commercial 1.68%, apartment 1.65%",
    },
    # ---------------- South Carolina ----------------
    "Charleston, SC": {
        "state": "SC",
        "tax_commercial": 0.0193, "tax_apartment": 0.0177,
        "tax_source": f"{LINCOLN}: Charleston commercial 1.93%, apartment 1.77%",
    },
    "Greenville, SC": {
        "state": "SC",
        "ind_vac": 0.075, "off_vac": 0.058,
        "vac_source": f"{LEE} Industrial and Office Q3 2026 (7.5%, 5.8%)",
        "tax_commercial": 0.0193, "tax_apartment": 0.0177,
        "tax_source": "ASSUMPTION — Charleston rates used as a South Carolina proxy",
    },
    # ---------------- Alabama ----------------
    "Birmingham, AL": {
        "state": "AL",
        "tax_commercial": 0.0104, "tax_apartment": 0.0102,
        "tax_source": f"ASSUMPTION — Huntsville rates (1.04% / 1.02%) used as an Alabama proxy ({LINCOLN})",
    },
}

# ---------------- How property taxes behave after a sale, by state ----------------
TAX_RULES = {
    "GA": {"type": "sale", "text": "Georgia assessors typically use the sale price to set next year's value, "
                                   "so taxes reset to the purchase price."},
    "FL": {"type": "sale", "text": "Florida's 10% cap on non-homestead assessments resets on a change of "
                                   "ownership, so taxes reset to market value the year after a sale."},
    "SC": {"type": "sale", "factor": 0.75,
           "text": "South Carolina reassesses at fair market value after an assessable transfer of interest; "
                   "non-homestead property receives a 25% point-of-sale exemption (taxed on 75% of value). Verify locally."},
    "AL": {"type": "sale", "text": "Alabama reappraises annually toward market value, so a buyer's taxes "
                                   "track the purchase price."},
    "NC": {"type": "cycle", "default_years": 3,
           "text": "North Carolina doesn't reassess at sale; counties revalue on a cycle of up to 8 years. "
                   "The buyer keeps the current bill until the next county revaluation."},
    "TN": {"type": "cycle", "default_years": 3,
           "text": "Tennessee doesn't reassess at sale; counties reappraise every 4–6 years (Davidson and Shelby "
                   "every 4) and values stay unchanged in between."},
}
FIRST_HOLD_YEAR = 2027   # year 1 of the buyer's hold


def years_to_reval(market: str) -> int:
    row = MARKETS[market]
    if "next_reval_calendar_year" in row:
        return max(1, row["next_reval_calendar_year"] - FIRST_HOLD_YEAR + 1)
    return TAX_RULES[row["state"]].get("default_years", 1)


# ---------------- Cap rate benchmarks: every published local data point, with its quarter ----------------
# (value, source, year, quarter). Confidence comes from how many recent local points exist and how well they agree.
CAP_POINTS = {
    "Atlanta, GA": {
        "multifamily": [(0.0557, "Matthews", 2026, 3), (0.0538, "Lee & Associates", 2026, 2)],
        "industrial": [(0.0603, "Matthews", 2026, 3), (0.0660, "Lee & Associates", 2026, 3)],
        "office": [(0.0860, "Lee & Associates", 2026, 3)],
    },
    "Charlotte, NC": {
        "multifamily": [(0.0533, "Matthews", 2026, 2), (0.0540, "Lee & Associates", 2025, 4)],
        "industrial": [(0.0649, "Matthews", 2026, 3), (0.0721, "Lee & Associates", 2026, 3)],
        "office": [(0.0789, "Lee & Associates", 2026, 3)],
    },
    "Raleigh-Durham, NC": {
        "multifamily": [(0.0530, "Lee & Associates (Raleigh)", 2026, 2)],
        "industrial": [(0.0780, "Lee & Associates (Raleigh)", 2026, 3), (0.0718, "Lee & Associates (Durham)", 2026, 3)],
        "office": [(0.0850, "Lee & Associates (Raleigh)", 2026, 3), (0.0870, "Lee & Associates (Durham)", 2026, 3)],
    },
    "Nashville, TN": {
        "multifamily": [(0.0544, "Matthews", 2026, 2), (0.0570, "Lee & Associates", 2026, 2)],
        "industrial": [(0.0651, "Matthews", 2026, 3), (0.0610, "Matthews", 2026, 2)],
        "office": [(0.0780, "Lee & Associates", 2026, 3)],
    },
    "Memphis, TN": {
        "multifamily": [(0.0699, "Matthews", 2026, 3)],
        "industrial": [(0.0883, "Matthews", 2026, 3)],
    },
    "Miami / South Florida, FL": {
        "multifamily": [(0.0638, "Lee & Associates", 2026, 2)],
        "industrial": [(0.0698, "Lee & Associates", 2026, 2)],
        "office": [(0.0717, "Lee & Associates", 2026, 3), (0.0670, "BNP Paribas RE (Miami)", 2026, 2)],
    },
    "Tampa, FL": {
        "multifamily": [(0.0550, "Northmarq", 2025, 1)],
        "industrial": [(0.0746, "Lee & Associates", 2026, 3), (0.0760, "Matthews", 2026, 2)],
        "office": [(0.0860, "Lee & Associates", 2026, 2)],
    },
    "Orlando, FL": {
        "multifamily": [(0.0525, "Northmarq (midpoint of 5.0–5.5%)", 2025, 4)],
        "industrial": [(0.0637, "Matthews", 2026, 3), (0.0670, "Lee & Associates", 2026, 3)],
    },
    "Jacksonville, FL": {
        "multifamily": [(0.0530, "Berkadia", 2024, 4)],
        "industrial": [(0.0715, "Matthews", 2026, 3)],
    },
    "Charleston, SC": {
        "multifamily": [(0.0540, "Berkadia", 2024, 4)],
        "industrial": [(0.0771, "Lee & Associates", 2025, 3)],
    },
    "Greenville, SC": {
        "multifamily": [(0.0570, "Berkadia", 2024, 4)],
        "industrial": [(0.0740, "Lee & Associates", 2026, 2)],
        "office": [(0.0700, "Lee & Associates", 2026, 3), (0.0780, "Lee & Associates", 2026, 2)],
    },
    "Birmingham, AL": {
        "multifamily": [(0.0560, "Berkadia", 2024, 4)],
    },
}
LATEST = (2026, 3)   # most recent quarter of published data

# Recent quarterly history for a source, where we've checked it against the original publication. A source whose own
# figure swings widely quarter to quarter is averaging a thin, changing mix of sales, so confidence is capped.
SOURCE_HISTORY = {
    ("Atlanta, GA", "industrial", "Lee & Associates"): {
        "values": [0.066, 0.065, 0.058, 0.066],          # Q3'26, Q2'26, Q1'26, Q4'25
        "note": "Lee & Associates' Atlanta industrial cap rate moved 5.8%–6.6% over the last four quarters "
                "(Q3 2026 report; buildings 15,000 SF+)."},
}
BENCHMARK_SCOPE = ("Published figures are market-wide averages across all sales of that property type (mostly "
                   "CoStar-based). They aren't adjusted for your building's size, age, location or tenant credit, so "
                   "they're a starting point, not a property-specific conclusion. Comparable sales of similar "
                   "buildings are the best check.")
VERIFIED = {("Atlanta, GA", "industrial"): "Checked Nov 2026 against Matthews 'Atlanta, GA Industrial Market Report Q3 "
                                           "2026' (6.03%) and Lee & Associates 'Q3 2026 Atlanta, GA Industrial' (6.6%)."}
MARKET_TIER = {m: "primary" for m in ["Atlanta, GA", "Charlotte, NC", "Raleigh-Durham, NC", "Nashville, TN",
                                       "Miami / South Florida, FL", "Tampa, FL", "Orlando, FL"]}
MARKET_TIER.update({m: "secondary" for m in ["Jacksonville, FL", "Memphis, TN", "Charleston, SC", "Greenville, SC",
                                              "Birmingham, AL"]})
MARKET_TIER["Athens, GA"] = "tertiary"

# Fallback when no local point exists: local multifamily + national sector spread
SECTOR_SPREAD = {"multifamily": 0.0, "industrial": 0.0102, "office": 0.0267}
SECTOR_SOURCE = "national sector spread over local multifamily (Apartment Loan Store, Nov 2026)"
CLASS_SPREAD = {
    "multifamily": {"A": -0.0043, "B": 0.0, "C": 0.0047},
    "industrial":  {"A": -0.0095, "B": 0.0, "C": 0.0130},
    "office":      {"A": -0.0080, "B": 0.0, "C": 0.0085},
}
CLASS_SOURCE = "Class spreads from Apartment Loan Store national table, Nov 2026 (market average treated as Class B)"


def _age_q(y, q):
    return (LATEST[0] * 4 + LATEST[1]) - (y * 4 + q)


def cap_benchmark(sector: str, market: str) -> dict:
    """Benchmark cap rate (Class B) with its evidence and a confidence level."""
    pts = CAP_POINTS.get(market, {}).get(sector, [])
    if market == "Athens, GA":   # no published Athens data: Atlanta + 25 bps
        b = cap_benchmark(sector, "Atlanta, GA")
        return {"cap": b["cap"] + 0.0025, "points": b["points"], "confidence": "Low", "scope": BENCHMARK_SCOPE,
                "why": "No published Athens data; Atlanta benchmark + 25 bps for a smaller, less liquid market.",
                "label": "Atlanta benchmark + 25 bps (assumption)"}
    if not pts:
        mf = cap_benchmark("multifamily", market)
        return {"cap": mf["cap"] + SECTOR_SPREAD[sector], "points": mf["points"], "confidence": "Low",
                "scope": BENCHMARK_SCOPE,
                "why": f"No local {sector} cap rate is published for this market; estimated from the local "
                       f"multifamily benchmark plus a {SECTOR_SOURCE}.",
                "label": f"Estimated ({SECTOR_SOURCE})"}
    recent = [p for p in pts if _age_q(p[2], p[3]) <= 4] or pts
    cap = sum(p[0] for p in recent) / len(recent)
    fresh = [p for p in pts if _age_q(p[2], p[3]) <= 2]
    spread = max(p[0] for p in recent) - min(p[0] for p in recent)
    if len(fresh) >= 2 and spread <= 0.0075:
        conf, why = "High", f"{len(fresh)} recent local sources agree within {spread * 100:.2f} pts."
    elif any(_age_q(p[2], p[3]) <= 4 for p in pts):
        if len(recent) >= 2:
            conf, why = "Medium", f"Local sources differ by {spread * 100:.2f} pts; the benchmark is their average."
        else:
            conf, why = "Medium", "One recent local source."
    else:
        conf, why = "Low", "Local data is more than a year old."
    for p in recent:
        h = SOURCE_HISTORY.get((market, sector, p[1]))
        if h and max(h["values"]) - min(h["values"]) > 0.006:
            if conf == "High":
                conf = "Medium"
            why += " " + h["note"] + " That volatility limits confidence."
    if (market, sector) in VERIFIED:
        why += " " + VERIFIED[(market, sector)]
    label = ("Average of " + "; ".join(f"{p[1]} Q{p[3]} {p[2]}: {p[0]:.2%}" for p in recent)
             + " — market-wide survey averages, not a property-specific conclusion")
    return {"cap": cap, "points": pts, "confidence": conf, "why": why, "label": label, "scope": BENCHMARK_SCOPE}


def stabilized_vacancy(sector: str, market: str) -> tuple[float, str]:
    """Market vacancy where published, kept between the underwriting floor and floor + 5 pts."""
    floor = STANDARD[sector]["vacancy_floor"]
    row = MARKETS[market]
    mv = row.get(f"{_PREFIX[sector]}_vac")
    if mv is None:
        return floor, f"{floor:.0%} underwriting floor (no local vacancy figure)"
    v = min(max(mv, floor), floor + 0.05)
    return v, f"Market vacancy {mv:.1%} ({row['vac_source']}), bounded to {floor:.0%}–{floor + 0.05:.0%}"


_PREFIX = {"multifamily": "mf", "industrial": "ind", "office": "off"}

# ---------------- Discount rate (independently underwritten) ----------------
# Base = class-adjusted cap rate + the discount-rate-over-cap spread investors report by sector.
# Newmark Valuation & Advisory Market Survey, 2025 mid-year update (national averages):
#   Warehouse/logistics: cap 5.62%, discount 6.90% (+128 bps); suburban multifamily: 5.40% / 7.00% (+160 bps);
#   suburban office: 8.21% / 9.54% (+133 bps). Reversion (exit) cap: +42–48 bps over going-in.
DISCOUNT_SPREAD = {"multifamily": 0.0160, "industrial": 0.0128, "office": 0.0133}
EXIT_SPREAD = {"multifamily": 0.0042, "industrial": 0.0045, "office": 0.0047}
DISCOUNT_SOURCE = ("Newmark Valuation & Advisory Market Survey (2025 mid-year): discount rate exceeds going-in cap by "
                   "~128 bps (industrial), ~160 bps (suburban multifamily), ~133 bps (suburban office); exit caps "
                   "42–48 bps above going-in")

# ---------------- Standard underwriting assumptions ----------------
# Rent and expense growth: Newmark survey averages. Others are RULES OF THUMB — review and replace with local data.
STANDARD = {
    "multifamily": {
        "vacancy_floor": 0.05, "credit_loss": 0.02, "mgmt_fee": 0.03, "reserves": 300,
        "rent_growth": 0.0273, "absorb_per_month": 0.02, "leaseup_cost_months": 1.0,
        "note": "Mgmt 3% of revenue, reserves $300/unit, credit loss 2% (v1 spec); rent growth 2.73% (Newmark survey); "
                "RULE OF THUMB: lease-up 2% of units/month at one month's rent per new lease",
    },
    "industrial": {
        "vacancy_floor": 0.05, "credit_loss": 0.01, "mgmt_fee": 0.03, "reserves": 0.15,
        "rent_growth": 0.0278, "absorb_per_month": 0.02,
        "note": "Rent growth 2.78% (Newmark survey). RULE OF THUMB: credit loss 1%, mgmt 3% (recoverable on NNN), "
                "structural reserves $0.15/SF, lease-up 2% of the building per month",
    },
    "office": {
        "vacancy_floor": 0.10, "credit_loss": 0.01, "mgmt_fee": 0.03, "reserves": 0.30,
        "rent_growth": 0.0152, "absorb_per_month": 0.01,
        "note": "Rent growth 1.52% (Newmark survey, suburban office). RULE OF THUMB: credit loss 1%, mgmt 3% "
                "(recoverable on NNN), structural reserves $0.30/SF, lease-up 1% of the building per month",
    },
}
# Lease rollover assumptions (RULES OF THUMB; editable in the app)
LEASING = {
    "industrial": {"renewal_prob": 0.70, "downtime": 6, "ti_new": 5.0, "ti_renew": 2.0, "lc_new": 0.06,
                   "lc_renew": 0.03, "term": 5, "free_new": 2, "free_renew": 0, "bump": 0.03,
                   "vacant_type": "nnn"},
    "office": {"renewal_prob": 0.65, "downtime": 9, "ti_new": 40.0, "ti_renew": 15.0, "lc_new": 0.06,
               "lc_renew": 0.03, "term": 7, "free_new": 5, "free_renew": 1, "bump": 0.025,
               "vacant_type": "base_year"},
}
LEASING_NOTE = ("RULE OF THUMB lease rollover: industrial 70% renewal, 6 months downtime, TI $5 new / $2 renewal per SF, "
                "commissions 6% new / 3% renewal of term rent, 5-year terms, 3% bumps; office 65% renewal, 9 months "
                "downtime, TI $40 / $15, 6% / 3% commissions, 7-year terms, 2.5% bumps, 5 / 1 months free rent")
# Expense growth by category (taxes follow the property-tax schedule)
EXPENSE_GROWTH = {"insurance": 0.05, "utilities": 0.03, "payroll": 0.035, "other": 0.03}
EXPENSE_GROWTH_NOTE = ("Expense growth by category: insurance 5% (RULE OF THUMB, reflecting Southeast premium "
                       "trends), utilities 3%, payroll 3.5%, other 3% (Newmark survey average expense growth ~3%)")
HOLD_YEARS = 10
SELLING_COSTS = 0.02


# ----------------------------------------------------------------------
# Quick estimate defaults — used only when the owner doesn't enter expenses
# Operating expenses EXCLUDING property taxes, management and reserves (those are modeled separately).
# Rules of thumb for Southeast properties; shown to the user and replaced as soon as they enter real numbers.
QUICK_OPEX = {"multifamily": 5000.0,   # $/unit/yr: insurance, utilities, repairs, payroll, admin, marketing
              "industrial": 1.25,      # $/SF/yr: insurance, CAM, repairs
              "office": 7.50}          # $/SF/yr: utilities, janitorial, repairs, insurance, security, admin
QUICK_OPEX_NOTE = ("Rule-of-thumb operating expenses (before property taxes, management and reserves): apartments "
                   "$5,000/unit, industrial $1.25/SF, office $7.50/SF per year. Replace with your T-12 for accuracy.")


# Quick estimate: answer to "When do most of your tenants' leases expire?" -> (share of leased space, month it expires)
def lease_profile(answer: str, sector: str) -> list[tuple[float, int]]:
    T = int(LEASING[sector]["term"] * 12)
    return {
        "Within 12 months": [(0.2, 3), (0.2, 7), (0.2, 11), (0.2, 24), (0.2, 42)],
        "1–3 years": [(0.2, 16), (0.2, 26), (0.2, 35), (0.2, 48), (0.2, T)],
        "More than 3 years": [(0.2, 24), (0.2, 40), (0.2, 48), (0.2, max(56, int(T * 0.85))), (0.2, max(64, T))],
    }.get(answer, [(0.2, max(1, round(T * (i + 0.5) / 5))) for i in range(5)])   # Not sure: evenly staggered


# ----------------------------------------------------------------------
# Industrial subtypes
# Evidence: Matthews (Q2 2026, Charlotte) — sub-125K SF industrial traded at $165/SF and a 5.7% cap vs. $119/SF and 7.2%
# market-wide; Lee & Associates Charlotte reports show 1M+ SF bulk sales at $97–$101/SF (Q3–Q4 2025). Those support
# the small-bay premium and bulk discount. Manufacturing, flex and cold-storage adjustments are judgment-based
# assumptions (no Southeast survey splits them out) and are labeled that way to the user.
INDUSTRIAL_SUBTYPES = {
    "Bulk distribution": {
        "why": "Large facilities, often one tenant — concentrated tenant exposure.",
        "cap_adj": 0.0, "price_mult": 0.85, "groups": 1, "quick_opex": 1.00,
        "leasing": {"renewal_prob": 0.70, "downtime": 9, "ti_new": 3.0, "ti_renew": 1.0, "term": 7, "free_new": 3},
        "evidence": "Price discount supported by large Charlotte bulk sales (Lee & Associates); cap rate at market.",
    },
    "Small-bay / multi-tenant": {
        "why": "Many short leases; more turnover but higher rents per SF and deep tenant demand.",
        "cap_adj": -0.0025, "price_mult": 1.30, "groups": 5, "quick_opex": 1.75,
        "leasing": {"renewal_prob": 0.65, "downtime": 4, "ti_new": 4.0, "ti_renew": 1.5, "term": 3, "free_new": 1},
        "evidence": "Premium pricing and lower caps for sub-125K SF buildings (Matthews, Charlotte Q2 2026).",
    },
    "Manufacturing": {
        "why": "Specialized improvements; harder and slower to re-lease if the tenant leaves.",
        "cap_adj": 0.0075, "price_mult": 0.70, "groups": 1, "quick_opex": 1.25,
        "leasing": {"renewal_prob": 0.75, "downtime": 12, "ti_new": 8.0, "ti_renew": 2.0, "term": 7, "free_new": 3},
        "evidence": "Judgment-based assumption (+75 bps cap, 12 months downtime) — not from a published survey.",
    },
    "Flex / light industrial": {
        "why": "More office build-out; demand comes from different, smaller tenants.",
        "cap_adj": 0.0025, "price_mult": 1.20, "groups": 5, "quick_opex": 3.00,
        "leasing": {"renewal_prob": 0.60, "downtime": 8, "ti_new": 12.0, "ti_renew": 4.0, "term": 4, "free_new": 2},
        "evidence": "Judgment-based assumption (+25 bps cap, office-like improvement costs) — not from a published survey.",
    },
    "Cold storage": {
        "why": "Specialized refrigeration systems; higher operating and replacement costs.",
        "cap_adj": 0.0050, "price_mult": 1.50, "groups": 1, "quick_opex": 3.50,
        "leasing": {"renewal_prob": 0.75, "downtime": 12, "ti_new": 15.0, "ti_renew": 4.0, "term": 10, "free_new": 3},
        "std": {"reserves": 0.40},
        "evidence": "Judgment-based assumption (+50 bps cap, higher reserves) — not from a published survey.",
    },
}


def suggest_subtype(size_sf: float) -> str:
    if size_sf >= 250_000:
        return "Bulk distribution"
    if size_sf < 75_000:
        return "Small-bay / multi-tenant"
    return "Bulk distribution"


def leasing_for(sector: str, subtype: str | None = None) -> dict:
    base = dict(LEASING[sector])
    if sector == "industrial" and subtype in INDUSTRIAL_SUBTYPES:
        base.update(INDUSTRIAL_SUBTYPES[subtype]["leasing"])
    return base


# ----------------------------------------------------------------------
# Published average sale prices (per SF; per unit for apartments) — used ONLY for a reasonableness check, never to
# set the value. These are market-wide averages of all sales of that type, so they're a broad sanity band.
PRICE_POINTS = {
    "Atlanta, GA": {"industrial": [(135, "Matthews", 2026, 3), (137, "Lee & Associates", 2026, 3)],
                    "office": [(210, "Lee & Associates", 2026, 3)],
                    "multifamily": [(189_000, "Matthews", 2026, 3)]},
    "Charlotte, NC": {"industrial": [(127, "Matthews", 2026, 3), (120, "Lee & Associates", 2026, 3)],
                      "office": [(266, "Lee & Associates", 2026, 3)],
                      "multifamily": [(219_000, "Matthews", 2026, 3)]},
    "Raleigh-Durham, NC": {"industrial": [(158, "Lee & Associates (Raleigh)", 2026, 3),
                                          (144, "Lee & Associates (Durham)", 2026, 3)],
                           "office": [(225, "Lee & Associates (Raleigh)", 2026, 3),
                                      (223, "Lee & Associates (Durham)", 2026, 3)],
                           "multifamily": [(213_000, "Matthews", 2026, 3)]},
    "Nashville, TN": {"industrial": [(162, "Matthews", 2026, 3)], "multifamily": [(216_000, "Matthews", 2026, 3)]},
    "Memphis, TN": {"multifamily": [(89_000, "Matthews", 2026, 3)]},
    "Miami / South Florida, FL": {"industrial": [(268, "Lee & Associates (South Florida)", 2026, 3)],
                                  "office": [(357, "Lee & Associates (South Florida)", 2026, 3),
                                             (253, "Lee & Associates (South Florida)", 2026, 2)]},
    "Tampa, FL": {"industrial": [(156, "Matthews", 2026, 2)], "office": [(211, "Lee & Associates", 2026, 2)],
                  "multifamily": [(207_000, "Matthews", 2026, 2)]},
    "Orlando, FL": {"industrial": [(182, "Matthews", 2026, 3), (164, "Lee & Associates", 2026, 2)],
                    "multifamily": [(222_000, "Matthews", 2026, 3)]},
    "Jacksonville, FL": {"industrial": [(117, "Matthews", 2026, 3)]},
}
PRICE_CLASS_MULT = {"A": 1.20, "B": 1.00, "C": 0.75}   # judgment-based: class mix behind a market average


def price_benchmark(sector: str, market: str, subtype: str | None = None, pclass: str | None = None) -> dict | None:
    pts = PRICE_POINTS.get(market, {}).get(sector)
    if not pts and market == "Athens, GA":
        pts = PRICE_POINTS["Atlanta, GA"].get(sector)
        if pts:
            pts = [(p[0] * 0.85, p[1] + " (Atlanta × 0.85 for Athens)", p[2], p[3]) for p in pts]
    if not pts:
        return None
    avg = sum(p[0] for p in pts) / len(pts)
    mult, notes = 1.0, []
    if sector == "industrial" and subtype in INDUSTRIAL_SUBTYPES:
        mult *= INDUSTRIAL_SUBTYPES[subtype]["price_mult"]
        notes.append(f"{subtype} × {INDUSTRIAL_SUBTYPES[subtype]['price_mult']:.2f}")
    if pclass in PRICE_CLASS_MULT and pclass != "B":
        mult *= PRICE_CLASS_MULT[pclass]
        notes.append(f"Class {pclass} × {PRICE_CLASS_MULT[pclass]:.2f}")
    mid = avg * mult
    spread = max(p[0] for p in pts) / min(p[0] for p in pts) - 1
    return {"market_avg": avg, "mid": mid, "low": mid * 0.75, "high": mid * 1.25, "points": pts,
            "adjustments": notes, "volatile": spread > 0.25,
            "unit": "per unit" if sector == "multifamily" else "per SF"}
