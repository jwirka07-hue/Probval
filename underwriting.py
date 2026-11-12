"""
Underwriting engine.

Three approaches, reconciled with explained weights:
  1. Direct capitalization — stabilized NOI ÷ cap rate, less the cost of reaching stabilization.
  2. Discounted cash flow (10 years + sale) —
       • Commercial: a MONTHLY, LEASE-BY-LEASE schedule. Each suite rolls at its expiration with a renewal
         probability; non-renewals sit vacant for a downtime period; renewals and new leases reset to market rent
         (growing at market rent growth), with tenant improvements, leasing commissions and free rent for each
         outcome, probability-weighted. Vacant suites lease up on an absorption schedule. Recoveries follow each
         suite's lease type (NNN, base year, gross). A general vacancy allowance tops up modeled vacancy to the
         market's stabilized level.
       • Apartments: unit-level occupancy path (leases are short and turn continuously).
  3. Sales comparison — owner-entered comparable sales, adjusted for class, when provided.

Inputs that drive value are independently supported:
  • Cap rate: average of recent local benchmarks with a confidence level (+ owner comps when given).
  • Discount rate: cap rate + investor-survey spread + property-specific risk adjustments (listed).
  • Property taxes: by state reassessment rule or owner override, with abatements and assessment ratio.
  • Expenses: grown by category (insurance, utilities, payroll, other).
The value range is SCENARIO-BASED (downside / upside assumptions), not a statistical confidence interval.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from statistics import median

import market_data as md

LEASEUP_RISK = 0.15   # buyer's allowance for lease-up risk: 15% of lost rent + leasing costs (appraisal convention, 10–20%)
N_YEARS = md.HOLD_YEARS + 1
N_MONTHS = 12 * N_YEARS
RANGE_LABEL = ("Scenario-based valuation range — built from the assumptions shown, not a statistical confidence "
               "interval or a measure of accuracy against actual sales")


class ValuationError(ValueError):
    """Inputs that can't produce a meaningful value. Messages are shown to the user as-is."""


@dataclass
class Inputs:
    sector: str                         # "multifamily" | "industrial" | "office"
    market: str
    size: float                         # units or rentable SF
    gpr: float                          # annual rent if 100% leased (in-place + market rent on vacant space)
    physical_vacancy: float
    opex: float                         # total annual operating expenses EXCLUDING property tax, management, reserves
    opex_breakdown: dict | None = None  # optional {"insurance": $, "utilities": $, "payroll": $}; remainder = other
    expense_growth: dict | None = None  # optional overrides of md.EXPENSE_GROWTH
    other_income: float = 0.0
    pclass: str | None = None           # "A" | "B" | "C" | None (not sure)
    suites: list | None = None          # commercial lease-level rows (from rentroll.review_commercial)
    leasing: dict | None = None         # overrides of md.LEASING[sector]
    rent_growth: float | None = None
    # property taxes
    current_tax: float | None = None
    tax_rate_override: float | None = None
    tax_mode: str = "default"           # "default" (state rule) | "sale" | "cycle"
    assess_pct: float | None = None     # assessor's value as a share of the sale price
    years_to_reval: int | None = None
    abatement: float = 0.0              # annual tax savings from an abatement / PILOT
    abatement_years: int = 0
    # recoveries (commercial)
    actual_recoveries: float | None = None
    nonrecoverable: float = 0.0
    # other
    concessions: float = 0.0
    collected_rent: float | None = None
    capex: float = 0.0
    leaseup_months: float | None = None
    comps: list | None = None           # [{"price", "size", "cap" (opt), "months_ago", "pclass" (opt)}]
    discount_override: float | None = None
    quality_grade: str = "A"            # from quality.py
    quick: bool = False                 # quick estimate: lease dates unknown, expirations assumed evenly staggered
    subtype: str | None = None          # industrial subtype (md.INDUSTRIAL_SUBTYPES)
    rent_basis: str = "actual"          # "actual" (contract rent) | "estimated" (owner's guess at market rent)
    cap_override: float | None = None   # going-in cap rate to use as-is (validation against past sales)


@dataclass(frozen=True)
class Scenario:
    name: str
    cap_shift: float = 0.0
    disc_shift: float = 0.0
    vac_shift: float = 0.0
    opex_mult: float = 1.0
    growth_shift: float = 0.0
    leaseup_mult: float = 1.0
    renewal_shift: float = 0.0
    downtime_mult: float = 1.0
    class_tilt: float = 0.0


BASE = Scenario("Base")
DOWNSIDE = Scenario("Downside", cap_shift=0.0025, disc_shift=0.005, vac_shift=0.015, opex_mult=1.04,
                    growth_shift=-0.005, leaseup_mult=1.5, renewal_shift=-0.10, downtime_mult=1.5, class_tilt=0.5)
UPSIDE = Scenario("Upside", cap_shift=-0.0025, disc_shift=-0.005, vac_shift=-0.01, opex_mult=0.98,
                  growth_shift=0.005, leaseup_mult=0.75, renewal_shift=0.10, downtime_mult=0.75, class_tilt=-0.5)
SCENARIO_NOTE = ("Downside: cap rate +25 bps, discount rate +50 bps, stabilized vacancy +1.5 pts, expenses +4%, rent "
                 "growth −0.5 pt, lease-up 50% slower, renewal probability −10 pts, downtime +50%. Upside: the reverse "
                 "at smaller magnitudes (cap −25 bps, discount −50 bps, vacancy −1 pt, expenses −2%, growth +0.5 pt, "
                 "lease-up 25% faster, renewals +10 pts, downtime −25%). If class is 'not sure', scenarios also lean "
                 "halfway toward Class C (downside) and Class A (upside). These are judgment-based scenarios, not "
                 "statistical bounds.")


