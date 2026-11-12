"""
Historical-sales validation.

    python validation.py my_sales.csv            -> validation_results.csv + validation_summary.md

For every sale it runs up to three valuations and compares each with the actual price:

  1. Quick         only what an ordinary owner knows: size, occupancy, contract rent, lease type, rough lease
                   expirations, subtype, class. Expenses and taxes use the site's defaults.
  2. Detailed      adds the operating information available at the sale date: expenses, taxes, market rent,
                   weighted remaining lease term.
  3. Detailed @    Detailed, but with the market cap rate at the sale date (column market_cap_at_sale) in place
     sale-date cap of today's benchmark.

Comparing the three separates the sources of error:
  • Quick vs. Detailed            -> accuracy lost to missing owner inputs
  • Detailed vs. Detailed @ cap   -> error from market assumptions (today's cap rate vs. the one at the sale)
  • Detailed @ cap vs. sale price -> what's left: the valuation engine itself and property facts it can't see
Where in_place_noi is given, the model's current NOI is also compared with the actual NOI, which shows whether
the income side or the cap-rate side is driving a miss.

Do NOT calibrate the model on sales whose rents and expenses were estimated rather than verified: you'd be fitting
the model to your guesses. Mark verified rows with verified=yes and the summary reports them separately.
"""
from __future__ import annotations

import argparse
import math
import sys
from statistics import mean, median

import pandas as pd

import market_data as md
from underwriting import Inputs, ValuationError, underwrite

COLUMNS = ["property_id", "sale_date", "market", "sector", "subtype", "sale_price", "size", "occupancy",
           "contract_rent", "market_rent", "lease_type", "lease_expiry", "wtd_lease_term_years", "in_place_noi",
           "opex", "property_taxes", "year_built", "building_class", "market_cap_at_sale", "verified", "notes"]
LEASE = {"nnn": "nnn", "triple net": "nnn", "modified gross": "base_year", "base year": "base_year",
         "gross": "gross", "full-service gross": "gross", "full service gross": "gross"}
EXPIRY = {"within 12 months": "Within 12 months", "1-3 years": "1–3 years", "1–3 years": "1–3 years",
          "more than 3 years": "More than 3 years", "not sure": "Not sure"}


def template() -> pd.DataFrame:
    return pd.DataFrame([{
        "property_id": "EXAMPLE-1 (replace with real sales)", "sale_date": "2026-06-30", "market": "Atlanta, GA",
        "sector": "industrial", "subtype": "Bulk distribution", "sale_price": 14_500_000, "size": 120_000,
        "occupancy": 1.0, "contract_rent": 7.25, "market_rent": 8.00, "lease_type": "NNN",
        "lease_expiry": "More than 3 years", "wtd_lease_term_years": 5.5, "in_place_noi": 830_000, "opex": 150_000,
        "property_taxes": 210_000, "year_built": 2015, "building_class": "", "market_cap_at_sale": 0.060,
        "verified": "no", "notes": "Illustrative row showing the format — not a real transaction."}],
        columns=COLUMNS)


def _num(v):
    try:
        f = float(str(v).replace("$", "").replace(",", "").replace("%", ""))
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _class(row) -> str | None:
    c = str(row.get("building_class") or "").strip().upper()
    if c in ("A", "B", "C"):
        return c
    yb = _num(row.get("year_built"))
    if yb:
        return "A" if yb >= 2010 else "B" if yb >= 1990 else "C"
    return None


def _suites(sector, subtype, size, occ, rent, market, lt, expiry=None, walt_years=None):
    term = md.leasing_for(sector, subtype)["term"]
    groups = md.INDUSTRIAL_SUBTYPES[subtype]["groups"] if subtype in md.INDUSTRIAL_SUBTYPES else 5
    if walt_years:
        m = max(1, int(walt_years * 12))
        profile = [(1.0, m)] if groups == 1 else [(0.2, max(1, int(m * f))) for f in (0.4, 0.7, 1.0, 1.3, 1.6)]
    elif groups == 1:
        profile = [(1.0, {"Within 12 months": 8, "1–3 years": 24,
                          "More than 3 years": max(54, int(term * 12 * 0.7))}.get(expiry, int(term * 6)))]
    else:
        profile = md.lease_profile(expiry or "Not sure", sector)
    leased = size * occ
    out = [{"suite": f"g{i}", "tenant": "x", "sf": leased * sh, "rent": leased * sh * rent, "lease_type": lt,
            "months_left": mo, "vacant": False, "market_psf": market} for i, (sh, mo) in enumerate(profile)]
    if size - leased > 0:
        out.append({"suite": "v", "tenant": "", "sf": size - leased, "rent": 0.0, "lease_type": lt,
                    "months_left": None, "vacant": True, "market_psf": market})
    return out


