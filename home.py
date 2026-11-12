"""
Single-family home valuation — sales comparison approach (how appraisers value houses).

Each comparable sale is adjusted toward the subject home:
  "If this comp were exactly like the owner's house, what would it have sold for?"
Then the adjusted prices are weighted — comps needing smaller adjustments count more.

Adjustment rates below are RULES OF THUMB, not survey data. They vary by market and price
point; review and tune them with local appraisal knowledge.
"""
from __future__ import annotations

from datetime import date
from statistics import median

ADJ = {
    "size_share": 0.50,       # extra SF valued at 50% of the comps' median $/SF (bigger homes sell at lower $/SF)
    "bedroom_pct": 0.015,     # per bedroom, % of median comp price (size already captures most of it)
    "bath_pct": 0.025,        # per full bath (half bath = 0.5), % of median comp price
    "age_pct_per_year": 0.0025,  # per year of age difference, % of comp price, capped below
    "age_cap": 0.10,
    "condition_pct": 0.075,   # comp noticeably better/worse than the subject
}
CONDITION_SHIFT = {"Worse than mine": +1, "Similar": 0, "Better than mine": -1}
ASSUMPTION_NOTE = ("RULES OF THUMB — size difference at 50% of median comp $/SF; bedroom 1.5% and full bath "
                   "2.5% of median comp price; age 0.25%/year (max 10%); condition ±7.5%")


def _years_between(d1: date, d2: date) -> float:
    return (d2 - d1).days / 365.25


def adjust_comps(subject: dict, comps: list[dict], appreciation: float = 0.0,
                 today: date | None = None) -> list[dict]:
    today = today or date.today()
    # Time-adjust first so size/feature rates are based on today's prices
    for c in comps:
        yrs = max(0.0, _years_between(c["sale_date"], today))
        c["time_adj"] = c["price"] * appreciation * yrs
        c["months_ago"] = yrs * 12
    tp = [c["price"] + c["time_adj"] for c in comps]
    med_price = median(tp)
    med_psf = median(p / c["sf"] for p, c in zip(tp, comps))

    out = []
    for c, base in zip(comps, tp):
        size = (subject["sf"] - c["sf"]) * med_psf * ADJ["size_share"]
        beds = (subject["beds"] - c["beds"]) * med_price * ADJ["bedroom_pct"]
        baths = (subject["baths"] - c["baths"]) * med_price * ADJ["bath_pct"]
        age_pct = max(-ADJ["age_cap"], min(ADJ["age_cap"],
                      (subject["year_built"] - c["year_built"]) * ADJ["age_pct_per_year"]))
        age = base * age_pct
        cond = base * ADJ["condition_pct"] * CONDITION_SHIFT[c["condition"]]
        lines = {"Sale date / market change": c["time_adj"], "Size": size, "Bedrooms": beds,
                 "Bathrooms": baths, "Age": age, "Condition": cond}
        adjusted = c["price"] + sum(lines.values())
        gross = sum(abs(v) for v in lines.values()) / c["price"]
        flags = []
        if c["months_ago"] > 12:
            flags.append("sold over 12 months ago")
        if abs(c["sf"] - subject["sf"]) / subject["sf"] > 0.25:
            flags.append("size differs by more than 25%")
        if gross > 0.25:
            flags.append("adjustments exceed 25% of price")
        out.append({**c, "lines": lines, "adjusted": adjusted, "gross_pct": gross, "flags": flags,
                    "weight_raw": 1 / (gross + 0.05)})

    total_w = sum(c["weight_raw"] for c in out)
    for c in out:
        c["weight"] = c["weight_raw"] / total_w
    return out


def estimate_home(subject: dict, comps: list[dict], appreciation: float = 0.0,
                  today: date | None = None, capex: float = 0.0) -> dict:
    if len(comps) < 3:
        raise ValueError("Enter at least 3 comparable sales.")
    adj = adjust_comps(subject, comps, appreciation, today)
    value = sum(c["adjusted"] * c["weight"] for c in adj) - capex
    adjusted_prices = sorted(c["adjusted"] - capex for c in adj)
    return {
        "value": value, "low": adjusted_prices[0], "high": adjusted_prices[-1],
        "per_sf": value / subject["sf"], "comps": adj, "capex": capex,
        "spread_pct": (adjusted_prices[-1] - adjusted_prices[0]) / value,
        "assumptions": ASSUMPTION_NOTE,
    }


def rental_check(value: float, monthly_rent: float, annual_costs: float, vacancy: float = 0.05) -> dict:
    """If the owner rents the house out: what yield does this value imply?"""
    gross = monthly_rent * 12
    noi = gross * (1 - vacancy) - annual_costs
    return {"gross_yield": gross / value, "net_yield": noi / value, "noi": noi,
            "price_to_rent": value / gross if gross else None}


def quick_estimate(sf: float, comps: list[dict]) -> dict:
    """Quick home estimate from 2–3 nearby sales: price and size only (no feature adjustments).
    Each sale is adjusted for size at 50% of the median $/SF; the estimate is the average adjusted price."""
    if len(comps) < 2:
        raise ValueError("Enter at least 2 recent nearby sales.")
    med_psf = median(c["price"] / c["sf"] for c in comps)
    adj = [{**c, "adjusted": c["price"] + (sf - c["sf"]) * med_psf * ADJ["size_share"]} for c in comps]
    vals = sorted(a["adjusted"] for a in adj)
    value = sum(vals) / len(vals)
    spread = max(vals[-1] - value, value - vals[0], 0.05 * value)   # at least ±5%
    return {"value": value, "low": value - spread, "high": value + spread, "per_sf": value / sf,
            "comps": adj, "med_psf": med_psf}