# ======================================================================
# Validation
# ======================================================================
def validate(inp: Inputs) -> list[str]:
    errors, notes = [], []
    unit = "units" if inp.sector == "multifamily" else "square feet"
    if not inp.size or inp.size <= 0 or math.isnan(inp.size):
        errors.append(f"Property size must be more than 0 {unit}.")
    if not inp.gpr or inp.gpr <= 0:
        errors.append("Potential rent must be more than $0. Check the rent roll's rent column.")
    if not (0 <= inp.physical_vacancy < 1):
        errors.append("Vacancy must be between 0% and 99%. A fully vacant property can't be valued on its income.")
    if inp.opex is None or inp.opex < 0:
        errors.append("Operating expenses can't be negative.")
    if inp.opex_breakdown:
        if any(v < 0 for v in inp.opex_breakdown.values()):
            errors.append("Expense categories can't be negative.")
        elif sum(inp.opex_breakdown.values()) > inp.opex + 0.5:
            errors.append("Insurance, utilities and payroll add up to more than total operating expenses.")
    for label, v in (("Unreimbursed expenses", inp.nonrecoverable), ("Repair costs", inp.capex),
                     ("Other income", inp.other_income), ("Tax abatement", inp.abatement)):
        if v is not None and v < 0:
            errors.append(f"{label} can't be negative.")
    if inp.current_tax is not None and inp.current_tax < 0:
        errors.append("The property tax bill can't be negative.")
    if inp.tax_rate_override is not None and not (0 < inp.tax_rate_override < 0.10):
        errors.append("The tax rate from your bill should be between 0% and 10% of value — check both numbers.")
    if inp.assess_pct is not None and not (0.2 <= inp.assess_pct <= 1.2):
        errors.append("Assessed value as a share of price should be between 20% and 120%.")
    if inp.collected_rent is not None:
        if inp.collected_rent <= 0:
            errors.append("Rent collected of $0 means the property has no income to value. Leave the field blank "
                          "if you don't know it.")
        elif inp.gpr and inp.collected_rent > inp.gpr * 1.05:
            notes.append("Rent collected is higher than the rent roll's full potential rent, so it was ignored. "
                         "Check that both cover the same 12 months.")
            inp.collected_rent = None
    if inp.actual_recoveries is not None and inp.actual_recoveries < 0:
        errors.append("Expense reimbursements can't be negative.")
    if inp.discount_override is not None and not (0.04 <= inp.discount_override <= 0.20):
        errors.append("A discount rate override should be between 4% and 20%.")
    if inp.sector != "multifamily" and not inp.suites:
        errors.append("Commercial properties need a reviewed suite list.")
    if errors:
        raise ValuationError(" ".join(errors))
    return notes


# ======================================================================
# Market inputs: cap rate (with confidence), comps, discount rate
# ======================================================================
CLASS_RANK = {"A": 0, "B": 1, "C": 2}


def _comp_analysis(inp: Inputs) -> dict | None:
    if not inp.comps:
        return None
    subj = CLASS_RANK.get(inp.pclass or "B", 1)
    used, dropped = [], 0
    for c in inp.comps:
        if not c.get("price") or not c.get("size") or c["price"] <= 0 or c["size"] <= 0:
            continue
        if c.get("months_ago", 0) > 24:
            dropped += 1
            continue
        steps = subj - CLASS_RANK.get(c.get("pclass") or "B", 1)   # + if comp is better than subject
        per = c["price"] / c["size"] * (1 - 0.10 * steps)          # 10% per class step (rule of thumb)
        cap_b = None
        if c.get("cap"):
            cap_b = c["cap"] - md.CLASS_SPREAD[inp.sector][c.get("pclass") or "B"]   # normalize to Class B
        used.append({**c, "adj_per_unit": per, "cap_b": cap_b})
    if not used:
        return {"n": 0, "dropped": dropped}
    pers = [u["adj_per_unit"] for u in used]
    caps = [u["cap_b"] for u in used if u["cap_b"]]
    mid = median(pers)
    return {"n": len(used), "dropped": dropped, "comps": used, "per_unit": mid,
            "dispersion": (max(pers) - min(pers)) / mid if mid else 1.0,
            "cap_b": median(caps) if caps else None, "n_caps": len(caps)}


def _cap_selection(inp: Inputs, comps: dict | None) -> dict:
    b = md.cap_benchmark(inp.sector, inp.market)
    cap_b, conf, notes = b["cap"], b["confidence"], []
    if comps and comps.get("cap_b"):
        wb = {"High": 3, "Medium": 2, "Low": 1}[conf]
        wc = min(3, comps["n_caps"])
        blended = (wb * cap_b + wc * comps["cap_b"]) / (wb + wc)
        diff = abs(comps["cap_b"] - b["cap"])
        notes.append(f"Your {comps['n_caps']} comparable sale(s) indicate a {comps['cap_b']:.2%} cap rate (Class B "
                     f"basis) vs. the {b['cap']:.2%} market benchmark; blended {wb}:{wc} → {blended:.2%}.")
        if comps["n_caps"] >= 2 and diff <= 0.005:
            conf = {"Low": "Medium", "Medium": "High", "High": "High"}[conf]
            notes.append("Comps agree with the benchmark within 50 bps, raising confidence.")
        elif diff > 0.01:
            conf = "Low" if conf != "High" else "Medium"
            notes.append("Comps differ from the benchmark by more than 100 bps — check that they are truly comparable.")
        cap_b = blended
    return {"cap_b": cap_b, "confidence": conf, "benchmark": b, "notes": notes}