def build_inputs(row: dict, mode: str) -> Inputs:
    sector = str(row["sector"]).strip().lower()
    sector = {"apartments": "multifamily", "apartment": "multifamily"}.get(sector, sector)
    subtype = row.get("subtype") if sector == "industrial" and row.get("subtype") in md.INDUSTRIAL_SUBTYPES else None
    size = _num(row["size"])
    occ = _num(row["occupancy"])
    occ = occ / 100 if occ and occ > 1 else occ
    rent = _num(row["contract_rent"])
    detailed = mode != "quick"
    market = (_num(row.get("market_rent")) if detailed else None) or rent
    k = 12 if sector == "multifamily" else 1
    gpr = rent * size * occ * k + market * size * (1 - occ) * k
    cls = _class(row)
    opex = _num(row.get("opex")) if detailed else None
    if opex is None:
        opex = (md.INDUSTRIAL_SUBTYPES[subtype]["quick_opex"] if subtype else md.QUICK_OPEX[sector]) * size
    tax = _num(row.get("property_taxes")) if detailed else None
    kw = dict(sector=sector, market=row["market"], size=size, gpr=gpr, physical_vacancy=1 - occ, opex=opex,
              pclass=cls, current_tax=tax, subtype=subtype, quality_grade="B")
    if tax is not None:
        kw["tax_mode"] = "cycle"          # an actual bill at the sale date: use it as the year-1 tax
        kw["years_to_reval"] = 2
    if mode == "detailed_cap":
        c = _num(row.get("market_cap_at_sale"))
        c = c / 100 if c and c > 1 else c
        sub_adj = md.INDUSTRIAL_SUBTYPES[subtype]["cap_adj"] if subtype else 0.0
        kw["cap_override"] = c + md.CLASS_SPREAD[sector][cls or "B"] + sub_adj
    if sector == "multifamily":
        return Inputs(**kw, quick=not detailed)
    lt = LEASE.get(str(row.get("lease_type") or "").strip().lower(), "nnn" if sector == "industrial" else "gross")
    expiry = EXPIRY.get(str(row.get("lease_expiry") or "").strip().lower(), "Not sure")
    walt = _num(row.get("wtd_lease_term_years")) if detailed else None
    suites = _suites(sector, subtype, size, occ, rent, market, lt, expiry, walt)
    return Inputs(**kw, suites=suites, quick=(not walt and expiry == "Not sure"))


