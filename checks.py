"""
Post-valuation checks. Neither one changes the value.

reasonableness(): compares the estimate (per SF or per unit) with published average sale prices for the market and
property type, adjusted for industrial subtype and building class. Outside the band, it flags the gap and lists the
likely reasons drawn from this property's own inputs. It never pulls the value into the band: a fully leased, newer
building can legitimately be worth more than the market average, and a vacant, dated one less.

reliability(): a plain-language rating of how much the estimate rests on the owner's actual facts versus assumptions.
"""
from __future__ import annotations

import market_data as md


def reasonableness(r: dict, inp, used_defaults: dict | None = None) -> dict:
    used_defaults = used_defaults or {}
    b = md.price_benchmark(inp.sector, inp.market, inp.subtype, inp.pclass)
    per = r["per_unit"]
    if b is None:
        return {"status": "none", "per": per,
                "message": "No published average sale price is available for this market and property type, so the "
                           "estimate can't be checked against market pricing. Comparable sales would provide that check."}
    ratio = per / b["mid"]
    status = "within" if b["low"] <= per <= b["high"] else ("above" if per > b["high"] else "below")
    reasons = []
    vac = inp.physical_vacancy
    if status == "above":
        if inp.rent_basis == "estimated":
            reasons.append("Rent was estimated rather than taken from actual leases — check what tenants really pay.")
        if used_defaults.get("opex"):
            reasons.append("Operating expenses used a rule of thumb; if your real costs are higher, value falls.")
        if used_defaults.get("tax"):
            reasons.append("Property taxes used the local average; check your actual bill.")
        if inp.suites and inp.suites[0].get("lease_type") == "nnn":
            reasons.append("NNN leases were assumed — confirm tenants really reimburse taxes, insurance and "
                           "operating costs.")
        if vac < 0.05:
            reasons.append("The property is nearly full; fully leased buildings often sell above the market average.")
        if inp.pclass == "A":
            reasons.append("Class A buildings typically sell above the market average.")
        reasons.append("Rent above market, long remaining leases or strong tenants can justify a premium — but verify "
                       "the contract rent and lease terms.")
    elif status == "below":
        if vac >= 0.15:
            reasons.append(f"{vac:.0%} vacancy: lease-up time and costs reduce value.")
        if inp.suites and inp.suites[0].get("lease_type") == "gross":
            reasons.append("Gross leases mean you pay the expenses — confirm the lease type is right.")
        if inp.capex:
            reasons.append("Near-term repairs were deducted dollar for dollar.")
        if inp.pclass == "C":
            reasons.append("Older or dated buildings typically sell below the market average.")
        if inp.rent_basis == "estimated":
            reasons.append("Rent was estimated — if actual lease rents are higher, value rises.")
        reasons.append("Rent below market, short remaining leases or high expenses lower value — verify each.")
    reasons.append("The selected benchmark is an average of all sales of this type across the metro; your building's "
                   "size, age, location and tenants may differ from that mix.")
    return {"status": status, "per": per, "ratio": ratio, "bench": b, "reasons": reasons}


def reliability(inp, cap_confidence: str, recon: dict, facts: dict) -> dict:
    """facts: rent_actual, opex_given, tax_given, leases_known (None for apartments/homes)."""
    pts, items = 0, []

    def add(ok, good, bad, weight=1):
        nonlocal pts
        pts += weight if ok else 0
        items.append(("✓" if ok else "✗", good if ok else bad))

    add(facts.get("rent_actual"), "Rent comes from actual leases", "Rent is an estimate, not contract rent", 2)
    add(facts.get("opex_given"), "Operating expenses are yours", "Operating expenses are a rule of thumb")
    add(facts.get("tax_given"), "Property taxes are from your bill", "Property taxes are a local average")
    if facts.get("leases_known") is not None:
        add(facts["leases_known"], "Lease expirations are known (approximately)", "Lease expirations are unknown")
    add(cap_confidence != "Low", f"Cap rate evidence: {cap_confidence}", "Cap rate evidence: Low",
        2 if cap_confidence == "High" else 1)
    add(recon["status"] == "within", "Value is consistent with published market pricing",
        "Value falls outside published market pricing" if recon["status"] != "none"
        else "No market pricing benchmark to compare against")
    max_pts = 2 + 1 + 1 + (1 if facts.get("leases_known") is not None else 0) + 2 + 1
    share = pts / max_pts
    label = "Higher" if share >= 0.75 else "Moderate" if share >= 0.45 else "Lower"
    return {"label": label, "items": items,
            "text": {"Higher": "Built mostly on your property's actual facts.",
                     "Moderate": "A mix of your facts and market assumptions.",
                     "Lower": "Rests heavily on assumptions — treat it as a rough starting point."}[label]}