def _discount_build(inp: Inputs, cap_class: float, metrics: dict) -> tuple[float, list]:
    """Discount rate = class-adjusted cap + survey spread + property-specific adjustments."""
    rows = [("Going-in cap rate (class-adjusted)", cap_class, "Local benchmark, adjusted for building class"),
            ("Investor-survey spread over cap rate", md.DISCOUNT_SPREAD[inp.sector], md.DISCOUNT_SOURCE)]
    adj = []
    tier = md.MARKET_TIER.get(inp.market, "secondary")
    if tier == "secondary":
        adj.append(("Secondary market liquidity", 0.0025, "Fewer buyers and less frequent trades than core Sunbelt metros"))
    elif tier == "tertiary":
        adj.append(("Tertiary market liquidity", 0.0050, "Thin buyer pool; few institutional comparables"))
    gap = metrics["occ_gap"]
    if gap > 0.03:
        bump = min(0.01, round(gap / 0.10 * 0.0025 / 0.0005) * 0.0005)
        adj.append(("Lease-up risk", bump, f"Occupancy {gap:.0%} below stabilized; +25 bps per 10 pts (max +100)"))
    if inp.sector != "multifamily" and not inp.quick:
        r3 = metrics.get("rollover_3yr", 0)
        if r3 >= 0.5:
            adj.append(("Near-term lease expirations", 0.0050, f"{r3:.0%} of rent expires within 3 years"))
        elif r3 >= 0.3:
            adj.append(("Near-term lease expirations", 0.0025, f"{r3:.0%} of rent expires within 3 years"))
        top = metrics.get("top_share", 0)
        if top >= 0.5:
            adj.append(("Tenant concentration", 0.0050, f"Largest tenant pays {top:.0%} of rent"))
        elif top >= 0.3:
            adj.append(("Tenant concentration", 0.0025, f"Largest tenant pays {top:.0%} of rent"))
    if inp.quality_grade == "C":
        adj.append(("Data reliability", 0.0025, "Owner data has several quality flags; projections are less certain"))
    rate = cap_class + md.DISCOUNT_SPREAD[inp.sector] + sum(a[1] for a in adj)
    rows += adj
    if inp.discount_override:
        rows.append(("Owner override", inp.discount_override - rate, "Discount rate entered by the user"))
        rate = inp.discount_override
    return rate, rows


# ======================================================================
# Shared schedules: expenses and property taxes
# ======================================================================
def _expense_cats(inp: Inputs) -> tuple[dict, dict]:
    growth = {**md.EXPENSE_GROWTH, **(inp.expense_growth or {})}
    if inp.opex_breakdown:
        cats = {k: v for k, v in inp.opex_breakdown.items()}
        cats["other"] = max(0.0, inp.opex - sum(cats.values()))
    else:
        cats = {"other": inp.opex}
    return cats, growth


def _opex_year(y: int, cats: dict, growth: dict, mult: float) -> float:
    return mult * sum(v * (1 + growth.get(k, 0.03)) ** (y - 1) for k, v in cats.items())


def _tax_setup(inp: Inputs) -> dict:
    row = md.MARKETS[inp.market]
    rule = md.TAX_RULES[row["state"]]
    mode = rule["type"] if inp.tax_mode == "default" else inp.tax_mode
    rate = inp.tax_rate_override or row["tax_apartment" if inp.sector == "multifamily" else "tax_commercial"]
    assess = inp.assess_pct if inp.assess_pct is not None else rule.get("factor", 1.0)
    reval = inp.years_to_reval or md.years_to_reval(inp.market)
    return {"mode": mode, "rate": rate, "assess": assess, "reval": reval, "rule": rule, "row": row}


def _tax_year(y: int, value: float, t: dict, g: float, inp: Inputs) -> float:
    market_tax = t["rate"] * t["assess"] * value * (1 + g) ** (y - 1)
    if t["mode"] == "cycle" and inp.current_tax is not None and y < t["reval"]:
        tax = inp.current_tax
    else:
        tax = market_tax
    if inp.abatement and y <= inp.abatement_years:
        tax = max(0.0, tax - inp.abatement)
    return tax