def run(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        row = r.to_dict()
        price = _num(row.get("sale_price"))
        out = {"property_id": row.get("property_id"), "sector": row.get("sector"), "subtype": row.get("subtype"),
               "market": row.get("market"), "sale_price": price,
               "verified": str(row.get("verified") or "").strip().lower() in ("yes", "y", "true", "1")}
        modes = ["quick", "detailed"] + (["detailed_cap"] if _num(row.get("market_cap_at_sale")) else [])
        for mode in modes:
            try:
                res = underwrite(build_inputs(row, mode), sensitivity=False)
                out[f"{mode}_value"] = res["value"]
                out[f"{mode}_error"] = res["value"] / price - 1
                if mode == "detailed":
                    out["model_cap"] = res["cap_rate"]
                    out["model_current_noi"] = res["current_noi"]["noi"]
            except (ValuationError, KeyError, TypeError, ZeroDivisionError) as e:
                out[f"{mode}_error_msg"] = str(e)[:160]
        noi = _num(row.get("in_place_noi"))
        if noi and price:
            out["implied_cap"] = noi / price
            if out.get("model_current_noi"):
                out["noi_gap"] = out["model_current_noi"] / noi - 1
        if out.get("quick_value") and out.get("detailed_value"):
            out["quick_vs_detailed"] = out["quick_value"] / out["detailed_value"] - 1
        rows.append(out)
    return pd.DataFrame(rows)


def _stats(errs):
    errs = [e for e in errs if e is not None and not (isinstance(e, float) and math.isnan(e))]
    if not errs:
        return None
    a = [abs(e) for e in errs]
    return {"n": len(errs), "median_abs": median(a), "bias": mean(errs),
            "within10": sum(x <= 0.10 for x in a) / len(a), "within20": sum(x <= 0.20 for x in a) / len(a)}


def summarize(res: pd.DataFrame) -> str:
    lines = ["# Historical-sales validation", "",
             "Errors are (estimate − sale price) ÷ sale price. Bias above 0 means the model runs high.", ""]
    groups = [("All sales", res)]
    if res["verified"].any():
        groups.append(("Verified operating data only", res[res["verified"]]))
    for sector, g in res.groupby("sector"):
        groups.append((f"Sector: {sector}", g))
    for (sector, sub), g in res.dropna(subset=["subtype"]).groupby(["sector", "subtype"]):
        groups.append((f"{sector} — {sub}", g))
    for name, g in groups:
        lines += [f"## {name}", "", "| Run | n | Median abs error | Bias | Within ±10% | Within ±20% |",
                  "|---|---:|---:|---:|---:|---:|"]
        for mode, label in (("quick", "Quick estimate"), ("detailed", "Detailed"),
                            ("detailed_cap", "Detailed @ sale-date cap")):
            col = f"{mode}_error"
            if col in g:
                s = _stats(g[col].tolist())
                if s:
                    lines.append(f"| {label} | {s['n']} | {s['median_abs']:.1%} | {s['bias']:+.1%} | "
                                 f"{s['within10']:.0%} | {s['within20']:.0%} |")
        lines.append("")
    # decomposition
    lines += ["## Where the error comes from (median absolute gap, as % of sale price)", ""]
    d = res.dropna(subset=["quick_value", "detailed_value"]) if "detailed_value" in res else res.iloc[0:0]
    if len(d):
        lines.append(f"- Missing owner inputs (Quick vs. Detailed): "
                     f"{median(abs(q - x) / p for q, x, p in zip(d.quick_value, d.detailed_value, d.sale_price)):.1%}")
    if "detailed_cap_value" in res:
        c = res.dropna(subset=["detailed_value", "detailed_cap_value"])
        if len(c):
            lines.append(f"- Market assumptions (today's cap vs. cap at sale): "
                         f"{median(abs(a - b) / p for a, b, p in zip(c.detailed_value, c.detailed_cap_value, c.sale_price)):.1%}")
            lines.append(f"- Engine and unseen property facts (Detailed @ sale-date cap vs. price): "
                         f"{median(abs(e) for e in c.detailed_cap_error):.1%}")
    if "noi_gap" in res and res["noi_gap"].notna().any():
        lines.append(f"- Income side: model current NOI vs. actual in-place NOI, median gap "
                     f"{median(abs(x) for x in res['noi_gap'].dropna()):.1%}")
    if "implied_cap" in res and res["implied_cap"].notna().any():
        z = res.dropna(subset=["implied_cap", "model_cap"])
        if len(z):
            lines.append(f"- Cap rate side: model cap minus implied cap (NOI ÷ price), median "
                         f"{median(z.model_cap - z.implied_cap) * 1e4:+.0f} bps")
    worst = res.reindex(res["detailed_error"].abs().sort_values(ascending=False).index).head(5) \
        if "detailed_error" in res else res.iloc[0:0]
    if len(worst):
        lines += ["", "## Largest misses (Detailed)", "", "| Property | Sector | Subtype | Price | Detailed | Error |",
                  "|---|---|---|---:|---:|---:|"]
        for _, w in worst.iterrows():
            lines.append(f"| {w.property_id} | {w.sector} | {w.subtype if isinstance(w.subtype, str) else ''} | "
                         f"${w.sale_price:,.0f} | ${w.detailed_value:,.0f} | {w.detailed_error:+.1%} |")
    lines += ["", "Notes: today's market benchmarks are applied to every sale unless market_cap_at_sale is given. "
              "Don't calibrate on rows whose rents and expenses were estimated rather than verified."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sales_csv", nargs="?", help="CSV of historical sales (see --template)")
    ap.add_argument("--out", default="validation_results.csv")
    ap.add_argument("--summary", default="validation_summary.md")
    ap.add_argument("--template", action="store_true", help="write historical_sales_template.csv and exit")
    a = ap.parse_args(argv)
    if a.template or not a.sales_csv:
        template().to_csv("historical_sales_template.csv", index=False)
        print("Wrote historical_sales_template.csv")
        return 0
    df = pd.read_csv(a.sales_csv)
    missing = [c for c in ("market", "sector", "sale_price", "size", "occupancy", "contract_rent") if c not in df]
    if missing:
        print("Missing required columns: " + ", ".join(missing))
        return 1
    res = run(df)
    res.to_csv(a.out, index=False)
    text = summarize(res)
    open(a.summary, "w").write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
