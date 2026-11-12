"""
Input-quality checks. Each check returns (severity, message): "critical" blocks valuation until acknowledged,
"warn" lowers the data grade, "info" is shown for context. Ranges are broad Southeast norms for 2025–26; values
outside them aren't necessarily wrong, but they're the most common source of materially wrong estimates.
"""
from __future__ import annotations

import market_data as md

# (low, high) — rent per unit per month (MF) or per SF per year (commercial); opex excl. taxes/mgmt/reserves
RENT_RANGE = {"multifamily": (700, 3500), "industrial": (4.0, 20.0), "office": (15.0, 60.0)}
OPEX_RANGE = {"multifamily": (2500, 9000), "industrial": (0.5, 4.0), "office": (4.0, 14.0)}
OPEX_LABEL = {"multifamily": "per unit per year", "industrial": "per SF per year", "office": "per SF per year"}


def check(sector: str, market: str, size: float, gpr: float, physical_vacancy: float, opex: float,
          current_tax: float | None = None, tax_rate: float | None = None, review: dict | None = None,
          rent_flags: list | None = None, collected: float | None = None, other_income: float = 0.0) -> dict:
    out = []
    if review:
        out += review.get("flags", [])
    if rent_flags:
        out += rent_flags
    if size and gpr:
        per = gpr / size / (12 if sector == "multifamily" else 1)
        lo, hi = RENT_RANGE[sector]
        unit = "/unit/month" if sector == "multifamily" else "/SF/year"
        if per < lo or per > hi:
            out.append(("warn", f"Average rent of ${per:,.2f}{unit} is outside the usual ${lo:,.0f}–${hi:,.0f} range "
                                f"for Southeast {sector} — check the rent column (monthly vs. annual?)."))
        o = opex / size
        lo, hi = OPEX_RANGE[sector]
        if o < lo or o > hi:
            out.append(("warn", f"Operating expenses of ${o:,.2f} {OPEX_LABEL[sector]} are outside the usual "
                                f"${lo:,.2f}–${hi:,.2f}. Exclude property taxes, management and reserves (modeled "
                                f"separately); include insurance, utilities, repairs, payroll, admin."))
        ratio = opex / gpr
        if sector == "multifamily" and ratio > 0.55:
            out.append(("warn", f"Expenses (before taxes) are {ratio:.0%} of potential rent — unusually high."))
        if other_income > 0.25 * gpr:
            out.append(("warn", "Other income is more than 25% of rent — buyers usually discount income that isn't rent."))
    if physical_vacancy >= 0.5:
        out.append(("critical", f"The property is {physical_vacancy:.0%} vacant. Income-based values for properties "
                                "this empty depend heavily on lease-up assumptions — treat the result as a rough guide."))
    elif physical_vacancy >= 0.25:
        out.append(("warn", f"{physical_vacancy:.0%} vacancy: the value depends materially on lease-up timing."))
    if collected is not None and gpr and collected < gpr * (1 - physical_vacancy) * 0.85:
        out.append(("warn", "Rent collected is more than 15% below the occupied rent on the roll — a sign of "
                            "delinquency or concessions. The model uses the higher loss."))
    if current_tax is not None and gpr:
        if current_tax > 0.30 * gpr:
            out.append(("warn", "The tax bill is more than 30% of potential rent — check it's an annual figure."))
        elif current_tax == 0:
            out.append(("warn", "A $0 tax bill usually means an exemption or abatement — enter it under abatements."))
    if tax_rate is not None:
        row = md.MARKETS[market]
        ref = row["tax_apartment" if sector == "multifamily" else "tax_commercial"]
        if tax_rate > 2.5 * ref or tax_rate < 0.4 * ref:
            out.append(("warn", f"Your tax rate ({tax_rate:.2%} of value) is far from the local average ({ref:.2%}). "
                                "Use the bill divided by the assessor's appraised (market) value."))

    crit = [m for s, m in out if s == "critical"]
    warns = [m for s, m in out if s == "warn"]
    grade = "C" if crit or len(warns) >= 3 else "B" if warns else "A"
    return {"items": out, "critical": crit, "warnings": warns, "grade": grade,
            "grade_text": {"A": "Inputs are internally consistent and in normal ranges.",
                           "B": "A few inputs to double-check.",
                           "C": "Several inputs look unusual — review them before relying on the estimate."}[grade],
            "scope": INPUT_QUALITY_NOTE}


INPUT_QUALITY_NOTE = ("Input quality checks whether your numbers are plausible and consistent with each other. It does "
                      "not measure how close the estimate is to what the property would actually sell for.")