# ======================================================================
# Commercial: monthly lease-by-lease schedule (value-independent part)
# ======================================================================
def _suite_schedules(inp: Inputs, sc: Scenario, g: float, stab_vac: float) -> dict:
    L = {**md.leasing_for(inp.sector, inp.subtype), **(inp.leasing or {})}
    p_renew = min(0.95, max(0.0, L["renewal_prob"] + sc.renewal_shift))
    down = max(0, round(L["downtime"] * sc.downtime_mult))
    term_m = int(L["term"] * 12)
    N = N_MONTHS
    total = inp.size
    occ_sf = [0.0] * N; rent = [0.0] * N; free = [0.0] * N; potential = [0.0] * N
    ti = [0.0] * N; lc = [0.0] * N
    nnn_sf = [0.0] * N
    by_sf: dict[int, list] = {}           # hold-year the base-year lease segment started → occupied SF by month
    lease_events = []

    def mkt_annual(s, m):                 # market rent for suite s at month index m (0-based)
        return s["market_psf"] * s["sf"] * (1 + g) ** (m / 12)

    def add_segment(s, start, end, annual_rent, prob, base_year_start, free_months):
        """Occupy months [start, end) with probability `prob` at annual_rent bumped yearly."""
        for m in range(max(0, start), min(N, end)):
            bumped = annual_rent * (1 + L["bump"]) ** ((m - start) // 12)
            occ_sf[m] += prob * s["sf"]
            rent[m] += prob * bumped / 12
            potential[m] += prob * bumped / 12
            if m - start < free_months:
                free[m] += prob * bumped / 12
            if s["lease_type"] == "nnn":
                nnn_sf[m] += prob * s["sf"]
            elif s["lease_type"] == "base_year":
                by_sf.setdefault(base_year_start, [0.0] * N)[m] += prob * s["sf"]

    # Absorption schedule for currently vacant suites
    vacant = [s for s in inp.suites if s["vacant"]]
    vac_sf = sum(s["sf"] for s in vacant)
    if inp.leaseup_months:
        pace = vac_sf / max(1.0, inp.leaseup_months)
    else:
        pace = md.STANDARD[inp.sector]["absorb_per_month"] * total
    pace /= sc.leaseup_mult
    cum = 0.0
    starts = {}
    for s in vacant:
        cum += s["sf"]
        starts[id(s)] = max(1, math.ceil(cum / pace)) - 1          # 0-based month the lease starts

    for s in inp.suites:
        if s["vacant"]:
            st = starts[id(s)]
            for m in range(0, min(N, st)):
                potential[m] += mkt_annual(s, m) / 12               # vacant: potential at market
            r0 = mkt_annual(s, st)
            if st < N:
                ti[st] += L["ti_new"] * s["sf"]
                lc[st] += L["lc_new"] * r0 * L["term"]
            add_segment(s, st, st + term_m, r0, 1.0, st // 12 + 1, L["free_new"])
            nxt = st + term_m
            lease_events.append({"suite": s["suite"], "tenant": "(vacant — lease-up)", "event_month": st + 1,
                                 "event": "New lease at market", "rent_psf": r0 / s["sf"]})
        else:
            end = s["months_left"]                                   # last month of the current lease (1-based)
            add_segment(s, 0, end, s["rent"], 1.0, 1, 0)
            nxt = end
            lease_events.append({"suite": s["suite"], "tenant": s["tenant"], "event_month": end + 1,
                                 "event": f"Expires — {p_renew:.0%} renewal / {down}-mo downtime if not",
                                 "rent_psf": s["rent"] / s["sf"]})
        # Roll forward
        while nxt < N:
            e = nxt                                                   # first month after expiration (0-based)
            r_new = mkt_annual(s, e)
            yr = e // 12 + 1
            # Renewal branch
            ti[e] += p_renew * L["ti_renew"] * s["sf"]
            lc[e] += p_renew * L["lc_renew"] * r_new * L["term"]
            add_segment(s, e, e + term_m, r_new, p_renew, yr, L["free_renew"])
            # Non-renewal branch: downtime, then a new tenant
            for m in range(e, min(N, e + down)):
                potential[m] += (1 - p_renew) * mkt_annual(s, m) / 12
            ne = e + down
            if ne < N:
                r_nt = mkt_annual(s, ne)
                ti[ne] += (1 - p_renew) * L["ti_new"] * s["sf"]
                lc[ne] += (1 - p_renew) * L["lc_new"] * r_nt * L["term"]
                add_segment(s, ne, ne + term_m - down, r_nt, 1 - p_renew, yr, L["free_new"])
            nxt = e + term_m

    # Aggregate to years
    years = []
    for y in range(N_YEARS):
        sl = slice(12 * y, 12 * y + 12)
        years.append({
            "rent": sum(rent[sl]), "free": sum(free[sl]), "potential": sum(potential[sl]),
            "occ": sum(occ_sf[sl]) / (12 * total), "ti": sum(ti[sl]), "lc": sum(lc[sl]),
            "nnn_share": sum(nnn_sf[sl]) / (12 * total),
            "by_share": {k: sum(v[sl]) / (12 * total) for k, v in by_sf.items()},
        })
    leaseup = {"ti_lc": sum(L["ti_new"] * s["sf"] + L["lc_new"] * mkt_annual(s, starts[id(s)]) * L["term"]
                            for s in vacant),
               "lost": sum(mkt_annual(s, 0) * starts[id(s)] / 12 + mkt_annual(s, 0) * L["free_new"] / 12 for s in vacant),
               "months": max(starts.values()) + 1 if starts else 0}
    excess = max(0.0, inp.physical_vacancy - stab_vac)
    if inp.physical_vacancy > 0:
        leaseup["lost"] *= excess / inp.physical_vacancy
    return {"years": years, "events": lease_events, "leaseup": leaseup, "L": L, "p_renew": p_renew, "down": down}


# ======================================================================
# Setup and cash flows
# ======================================================================
def _std(inp: Inputs) -> dict:
    std = dict(md.STANDARD[inp.sector])
    if inp.sector == "industrial" and inp.subtype in md.INDUSTRIAL_SUBTYPES:
        std.update(md.INDUSTRIAL_SUBTYPES[inp.subtype].get("std", {}))
    return std


def _setup(inp: Inputs, sc: Scenario, comps: dict | None, metrics: dict) -> dict:
    std = _std(inp)
    capsel = _cap_selection(inp, comps)
    spreads = md.CLASS_SPREAD[inp.sector]
    if inp.pclass:
        class_adj = spreads[inp.pclass]
    else:
        class_adj = sc.class_tilt * (spreads["C"] if sc.class_tilt > 0 else -spreads["A"]) if sc.class_tilt else 0.0
    sub = md.INDUSTRIAL_SUBTYPES.get(inp.subtype) if inp.sector == "industrial" else None
    cap_class = capsel["cap_b"] + class_adj + (sub["cap_adj"] if sub else 0.0)
    if inp.cap_override:
        cap_class = inp.cap_override
    cap = cap_class + sc.cap_shift
    exit_cap = cap + md.EXIT_SPREAD[inp.sector]
    disc, disc_rows = _discount_build(inp, cap_class, metrics)
    disc += sc.disc_shift
    stab_vac, vac_src = md.stabilized_vacancy(inp.sector, inp.market)
    stab_vac = max(0.02, stab_vac + sc.vac_shift)
    credit = max(std["credit_loss"], inp.concessions)
    if inp.collected_rent:
        actual_loss = max(0.0, 1 - inp.collected_rent / inp.gpr)
        credit = max(credit, min(0.25, actual_loss - inp.physical_vacancy))
    g = (inp.rent_growth if inp.rent_growth is not None else std["rent_growth"]) + sc.growth_shift
    cats, growth = _expense_cats(inp)
    s = dict(std=std, capsel=capsel, cap=cap, cap_class=cap_class, exit_cap=exit_cap, disc=disc, disc_rows=disc_rows,
             stab_vac=stab_vac, vac_src=vac_src, os=1 - stab_vac, o0=1 - inp.physical_vacancy, credit=credit, g=g,
             cats=cats, growth=growth, opex_mult=sc.opex_mult, tax=_tax_setup(inp), sc=sc)
    if inp.sector == "multifamily":
        o0, os_ = s["o0"], s["os"]
        if o0 < os_:
            default = math.ceil((os_ - o0) / std["absorb_per_month"])
            s["months"] = (inp.leaseup_months or default) * sc.leaseup_mult
        else:
            s["months"] = 0.0
    else:
        s["sched"] = _suite_schedules(inp, sc, g, stab_vac)
        s["months"] = s["sched"]["leaseup"]["months"]
    return s


def _mf_flows(inp: Inputs, s: dict, value: float) -> list[dict]:
    std = s["std"]
    flows, prev_end = [], min(s["o0"], s["os"])
    for y in range(1, N_YEARS + 1):
        occs = []
        for m in range(1, 13):
            t = (y - 1) * 12 + m
            occs.append(s["os"] if s["months"] <= 0 else s["o0"] + (s["os"] - s["o0"]) * min(1.0, t / s["months"]))
        occ, end = sum(occs) / 12, occs[-1]
        rent = inp.gpr * (1 + s["g"]) ** (y - 1)
        vac, credit = rent * (1 - occ), rent * occ * s["credit"]
        other = inp.other_income * (1 + s["g"]) ** (y - 1)
        revenue = rent - vac - credit + other
        opex = _opex_year(y, s["cats"], s["growth"], s["opex_mult"])
        mgmt = std["mgmt_fee"] * revenue
        reserves = std["reserves"] * inp.size * (1.03) ** (y - 1)
        tax = _tax_year(y, value, s["tax"], s["g"], inp)
        noi = revenue - opex - mgmt - reserves - tax
        newly = max(0.0, end - prev_end)
        prev_end = end
        leasing = newly * inp.size * (inp.gpr / inp.size) / 12 * std["leaseup_cost_months"]
        one_time = inp.capex if y == 1 else 0.0
        flows.append({"year": y, "occupancy": occ, "potential_rent": rent, "vacancy": -vac, "free_rent": 0.0,
                      "credit_loss": -credit, "other_income": other, "recoveries": 0.0, "egi": revenue,
                      "opex": -opex, "management": -mgmt, "reserves": -reserves, "nonrecoverable": 0.0,
                      "taxes": -tax, "noi": noi, "leasing_costs": -leasing, "one_time": -one_time,
                      "cash_flow": noi - leasing - one_time})
    return flows


def _cm_flows(inp: Inputs, s: dict, value: float) -> list[dict]:
    std, sched = s["std"], s["sched"]
    flows, pools = [], {}
    raw = []
    for y in range(1, N_YEARS + 1):
        Y = sched["years"][y - 1]
        modeled_vac = 1 - Y["occ"]
        gv = max(0.0, s["stab_vac"] - modeled_vac) * Y["potential"]
        absorption_vac = Y["potential"] - Y["rent"]
        net_rent = Y["rent"] - Y["free"] - gv
        credit = s["credit"] * net_rent
        other = inp.other_income * (1 + s["g"]) ** (y - 1)
        opex = _opex_year(y, s["cats"], s["growth"], s["opex_mult"])
        mgmt = std["mgmt_fee"] * (net_rent - credit + other)
        reserves = std["reserves"] * inp.size * (1.03) ** (y - 1)
        nonrec = inp.nonrecoverable * (1.03) ** (y - 1)
        tax = _tax_year(y, value, s["tax"], s["g"], inp)
        pool = opex + mgmt + tax
        pools[y] = pool
        rec = Y["nnn_share"] * pool + sum(sh * max(0.0, pool - pools.get(by, pool)) for by, sh in Y["by_share"].items())
        raw.append(dict(y=y, Y=Y, gv=gv, absorption_vac=absorption_vac, credit=credit, other=other, opex=opex,
                        mgmt=mgmt, reserves=reserves, nonrec=nonrec, tax=tax, pool=pool, rec=rec))
    # Calibrate recoveries to the owner's actual T-12 reimbursements, if given
    scale, share_override = 1.0, None
    if inp.actual_recoveries is not None:
        r1 = raw[0]["rec"]
        if r1 > 0:
            scale = inp.actual_recoveries / r1
        elif raw[0]["Y"]["occ"] > 0 and raw[0]["pool"] > 0:
            share_override = inp.actual_recoveries / (raw[0]["Y"]["occ"] * raw[0]["pool"])
    for d in raw:
        Y = d["Y"]
        rec = d["rec"] * scale if share_override is None else share_override * Y["occ"] * d["pool"]
        egi = Y["potential"] - d["absorption_vac"] - Y["free"] - d["gv"] - d["credit"] + d["other"] + rec
        noi = egi - d["opex"] - d["mgmt"] - d["reserves"] - d["nonrec"] - d["tax"]
        leasing = Y["ti"] + Y["lc"]
        one_time = inp.capex if d["y"] == 1 else 0.0
        flows.append({"year": d["y"], "occupancy": Y["occ"] * (1 - (d["gv"] / Y["potential"] if Y["potential"] else 0)),
                      "potential_rent": Y["potential"], "vacancy": -(d["absorption_vac"] + d["gv"]),
                      "free_rent": -Y["free"], "credit_loss": -d["credit"], "other_income": d["other"],
                      "recoveries": rec, "egi": egi, "opex": -d["opex"], "management": -d["mgmt"],
                      "reserves": -d["reserves"], "nonrecoverable": -d["nonrec"], "taxes": -d["tax"], "noi": noi,
                      "leasing_costs": -leasing, "one_time": -one_time, "cash_flow": noi - leasing - one_time})
    return flows


def _flows(inp, s, value):
    return _mf_flows(inp, s, value) if inp.sector == "multifamily" else _cm_flows(inp, s, value)


def _pv(flows: list[dict], disc: float, exit_cap: float) -> tuple[float, float, float]:
    pv_cf = sum(f["cash_flow"] / (1 + disc) ** f["year"] for f in flows[:md.HOLD_YEARS])
    reversion = flows[md.HOLD_YEARS]["noi"] / exit_cap * (1 - md.SELLING_COSTS)
    return pv_cf + reversion / (1 + disc) ** md.HOLD_YEARS, pv_cf, reversion


def _leaseup_costs(inp: Inputs, s: dict) -> tuple[float, float]:
    """(leasing costs, lost rent) to reach stabilization."""
    if inp.sector == "multifamily":
        flows = _mf_flows(inp, s, 1.0)   # value-independent lines only
        leasing = sum(-f["leasing_costs"] for f in flows[:md.HOLD_YEARS])
        lost = sum(max(0.0, s["os"] - f["occupancy"]) * f["potential_rent"] for f in flows[:md.HOLD_YEARS])
        return leasing, lost
    lu = s["sched"]["leaseup"]
    return lu["ti_lc"], lu["lost"]


def _stabilized_noi(inp: Inputs, s: dict, value: float, current: bool) -> dict:
    """One-year NOI in today's dollars: current occupancy (current=True) or stabilized occupancy."""
    std = s["std"]
    if inp.sector == "multifamily":
        potential = inp.gpr
        nnn_share = 0.0
    else:
        potential = sum(x["rent"] if not x["vacant"] else x["market_psf"] * x["sf"] for x in inp.suites)
        leased_nnn = sum(x["sf"] for x in inp.suites if x["lease_type"] == "nnn")
        nnn_share = leased_nnn / inp.size
    occ = s["o0"] if current else s["os"]
    vac = potential * (1 - occ)
    credit = potential * occ * s["credit"]
    other = inp.other_income
    opex = _opex_year(1, s["cats"], s["growth"], 1.0)
    mgmt = std["mgmt_fee"] * (potential - vac - credit + other)
    reserves = std["reserves"] * inp.size
    t = s["tax"]
    if current and inp.current_tax is not None:
        tax = inp.current_tax
    else:
        tax = _tax_year(1, value, t, s["g"], inp)
    if inp.sector == "multifamily":
        rec = 0.0
    elif inp.actual_recoveries is not None and current:
        rec = inp.actual_recoveries
    else:
        pool = opex + mgmt + tax
        if current:
            rec = nnn_share * pool                                   # leased NNN space pays its pro-rata share
        else:
            all_nnn = sum(x["sf"] for x in inp.suites if x["lease_type"] == "nnn") / inp.size
            rec = occ * all_nnn * pool                               # stabilized: NNN share at stabilized occupancy
        rec = min(rec, pool)
    noi = potential - vac - credit + other + rec - opex - mgmt - reserves - inp.nonrecoverable - tax
    return {"occupancy": occ, "potential_rent": potential, "vacancy": -vac, "credit_loss": -credit,
            "other_income": other, "recoveries": rec, "egi": potential - vac - credit + other + rec,
            "opex": -opex, "management": -mgmt, "reserves": -reserves, "nonrecoverable": -inp.nonrecoverable,
            "taxes": -tax, "noi": noi}


def _values(inp: Inputs, sc: Scenario, comps, metrics) -> dict:
    """Direct cap and DCF under one scenario (taxes solved by iteration on value)."""
    s = _setup(inp, sc, comps, metrics)
    leasing, lost = _leaseup_costs(inp, s)
    allowance = LEASEUP_RISK * (leasing + lost)
    v = max(1.0, inp.gpr * 0.5 / s["cap"])
    for _ in range(60):
        flows = _flows(inp, s, v)
        dcf, pv_cf, rev = _pv(flows, s["disc"], s["exit_cap"])
        dcf -= allowance
        stab = _stabilized_noi(inp, s, v, current=False)
        dc = stab["noi"] / s["cap"] - leasing - lost - inp.capex - allowance
        new_v = (dcf + dc) / 2
        if abs(new_v - v) < 1:
            break
        v = new_v if new_v > 0 else max(1.0, v / 2)
    return {"s": s, "flows": flows, "dcf": dcf, "pv_cf": pv_cf, "reversion": rev, "dc": dc, "stab": stab,
            "leasing": leasing, "lost": lost, "allowance": allowance, "value_for_tax": v}


# ======================================================================
# Reconciliation
# ======================================================================
def _weights(inp: Inputs, metrics: dict, comps: dict | None, sales_value: float | None) -> tuple[dict, list]:
    w, why = {"dc": 50.0, "dcf": 50.0}, []
    def shift(to, amt, reason):
        frm = "dc" if to == "dcf" else "dcf"
        w[to] += amt; w[frm] -= amt
        why.append(f"{'+' if amt > 0 else ''}{amt:.0f} pts to {'DCF' if to == 'dcf' else 'direct cap'}: {reason}")
    gap = metrics["occ_gap"]
    if inp.sector == "multifamily":
        shift("dc", 10, "apartments trade on in-place NOI and cap rates; short leases make income predictable.")
    if gap <= 0.03 and (inp.quick or metrics.get("rollover_3yr", 0) < 0.30):
        shift("dc", 10, "the property is at or near stabilized occupancy with limited near-term rollover.")
    if gap > 0.10:
        shift("dcf", 25, f"occupancy is {gap:.0%} below stabilized — only a cash flow model captures lease-up timing.")
    elif gap > 0.03:
        shift("dcf", 10, f"occupancy is {gap:.0%} below stabilized.")
    if inp.sector != "multifamily" and not inp.quick:
        if metrics.get("rollover_3yr", 0) >= 0.30:
            shift("dcf", 15, f"{metrics['rollover_3yr']:.0%} of rent expires within 3 years; the lease-by-lease DCF "
                             "models those expirations, direct cap doesn't.")
        if metrics.get("n_tenants", 0) >= 3 and metrics.get("walt", 9) < 3:
            shift("dcf", 5, "multi-tenant rent roll with a short average remaining lease term.")
    if inp.quality_grade == "C":
        shift("dc", 10, "several data-quality flags make 10-year projections less reliable.")
    w["dc"], w["dcf"] = max(15.0, min(85.0, w["dc"])), max(15.0, min(85.0, w["dcf"]))
    tot = w["dc"] + w["dcf"]
    w = {k: v / tot * 100 for k, v in w.items()}
    w["sales"] = 0.0
    if sales_value and comps and comps.get("n", 0) >= 1:
        n, disp = comps["n"], comps["dispersion"]
        sw = 30.0 if n >= 3 and disp <= 0.15 else 20.0 if n >= 3 else 10.0
        w = {k: v * (100 - sw) / 100 for k, v in w.items()}
        w["sales"] = sw
        why.append(f"{sw:.0f}% to sales comparison: {n} comparable sale(s), adjusted prices "
                   f"{'agree within' if disp <= 0.15 else 'spread'} {disp:.0%}.")
    if not why:
        why.append("Equal weight: no factor favors one method over the other.")
    return w, why


# ======================================================================
# Public entry point
# ======================================================================
def underwrite(inp: Inputs, sensitivity: bool = True) -> dict:
    inp = replace(inp, suites=[dict(x) for x in inp.suites] if inp.suites else None)
    notes = validate(inp)
    comps = _comp_analysis(inp)
    metrics = {"occ_gap": max(0.0, (1 - md.stabilized_vacancy(inp.sector, inp.market)[0]) - (1 - inp.physical_vacancy))}
    if inp.suites:
        occ_rent = sum(x["rent"] for x in inp.suites) or 1.0
        metrics.update({
            "rollover_3yr": sum(x["rent"] for x in inp.suites if x["months_left"] and x["months_left"] <= 36) / occ_rent,
            "top_share": max(x["rent"] for x in inp.suites) / occ_rent,
            "n_tenants": sum(1 for x in inp.suites if not x["vacant"]),
            "walt": sum(x["rent"] * x["months_left"] for x in inp.suites if x["months_left"]) / occ_rent / 12,
        })

    base = _values(inp, BASE, comps, metrics)
    s = base["s"]
    if base["stab"]["noi"] <= 0:
        raise ValuationError(
            f"At stabilized occupancy the property's expenses exceed its income (NOI of ${base['stab']['noi']:,.0f}), "
            "so it can't be valued on income. Check the expense and rent figures — if they're right, the property is "
            "worth roughly its land or redevelopment value, which this tool doesn't estimate.")

    sales_value = None
    if comps and comps.get("n", 0) >= 1:
        sales_value = comps["per_unit"] * inp.size - base["leasing"] - base["lost"] - inp.capex - base["allowance"]
    weights, why = _weights(inp, metrics, comps, sales_value)

    def reconcile(vals, sv):
        return (weights["dc"] * vals["dc"] + weights["dcf"] * vals["dcf"] + weights["sales"] * (sv or 0)) / 100

    value = reconcile(base, sales_value)
    if value <= 0:
        raise ValuationError("Lease-up, rollover and repair costs exceed the property's income value. Check the "
                             "vacancy, lease and repair figures.")
    down = _values(inp, DOWNSIDE, comps, metrics)
    up = _values(inp, UPSIDE, comps, metrics)
    sv_down = sales_value * down["dcf"] / base["dcf"] if sales_value else None
    sv_up = sales_value * up["dcf"] / base["dcf"] if sales_value else None
    v_down, v_up = reconcile(down, sv_down), reconcile(up, sv_up)
    low, high = min(v_down, value, v_up), max(v_down, value, v_up)
    warnings = []
    if low <= 0:
        warnings.append("In the downside scenario the value falls to zero or below — the low end is highly uncertain.")
        low = 0.0

    # Sensitivity 1: discount rate × exit cap (DCF only, base cash flows)
    d0, x0 = s["disc"], s["exit_cap"]
    d_steps, x_steps = [-0.01, -0.005, 0, 0.005, 0.01], [-0.005, -0.0025, 0, 0.0025, 0.005]
    if not sensitivity:
        d_steps, x_steps = [0], [0]
    grid_dx = [{"disc": d0 + dd, "values": [_pv(base["flows"], d0 + dd, x0 + dx)[0] - base["allowance"]
                                            for dx in x_steps]} for dd in d_steps]
    # Sensitivity 2: going-in cap × rent growth (full reconciled re-runs)
    g0 = s["g"]
    growths = [g0 - 0.01, g0, g0 + 0.01]
    grid_cg = []
    for cs in ([-0.005, -0.0025, 0.0, 0.0025, 0.005] if sensitivity else []):
        row = []
        for gr in growths:
            alt = replace(inp, rent_growth=gr)
            r = _values(alt, Scenario("sens", cap_shift=cs), comps, metrics)
            row.append(reconcile(r, sales_value * r["dcf"] / base["dcf"] if sales_value else None))
        grid_cg.append({"cap": s["cap"] + cs, "values": row})

    current = _stabilized_noi(inp, s, base["value_for_tax"], current=True)
    t = s["tax"]
    if t["mode"] == "cycle":
        if inp.current_tax is not None:
            tax_text = (f"{t['rule']['text']} Your current bill (${inp.current_tax:,.0f}) is used through year "
                        f"{t['reval'] - 1}, then taxes step to {t['rate'] * t['assess']:.2%} of value.")
        else:
            tax_text = (f"{t['rule']['text']} Without your current bill, taxes are estimated at "
                        f"{t['rate'] * t['assess']:.2%} of value from year 1.")
            warnings.append("Add your current property tax bill — here the buyer keeps it until the next county "
                            "revaluation, which can change the value noticeably.")
    else:
        tax_text = f"{t['rule']['text']} Taxes modeled at {t['rate']:.2%} × {t['assess']:.0%} assessment of the price."
    if inp.tax_mode != "default":
        tax_text = f"Owner override: {'reassessed to the sale price' if t['mode'] == 'sale' else 'current bill until revaluation in year ' + str(t['reval'])}. " + tax_text
    if inp.abatement:
        tax_text += f" Abatement of ${inp.abatement:,.0f}/yr applied for {inp.abatement_years} year(s)."

    capsel = s["capsel"]
    if capsel["confidence"] == "Low":
        warnings.append("Cap rate confidence is low for this market and property type — adding 2–3 recent comparable "
                        "sales would make the estimate more dependable.")
    if s["months"] > 0 and s["o0"] >= s["os"]:
        notes.append(f"{inp.physical_vacancy:.0%} of the space is vacant; it's modeled leasing up over about "
                     f"{s['months']:.0f} months at market rent (${base['leasing']:,.0f} in improvements and commissions). "
                     f"A general vacancy allowance of {s['stab_vac']:.0%} still applies, matching the market's long-run level.")
    elif s["months"] > 0:
        notes.append(f"Occupancy is {s['o0']:.0%} today vs. {s['os']:.0%} stabilized: vacant space leases up over about "
                     f"{s['months']:.0f} months (${base['leasing']:,.0f} in leasing costs, ${base['lost']:,.0f} of lost "
                     f"rent, plus a ${base['allowance']:,.0f} lease-up risk allowance).")
    if inp.capex:
        notes.append(f"${inp.capex:,.0f} of near-term repairs paid in year 1.")
    if inp.collected_rent:
        notes.append(f"Collection loss set to {s['credit']:.1%} after comparing rent collected with the rent roll.")
    if inp.concessions > s["std"]["credit_loss"]:
        notes.append(f"Concessions of {inp.concessions:.1%} used in place of the standard collection loss.")
    if not inp.pclass:
        notes.append("Building class not specified: priced as Class B, with the range widened toward A and C.")
    if comps and comps.get("dropped"):
        notes.append(f"{comps['dropped']} comparable sale(s) older than 24 months were excluded.")
    notes += capsel["notes"]
    if inp.sector == "industrial" and inp.subtype in md.INDUSTRIAL_SUBTYPES:
        st_ = md.INDUSTRIAL_SUBTYPES[inp.subtype]
        cap_txt = ("cap rate at the market average" if not st_["cap_adj"]
                   else f"cap rate {st_['cap_adj'] * 1e4:+.0f} bps vs. the market average")
        notes.append(f"Valued as {inp.subtype.lower()}: {cap_txt}, "
                     f"{st_['leasing']['downtime']} months downtime and ${st_['leasing']['ti_new']:.0f}/SF improvements "
                     f"for a new tenant. {st_['evidence']}")
    if inp.cap_override:
        notes.append(f"Going-in cap rate set directly to {inp.cap_override:.2%} (override).")
    if inp.rent_basis == "estimated":
        warnings.append("Rent was entered as an estimate of market rent, not what tenants are contracted to pay. The "
                        "estimate describes hypothetical income — enter actual lease rent for a more reliable value.")
    if inp.quick and inp.sector != "multifamily":
        notes.append("Lease end dates weren't provided, so leased space is assumed to expire evenly over a typical "
                     f"{md.leasing_for(inp.sector, inp.subtype)['term']:.0f}-year term, re-leasing at the rent you entered.")

    sources = {
        "Cap rate benchmark": f"{capsel['benchmark']['label']}. Confidence: {capsel['confidence']} — {capsel['benchmark']['why']}",
        "Class adjustment": md.CLASS_SOURCE,
        "Discount rate": md.DISCOUNT_SOURCE + "; property-specific adjustments listed in the build-up.",
        "Exit cap": f"Going-in + {md.EXIT_SPREAD[inp.sector] * 100:.0f} bps ({md.DISCOUNT_SOURCE.split(';')[0]})",
        "Stabilized vacancy": s["vac_src"],
        "Property tax rate": "Owner-provided" if inp.tax_rate_override else t["row"]["tax_source"],
        "Property tax after a sale": tax_text,
        "Expense growth": md.EXPENSE_GROWTH_NOTE + ("" if inp.opex_breakdown else
                                                    " — no breakdown given, so all expenses grow at 3%."),
        "Standard underwriting": s["std"]["note"],
        "Value range": SCENARIO_NOTE,
        "Reconciliation": "Weights reflect stabilization, lease complexity, data reliability and comparable sales: "
                          + " ".join(why),
    }
    if inp.sector != "multifamily":
        sources["Lease rollover"] = md.LEASING_NOTE

    return {
        "value": value, "low": low, "high": high, "range_label": RANGE_LABEL, "per_unit": value / inp.size,
        "cap_rate": s["cap"], "cap_confidence": capsel["confidence"], "cap_evidence": capsel["benchmark"],
        "exit_cap": s["exit_cap"], "discount": s["disc"], "discount_rows": s["disc_rows"],
        "stab_vac": s["stab_vac"], "credit": s["credit"], "rent_growth": s["g"], "leaseup_months": s["months"],
        "pclass": inp.pclass or "B (not sure)", "flows": base["flows"][:md.HOLD_YEARS],
        "year11_noi": base["flows"][md.HOLD_YEARS]["noi"],
        "reversion": base["reversion"], "pv_cf": base["pv_cf"], "dcf_value": base["dcf"], "direct_cap": base["dc"],
        "sales_value": sales_value, "comps": comps, "weights": weights, "weight_reasons": why,
        "current_noi": current, "stabilized_noi": base["stab"],
        "leaseup_cost": base["leasing"], "lost_rent": base["lost"], "allowance": base["allowance"],
        "one_time": inp.capex, "lease_events": s["sched"]["events"] if inp.sector != "multifamily" else [],
        "leasing_assumptions": s["sched"]["L"] if inp.sector != "multifamily" else None,
        "sens_disc_exit": {"exits": [x0 + dx for dx in x_steps], "rows": grid_dx},
        "sensitivity": {"growths": growths, "rows": grid_cg},
        "scenarios": {"Downside": v_down, "Base": value, "Upside": v_up},
        "notes": notes, "warnings": warnings, "sources": sources, "tax_text": tax_text,
        "sector": inp.sector, "market": inp.market, "size": inp.size, "metrics": metrics,
    }
