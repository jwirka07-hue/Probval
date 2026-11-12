"""
PropertyValue — Southeast property value estimator (Streamlit)

Two paths, each in three steps (property details -> financial information -> estimate):
  • Quick Estimate        a few numbers, market assumptions fill the gaps, clearly disclosed
  • Detailed Underwriting rent roll review, expenses, taxes, leases -> lease-by-lease model
Run locally:  streamlit run app.py
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import checks
import export
import home
import market_data as md
import quality
import rentroll
import styles
from underwriting import Inputs, ValuationError, underwrite

st.set_page_config(page_title="PropertyValue — Southeast property value estimator", page_icon="🏢",
                   layout="centered")
styles.apply()
ss = st.session_state

MARKET_LIST = list(md.MARKETS.keys())
STATE_NAMES = {"GA": "Georgia", "NC": "North Carolina", "SC": "South Carolina", "TN": "Tennessee", "FL": "Florida",
               "AL": "Alabama"}
TYPES = {  # key: (label, material icon, svg icon)
    "multifamily": ("Apartments", ":material/apartment:", "building"),
    "industrial": ("Industrial", ":material/warehouse:", "warehouse"),
    "office": ("Office", ":material/domain:", "building"),
    "home": ("Single-family", ":material/home:", "home"),
}
CLASS_OPTIONS = {"Not sure — use Class B as a starting assumption": None,
                 "Class A — newer, top-tier finishes and location": "A",
                 "Class B — older, well maintained": "B",
                 "Class C — dated or functionally obsolete": "C"}
LEASE_OPTIONS = {"Triple net (NNN)": "nnn", "Modified gross": "base_year", "Full-service gross": "gross"}
LEASE_NAMES = {"nnn": ("Triple net", "NNN"), "base_year": ("Modified gross", "Base year"),
               "gross": ("Full-service gross", "Gross")}
LEASE_HELP = ("NNN: tenants pay their share of taxes, insurance and operating costs. Modified gross: tenants pay "
              "only increases over their first lease year. Full-service gross: you pay all expenses.")
SEVERITY = {"critical": st.error, "warn": st.warning, "info": st.info}
DISCLAIMER = ("Automated estimate for informational purposes only — not an appraisal or broker opinion of value, "
              "and not for lending, tax or legal decisions.")


# ======================================================================
# State helpers
# ======================================================================
# Streamlit forgets a widget's value when the widget isn't drawn (e.g. on another step). Re-assigning every
# "p_" key each run keeps answers alive across steps. Buttons, uploaders and tables never use the "p_" prefix.
for _k in list(ss.keys()):
    if isinstance(_k, str) and _k.startswith("p_"):
        ss[_k] = ss[_k]


def w(fn, *args, key: str, **kw):
    """Draw a widget whose value lives in session state (default used only the first time)."""
    if key in ss:
        kw.pop("value", None)
        kw.pop("index", None)
    return fn(*args, key=key, **kw)


def money(x) -> str:
    if x is None:
        return "—"
    if abs(x) < 0.5:
        return "$0"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def bps(x: float) -> str:
    return f"{x * 1e4:+.0f} bps"


def place(market: str) -> tuple[str, str]:
    city, st_ = market.rsplit(", ", 1)
    return city, f"{city}, {STATE_NAMES.get(st_, st_)}"


def go(step_key: str, n: int):
    commit_tables()
    ss[step_key] = n


def restart():
    for k in list(ss.keys()):
        del ss[k]


def choose_mode(mode: str):
    ss["mode"] = mode
    ss.setdefault("q_step", 1)
    ss.setdefault("d_step", 1)


def _quick_rent_psf(t):
    size = ss.get(f"p_q_size_{t}") or 0
    return _income(t, size)["market"] or None if size else None


def quick_to_detailed():
    """Carry the quick answers into detailed underwriting."""
    t = ss.get("p_q_type")
    ss["p_d_type"] = t
    ss["p_d_market"] = ss.get("p_q_market", MARKET_LIST[0])
    if ss.get("p_q_class"):
        ss["p_d_class"] = ss["p_q_class"]
    if t in ("industrial", "office"):
        ss[f"p_d_bsf_{t}"] = ss.get(f"p_q_size_{t}")
        ss[f"p_d_mpsf_{t}"] = _quick_rent_psf(t)
    if t == "industrial" and ss.get("p_q_subtype"):
        ss["p_d_subtype"] = ss["p_q_subtype"]
    if t == "home":
        ss["p_d_h_sf"] = ss.get("p_q_size_home")
    k = {"multifamily": "p_d_mf", "industrial": "p_d_ind", "office": "p_d_off"}.get(t)
    if k:
        for src, dst in (("p_q_opex", f"{k}_opex"), ("p_q_bill", f"{k}_bill")):
            if ss.get(src) is not None:
                ss[dst] = ss[src]
    ss["mode"] = "detailed"
    ready = t == "multifamily" or (t in ("industrial", "office") and ss.get(f"p_d_bsf_{t}") and ss.get(f"p_d_mpsf_{t}")
                                   and (t != "industrial" or ss.get("p_d_subtype")))
    ss["d_step"] = 2 if ready else 1


# ---------- tables that survive moving between steps ----------
def persistent_editor(name: str, base: pd.DataFrame, src: str, **kw) -> pd.DataFrame:
    bk, vk, sk = f"_base_{name}", f"_ver_{name}", f"_src_{name}"
    if ss.get(sk) != src or bk not in ss:
        ss[bk], ss[sk] = base, src
        ss[vk] = ss.get(vk, 0) + 1
    ed = st.data_editor(ss[bk], key=f"ed_{name}_{ss[vk]}", **kw)
    ss[f"_cur_{name}"] = ed
    ss.setdefault("_tables", set()).add(name)
    return ed


def commit_tables():
    for name in ss.get("_tables", set()):
        if f"_cur_{name}" in ss:
            ss[f"_base_{name}"] = ss[f"_cur_{name}"]
            ss[f"_ver_{name}"] = ss.get(f"_ver_{name}", 0) + 1


def upload_table(name: str, label: str, parser, help: str):
    up = st.file_uploader(label, type=["csv", "xlsx", "xls"], key=f"up_{name}", help=help)
    if up is not None and ss.get(f"_file_{name}") != (up.name, up.size):
        try:
            ss[f"_parsed_{name}"] = parser(rentroll.read_file(up))
            ss[f"_file_{name}"] = (up.name, up.size)
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
    if ss.get(f"_parsed_{name}") is not None and up is None:
        c1, c2 = st.columns([3, 1])
        c1.caption(f"Using {ss[f'_file_{name}'][0]}")
        if c2.button("Remove file", key=f"rm_{name}"):
            for k in (f"_parsed_{name}", f"_file_{name}"):
                ss.pop(k, None)
            st.rerun()
    return ss.get(f"_parsed_{name}"), (ss.get(f"_file_{name}") or ("manual",))[0]


def type_cards(prefix: str):
    items = list(TYPES.items())
    for row in (items[:2], items[2:]):
        cols = st.columns(2)
        for col, (t, (label, icon, _)) in zip(cols, row):
            _type_button(col, prefix, t, label, icon)


def _type_button(col, prefix, t, label, icon):
    key = f"type_{prefix}_{t}"
    col.button(label, icon=icon, key=key, use_container_width=True,
               on_click=lambda: ss.__setitem__(f"p_{prefix}_type", t))
    if ss.get(f"p_{prefix}_type") == t:
        styles.selected_card(key)


def nav(back_step_key: str | None, back_to: int | None, label: str, ready: bool, key: str, on_click=None, args=()):
    if back_step_key:
        c1, c2 = st.columns([1, 3])
        c1.button("Back", key=f"back_{key}", use_container_width=True, on_click=go, args=(back_step_key, back_to))
        return c2.button(label, type="primary", disabled=not ready, use_container_width=True, key=key,
                         on_click=on_click, args=args)
    return st.button(label, type="primary", disabled=not ready, use_container_width=True, key=key,
                     on_click=on_click, args=args)


# ======================================================================
# Landing
# ======================================================================
def landing():
    styles.brand("Southeast property value estimator")
    styles.title("What is your property worth?",
                 "Apartments, industrial, office and single-family homes across 13 Southeast markets. "
                 "Pick how much detail you have.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="modecard"><h3>Quick Estimate</h3><span class="time">About 2 minutes</span><ul>'
                    "<li>Property type, market and size</li><li>Rent and occupancy</li>"
                    "<li>Market assumptions fill the rest — all disclosed</li></ul></div>", unsafe_allow_html=True)
        st.button("Start a quick estimate →", type="primary", use_container_width=True, key="start_q",
                  on_click=choose_mode, args=("quick",))
    with c2:
        st.markdown('<div class="modecard"><h3>Detailed Underwriting</h3><span class="time">15–20 minutes</span><ul>'
                    "<li>Rent roll upload and review</li><li>Expenses, taxes, leasing terms, comps</li>"
                    "<li>Lease-by-lease cash flow and Excel model</li></ul></div>", unsafe_allow_html=True)
        st.button("Start detailed underwriting →", use_container_width=True, key="start_d",
                  on_click=choose_mode, args=("detailed",))


def header(subtitle: str):
    c1, c2, c3 = st.columns([3, 1.5, 1])
    with c1:
        styles.brand(subtitle)
    if ss["mode"] == "quick":
        c2.button("Detailed underwriting", key="nav_switch", on_click=quick_to_detailed)
    else:
        c2.button("Quick estimate", key="nav_switch", on_click=choose_mode, args=("quick",))
    c3.button("Start over", key="nav_restart", on_click=restart)


# ======================================================================
# QUICK ESTIMATE
# ======================================================================
def quick_flow():
    t = ss.get("p_q_type")
    header(f"{TYPES[t][0]} valuation · Quick estimate" if t else "Quick estimate")
    {1: q_step1, 2: q_step2, 3: q_step3}[ss.get("q_step", 1)]()


def size_label(t: str) -> tuple[str, str, float]:
    return {"multifamily": ("Number of units", "e.g. 120", 1.0),
            "home": ("Heated square feet", "e.g. 2,100", 50.0)}.get(t, ("Rentable square feet", "e.g. 100,000", 1000.0))


EXPIRY_OPTIONS = {"Within the next 12 months": "Within 12 months", "In 1–3 years": "1–3 years",
                  "More than 3 years from now": "More than 3 years", "I'm not sure": "Not sure"}
RENT_BASIS = ["Actual rent from existing leases", "Estimated market rent"]


def subtype_picker(key: str, size):
    """Industrial subtype: suggested from size, but the owner must confirm it."""
    styles.qhead("What kind of industrial property is it?")
    subtypes = list(md.INDUSTRIAL_SUBTYPES)
    sub = w(st.selectbox, "Industrial property type", subtypes, index=None, key=key,
            placeholder="Choose the closest match", label_visibility="collapsed")
    if sub:
        styles.hint(md.INDUSTRIAL_SUBTYPES[sub]["why"])
    elif size:
        styles.hint(f"Based on size alone this looks like {md.suggest_subtype(size).lower()}, but size doesn't "
                    "reliably identify how a building is used — please confirm.")
    with st.expander("Why property type matters"):
        st.markdown("| Industrial property type | Why it matters |\n|---|---|\n" +
                    "\n".join(f"| {k} | {v['why']} |" for k, v in md.INDUSTRIAL_SUBTYPES.items()))
    return sub


def q_step1():
    styles.progress(1, "Property details")
    styles.title("What type of property are you valuing?", "Start with the basics. You can add financial details later.")
    type_cards("q")
    t = ss.get("p_q_type")
    w(st.selectbox, "Market", MARKET_LIST, key="p_q_market")
    size, ready = None, False
    if t:
        lbl, ph, step = size_label(t)
        size = w(st.number_input, lbl, min_value=0.0, value=None, step=step, key=f"p_q_size_{t}", format="%.0f",
                 placeholder=ph)
        ready = bool(size and size > 0)
        if t == "industrial":
            ready = bool(subtype_picker("p_q_subtype", size)) and ready
    nav(None, None, "Continue →", ready, "q1_next", on_click=go, args=("q_step", 2))


def _income(t: str, size: float) -> dict:
    """Rent the property generates, distinguishing contract rent from an estimate of market rent."""
    mf = t == "multifamily"
    k = 12 if mf else 1                                    # apartments: rents are monthly
    occ = (ss.get(f"p_q_occ_{t}") or 0) / 100
    occ_amt, vac_amt = size * occ, size * (1 - occ)
    basis = "estimated" if ss.get(f"p_q_basis_{t}") == RENT_BASIS[1] else "actual"
    total_mode = ss.get(f"p_q_rentmode_{t}") == "Total annual rent"
    if total_mode:
        annual = ss.get(f"p_q_annual_{t}") or 0.0
        denom = occ_amt if basis == "actual" else size
        rate = annual / denom / k if denom else 0.0
    else:
        rate = (ss.get(f"p_q_unitrent_{t}") if mf else ss.get(f"p_q_psf_{t}")) or 0.0
    market = rate if basis == "estimated" else (ss.get(f"p_q_mkt_{t}") or rate)
    current = rate * occ_amt * k
    return {"basis": basis, "rate": rate, "market": market, "occ": occ, "occ_amt": occ_amt, "vac_amt": vac_amt,
            "current": current, "potential": current + market * vac_amt * k, "mf": mf,
            "market_given": basis == "actual" and bool(ss.get(f"p_q_mkt_{t}"))}


def q_step2():
    t = ss["p_q_type"]
    market = ss["p_q_market"]
    _, full = place(market)
    size = ss[f"p_q_size_{t}"]
    label, _, icon = TYPES[t]
    styles.progress(2, "Property income" if t != "home" else "Recent sales")
    if t == "home":
        return q_step2_home(full, size)
    styles.title("Tell us about your property's income",
                 "A few numbers help us estimate what your building could be worth. Don't worry if you don't know "
                 "everything.")
    mf = t == "multifamily"
    u = "units" if mf else "SF"
    kind = f"{label} · {size:,.0f} units" if mf else f"{label} · {size:,.0f} rentable SF"
    if t == "industrial" and ss.get("p_q_subtype"):
        kind += f" · {ss['p_q_subtype']}"
    styles.facts_lines(full, icon, kind)
    st.divider()

    styles.qhead("1. How much of the building is currently occupied?")
    occ = ss.setdefault(f"p_q_occ_{t}", 95)
    c1, c2 = st.columns([3, 1])
    c1.markdown("Occupied space")
    c2.markdown(f'<div class="bignum">{occ}%</div>', unsafe_allow_html=True)
    st.slider("Occupied space", 0, 100, key=f"p_q_occ_{t}", label_visibility="collapsed", format="%d%%")
    occ = ss[f"p_q_occ_{t}"]
    styles.split(f"{size * occ / 100:,.0f} {u} occupied", f"{size * (1 - occ / 100):,.0f} {u} vacant")
    st.divider()

    styles.qhead("2. How much rent does your property generate?")
    styles.hint("Enter the rent tenants are currently contracted to pay, not what you think the space could rent "
                "for today.")
    ss.setdefault(f"p_q_basis_{t}", RENT_BASIS[0])
    st.radio("Rent basis", RENT_BASIS, key=f"p_q_basis_{t}", label_visibility="collapsed")
    actual = ss[f"p_q_basis_{t}"] == RENT_BASIS[0]
    modes = ["Per unit" if mf else "Per SF", "Total annual rent"]
    ss.setdefault(f"p_q_rentmode_{t}", modes[0])
    mode = st.segmented_control("How to enter rent", modes, key=f"p_q_rentmode_{t}",
                                label_visibility="collapsed") or modes[0]
    if mode == "Total annual rent":
        w(st.number_input, "Total annual rent from current tenants ($)" if actual
          else "Estimated annual rent for the whole property at market ($)",
          min_value=0.0, value=None, step=10000.0, key=f"p_q_annual_{t}", format="%.0f")
    elif mf:
        w(st.number_input, "Average monthly rent per occupied unit ($)" if actual
          else "Estimated market rent per unit, per month ($)",
          min_value=0.0, value=None, step=25.0, key=f"p_q_unitrent_{t}", format="%.0f")
    else:
        w(st.number_input, "Annual rent per occupied square foot ($)" if actual
          else "Estimated market rent per square foot, per year ($)",
          min_value=0.0, value=None, step=0.25, key=f"p_q_psf_{t}", format="%.2f")
    inc = _income(t, size)
    if inc["rate"]:
        if mf:
            st.caption(f"{money(inc['rate'])}/unit/month × {inc['occ_amt']:,.0f} occupied units × 12 = "
                       f"{money(inc['current'])} a year from current tenants.")
        else:
            st.caption(f"${inc['rate']:,.2f}/SF/year × {inc['occ_amt']:,.0f} occupied SF = {money(inc['current'])} "
                       "a year from current tenants.")
    if actual:
        w(st.number_input, ("What would a vacant unit rent for today? ($/month, optional)" if mf
                            else "Current market rent for this building ($/SF/year, optional)"),
          min_value=0.0, value=None, step=0.25 if not mf else 25.0, key=f"p_q_mkt_{t}",
          format="%.2f" if not mf else "%.0f",
          help="Used to price vacant space" + ("" if mf else " and leases that renew or roll over") +
               ". Leave blank to assume your current rent.")
    else:
        styles.note("You're describing hypothetical income",
                    "An estimate of market rent isn't the same as what tenants pay. The result will be marked less "
                    "reliable — switch to actual rent if you have the leases.")

    lease = None
    if not mf:
        st.divider()
        styles.qhead("3. How are the leases structured?")
        ss.setdefault(f"p_q_lease_{t}", "Triple net (NNN)" if t == "industrial" else "Full-service gross")
        lease = st.segmented_control("Lease structure", list(LEASE_OPTIONS), key=f"p_q_lease_{t}",
                                     label_visibility="collapsed") or "Triple net (NNN)"
        styles.hint(LEASE_HELP + " This choice has a big effect on value: it decides who pays the expenses.")
        if LEASE_OPTIONS[lease] != "gross":
            reimb_opts = ["Yes, their full share", "Partly — I pay some costs", "Not sure"]
            ss.setdefault(f"p_q_reimb_{t}", reimb_opts[0])
            st.radio("Do tenants reimburse their full share of operating expenses and taxes?", reimb_opts,
                     key=f"p_q_reimb_{t}", horizontal=True)
            if ss[f"p_q_reimb_{t}"] == reimb_opts[1]:
                w(st.number_input, "About how much do you pay each year that tenants don't reimburse? ($, optional)",
                  min_value=0.0, value=None, step=1000.0, key=f"p_q_nonrec_{t}", format="%.0f",
                  help="Roof and structure repairs, admin costs, caps on reimbursements. Leave blank and the model "
                       "assumes 15% of operating expenses.")

        st.divider()
        styles.qhead("4. When do most of your leases expire?")
        styles.hint("An approximate answer is fine.")
        ss.setdefault(f"p_q_expiry_{t}", "I'm not sure")
        st.radio("Lease expirations", list(EXPIRY_OPTIONS), key=f"p_q_expiry_{t}", label_visibility="collapsed")
        if ss[f"p_q_expiry_{t}"] == "I'm not sure":
            styles.note("The model will assume a staggered lease-expiration schedule",
                        "Leased space is assumed to roll evenly over a typical lease term. That's an approximation, "
                        "not your actual lease dates.")
        else:
            styles.hint("Used to shape an approximate expiration schedule — the model doesn't know your individual "
                        "lease dates.")

    st.write("")
    with st.expander("Additional property details (optional)", icon=":material/tune:"):
        opex = w(st.number_input, "Annual operating expenses ($)", min_value=0.0, value=None, step=1000.0,
                 key="p_q_opex", format="%.0f",
                 help="Insurance, utilities, repairs, payroll, admin — the full amount, even what tenants reimburse. "
                      "Leave out property taxes and management fees.")
        w(st.number_input, "Current annual property tax bill ($)", min_value=0.0, value=None, step=1000.0,
          key="p_q_bill", format="%.0f")
        w(st.number_input, "Other annual income ($)", min_value=0.0, value=0.0, step=1000.0, key="p_q_other",
          format="%.0f", help="Parking, laundry, fees, cell towers.")
        st.markdown("**Income snapshot**")
        st.markdown(
            f"| | |\n|---|---:|\n| Rent from current tenants | {money(inc['current'])} |\n"
            f"| Vacant space at {'your market rent' if inc['market_given'] else 'the same rent'} | "
            f"{money(inc['potential'] - inc['current'])} |\n"
            f"| Potential annual rent | {money(inc['potential'])} |\n"
            f"| Operating expenses | {money(opex) if opex is not None else 'To be estimated'} |")
        st.caption("Illustrative figures before concessions, collection losses, expense recoveries and property "
                   "taxes. Not a valuation or NOI calculation.")
    nav("q_step", 1, "Continue to estimate →", inc["potential"] > 0 and occ > 0, "q2_next", on_click=go,
        args=("q_step", 3))


def q_step2_home(full, size):
    styles.title("What have nearby homes sold for?",
                 "Enter 2–3 homes that sold in the last year, within about a mile, and similar in size. On Zillow "
                 "or Redfin, search your area and filter to Sold.")
    styles.facts_lines(full, "home", f"Single-family · {size:,.0f} heated SF")
    st.divider()
    n = 0
    for i in range(3):
        with st.container(border=True):
            st.markdown(f"**Sale {i + 1}**" + (" (optional)" if i == 2 else ""))
            c1, c2, c3 = st.columns([1.4, 1, 1])
            p = w(c1.number_input, "Sale price ($)", min_value=0.0, value=None, step=5000.0, key=f"p_q_hp{i}",
                  format="%.0f")
            s = w(c2.number_input, "Square feet", min_value=0.0, value=None, step=50.0, key=f"p_q_hs{i}", format="%.0f")
            w(c3.number_input, "Months ago", min_value=0, max_value=36, value=6, step=1, key=f"p_q_hm{i}")
            n += bool(p and s)
    with st.expander("Additional property details (optional)", icon=":material/tune:"):
        w(st.number_input, "Monthly rent, if you rent it out ($)", min_value=0.0, value=0.0, step=50.0,
          key="p_q_hrent", format="%.0f")
    nav("q_step", 1, "Continue to estimate →", n >= 2, "q2_next", on_click=go, args=("q_step", 3))


def quick_inputs(t: str, cls) -> tuple[Inputs, list[str], dict]:
    """Turn the quick answers into model inputs, listing every assumption the model made.
    Returns (inputs, assumptions used, facts for the reliability rating)."""
    market, size = ss["p_q_market"], ss[f"p_q_size_{t}"]
    inc = _income(t, size)
    subtype = ss.get("p_q_subtype") if t == "industrial" else None
    used = []
    opex = ss.get("p_q_opex")
    opex_given = opex is not None
    if not opex_given:
        rate_oe = md.INDUSTRIAL_SUBTYPES[subtype]["quick_opex"] if subtype else md.QUICK_OPEX[t]
        opex = rate_oe * size
        used.append(f"Operating expenses of {money(opex)}/yr ("
                    f"{money(rate_oe) + ' per unit' if t == 'multifamily' else f'${rate_oe:.2f} per SF'}"
                    f"{' for ' + subtype.lower() if subtype else ''}) — a rule of thumb, not your actual costs.")
    bill = ss.get("p_q_bill") if ss.get("p_q_taxmode", "").startswith("Use my") else None
    if bill is None:
        row = md.MARKETS[market]
        used.append(f"Property taxes at the local average of "
                    f"{row['tax_apartment' if t == 'multifamily' else 'tax_commercial']:.2%} of value.")
    if not cls:
        used.append("Building priced as Class B, with the range widened toward A and C.")
    if inc["basis"] == "estimated":
        used.append("Rent is your estimate of market rent, not contract rent — current tenants are assumed to pay it.")
    elif inc["vac_amt"] > 0 and not inc["market_given"]:
        used.append("Vacant space assumed to lease at the same rent current tenants pay.")
    facts = {"rent_actual": inc["basis"] == "actual", "opex_given": opex_given, "tax_given": bill is not None,
             "leases_known": None}
    common = dict(sector=t, market=market, size=size, gpr=inc["potential"], physical_vacancy=1 - inc["occ"],
                  opex=opex, other_income=ss.get("p_q_other") or 0.0, pclass=cls, current_tax=bill,
                  quality_grade="B", quick=True, subtype=subtype, rent_basis=inc["basis"])
    if t == "multifamily":
        return Inputs(**common), used, facts

    lt = LEASE_OPTIONS[ss.get(f"p_q_lease_{t}") or "Triple net (NNN)"]
    expiry = EXPIRY_OPTIONS.get(ss.get(f"p_q_expiry_{t}"), "Not sure")
    facts["leases_known"] = expiry != "Not sure"
    term = md.leasing_for(t, subtype)["term"]
    groups = md.INDUSTRIAL_SUBTYPES[subtype]["groups"] if subtype else 5
    if groups == 1:      # single-tenant building: one lease
        month = {"Within 12 months": 8, "1–3 years": 24, "More than 3 years": max(54, int(term * 12 * 0.7))}.get(
            expiry, int(term * 12 / 2))
        profile = [(1.0, month)]
    else:
        profile = md.lease_profile(expiry, t)
    leased = inc["occ_amt"]
    suites = [{"suite": f"Lease group {i + 1}", "tenant": "Existing tenants", "sf": leased * share,
               "rent": leased * share * inc["rate"], "lease_type": lt, "months_left": month, "vacant": False,
               "market_psf": inc["market"]} for i, (share, month) in enumerate(profile)] if leased > 0 else []
    if inc["vac_amt"] > 0:
        suites.append({"suite": "Vacant", "tenant": "", "sf": inc["vac_amt"], "rent": 0.0, "lease_type": lt,
                       "months_left": None, "vacant": True, "market_psf": inc["market"]})
    tenancy = "a single-tenant building" if groups == 1 else "several leases"
    if expiry == "Not sure":
        used.append(f"Lease expirations unknown: modeled as {tenancy} with a staggered schedule over a typical "
                    f"{term:.0f}-year term — an approximation, not your actual lease dates.")
    else:
        used.append(f"Most leases expire {expiry.lower()}: modeled approximately as {tenancy}"
                    + (" rolling in that window" if groups == 1 else ", 60% of leased space rolling in that window")
                    + ". The model doesn't know your individual lease dates.")
    nonrec = 0.0
    if lt != "gross":
        reimb = ss.get(f"p_q_reimb_{t}", "Yes, their full share")
        if reimb.startswith("Partly"):
            nonrec = ss.get(f"p_q_nonrec_{t}")
            if nonrec is None:
                nonrec = 0.15 * opex
                used.append(f"Unreimbursed owner costs of {money(nonrec)}/yr (15% of operating expenses) — an "
                            "assumption; enter your figure in step 2.")
        elif reimb == "Not sure":
            used.append("Tenants assumed to reimburse their full share of expenses and taxes on occupied space. If "
                        "you cover some costs, the value is lower.")
    common["quick"] = expiry == "Not sure"     # a real answer turns on the rollover-risk adjustments
    return Inputs(**common, suites=suites, nonrecoverable=nonrec), used, facts


def q_step3():
    t = ss["p_q_type"]
    market, size = ss["p_q_market"], ss[f"p_q_size_{t}"]
    city, full = place(market)
    label, _, icon = TYPES[t]
    styles.progress(3, "Review & Estimate", right_chip=True)
    styles.title("Your property is ready for review", "Check the details below before generating your preliminary valuation.")
    if t == "home":
        return q_step3_home(full, size)

    mf = t == "multifamily"
    inc = _income(t, size)
    occ, potential = inc["occ"], inc["potential"]
    if mf:
        third = ("Rent from current tenants", money(inc["current"]), f"{money(inc['rate'])} / unit / month")
    else:
        lt = LEASE_OPTIONS[ss.get(f"p_q_lease_{t}") or "Triple net (NNN)"]
        third = ("Lease structure", *LEASE_NAMES[lt])
    sub = ss.get("p_q_subtype") if t == "industrial" else None
    styles.summary_card("PROPERTY SUMMARY", f"{city} {label if mf else label + ' Property'}",
                        f"{full} · {size:,.0f} {'units' if mf else 'SF'}" + (f" · {sub}" if sub else ""), icon, [
                            ("Potential annual rent", money(potential),
                             f"{money(potential / size / 12)} / unit / month" if mf else f"${potential / size:,.2f} / SF / year"),
                            ("Current occupancy", f"{occ:.0%}", f"{inc['occ_amt']:,.0f} {'units' if mf else 'SF'} occupied"),
                            third,
                            ("Rent basis", "Contract rent" if inc["basis"] == "actual" else "Estimated",
                             "From existing leases" if inc["basis"] == "actual" else "Hypothetical — less reliable"),
                        ])

    styles.qhead("Building quality", "Optional")
    cls = CLASS_OPTIONS[w(st.selectbox, "Building quality", list(CLASS_OPTIONS), key="p_q_class",
                          label_visibility="collapsed")]

    opex = ss.get("p_q_opex")
    styles.qhead("Operating expenses & property taxes", "Provided" if opex is not None else "Estimates required",
                 badge="ok" if opex is not None else "warn")
    if opex is None:
        rec = (" With NNN leases, tenant reimbursements are modeled separately so expenses aren't counted twice."
               if not mf and str(ss.get(f"p_q_lease_{t}", "")).startswith("Triple") else "")
        styles.note("Annual operating expenses: Unknown",
                    f"The model will use a disclosed preliminary assumption of "
                    f"{money((md.INDUSTRIAL_SUBTYPES[sub]['quick_opex'] if sub else md.QUICK_OPEX[t]) * size)} per "
                    f"year.{rec} You can enter your actual figure in step 2.")
    else:
        styles.note(f"Annual operating expenses: {money(opex)}", "From your entry in step 2.")
    tax_opts = ["Use a local property tax assumption", "Use my actual tax bill"]
    ss.setdefault("p_q_taxmode", tax_opts[1] if ss.get("p_q_bill") else tax_opts[0])
    st.radio("Property tax information", tax_opts, key="p_q_taxmode")
    tax_ok = True
    if ss["p_q_taxmode"] == tax_opts[1]:
        bill = w(st.number_input, "Current annual property tax bill ($)", min_value=0.0, value=None, step=1000.0,
                 key="p_q_bill", format="%.0f")
        if not bill:
            tax_ok = False
            st.error("Enter your annual tax bill, or switch back to the local property tax assumption. The estimate "
                     "won't run on a blank bill.")

    rule = md.TAX_RULES[md.MARKETS[market]["state"]]
    capb = md.cap_benchmark(t, market)
    vac, _ = md.stabilized_vacancy(t, market)
    with st.expander("What assumptions will the model use?", icon=":material/tune:"):
        lines = [f"**Cap rate:** {capb['cap']:.2%} — {capb['label']}. Confidence {capb['confidence']}: {capb['why']}",
                 f"**Long-run vacancy:** {vac:.0%}, the market's stabilized level",
                 f"**Operating expenses:** {money(opex) if opex is not None else money((md.INDUSTRIAL_SUBTYPES[sub]['quick_opex'] if sub else md.QUICK_OPEX[t]) * size) + ' (rule of thumb)'}"
                 ", plus 3% management and capital reserves",
                 f"**Property taxes:** {rule['text']}",
                 f"**Rent growth:** {md.STANDARD[t]['rent_growth']:.2%} per year (investor surveys)",
                 "**Discount rate:** the cap rate plus an investor-survey spread and risk adjustments"]
        if sub:
            lines.append(f"**Property type:** {sub} — {md.INDUSTRIAL_SUBTYPES[sub]['evidence']}")
        if not mf:
            L = md.leasing_for(t, sub)
            lines.append(f"**Leases:** expirations spread over {L['term']:.0f} years; {L['renewal_prob']:.0%} renew, "
                         f"otherwise {L['downtime']:.0f} months vacant and ${L['ti_new']:.0f}/SF improvements for a new tenant")
        st.markdown("\n".join(f"- {x}" for x in lines))
        st.caption(capb["scope"])

    styles.qhead("Valuation method")
    methods = ["Preliminary estimate — simplified assumptions",
               "Detailed underwriting — upload lease and expense information"]
    w(st.radio, "Valuation method", methods, key="p_q_method", label_visibility="collapsed")
    if ss["p_q_method"] == methods[1]:
        st.button("Switch to detailed underwriting →", type="primary", use_container_width=True, key="q_to_d",
                  on_click=quick_to_detailed)
        st.caption("Your property type, market, size, rent and expenses carry over.")
        st.button("Back", key="q3_back", on_click=go, args=("q_step", 2))
        return
    inp, used, facts = quick_inputs(t, cls)
    q = quality.check(t, market, size, inp.gpr, inp.physical_vacancy, inp.opex,
                      current_tax=inp.current_tax, other_income=inp.other_income)
    inp.quality_grade = q["grade"]
    styles.qhead("Input quality", f"Grade {q['grade']}", badge="ok" if q["grade"] == "A" else "warn")
    styles.note(q["grade_text"], q["scope"] + " This quick estimate also relies on the market assumptions above, so "
                "its range reflects those assumptions, not a measured accuracy.")
    for sev, msg in q["items"]:
        SEVERITY[sev](msg)
    ack = w(st.checkbox, "I understand that missing expenses and lease information will affect the reliability of "
                         "this estimate.", value=False, key="p_q_ack")
    c1, c2 = st.columns([1, 3])
    c1.button("Back", key="q3_back", use_container_width=True, on_click=go, args=("q_step", 2))
    calc = c2.button("Calculate estimate", type="primary", use_container_width=True, key="q_calc",
                     disabled=not (ack and tax_ok))
    if not ack:
        st.caption("Check the box above to calculate.")
    sig = repr(asdict(inp))
    if calc:
        try:
            ss["_q_res"], ss["_q_err"] = underwrite(inp), None
            ss["_q_moves"] = what_moves(inp)
        except ValuationError as e:
            ss["_q_res"], ss["_q_err"] = None, str(e)
        ss["_q_sig"] = sig
    if not ss.get("_q_sig"):
        return
    if ss["_q_sig"] != sig or not (ack and tax_ok):
        st.info("Your inputs changed since the last calculation. Select Calculate estimate to update it.")
        return
    if ss["_q_err"]:
        st.error(ss["_q_err"])
        return
    show_quick_result(ss["_q_res"], inp, used, ss.get("_q_moves", []), facts)


def show_reasonableness(rc: dict, inp: Inputs):
    unit = "unit" if inp.sector == "multifamily" else "SF"
    with st.container(border=True):
        st.caption("REASONABLENESS CHECK")
        if rc["status"] == "none":
            st.markdown(f"**{money(rc['per'])} / {unit}** — your estimate")
            st.caption(rc["message"])
            return
        b = rc["bench"]
        c1, c2 = st.columns(2)
        c1.markdown(f"### {money(rc['per'])} / {unit}")
        c1.caption("Your estimate")
        c2.markdown(f"### {money(b['low'])}–{money(b['high'])} / {unit}")
        c2.caption("Published market sale prices, adjusted" + (f" ({', '.join(b['adjustments'])})"
                                                                if b["adjustments"] else ""))
        if rc["status"] == "within":
            st.success(f"Consistent with market pricing — {rc['ratio']:.0%} of the adjusted market average.")
        else:
            word = "exceeds" if rc["status"] == "above" else "falls below"
            st.warning(f"**Review recommended.** The estimate {word} the market range ({rc['ratio']:.0%} of the "
                       "adjusted average). Likely reasons to check:\n" + "\n".join(f"- {x}" for x in rc["reasons"]))
        src = "; ".join(f"{p[1]} Q{p[3]} {p[2]}: {money(p[0])}" for p in b["points"])
        st.caption(f"Benchmark: average of {src} — market-wide averages of all sales, ±25% band. "
                   + ("Sources disagree by more than 25%, so treat this band loosely. " if b["volatile"] else "")
                   + "This check flags discrepancies; it never changes the estimate.")


def what_moves(inp: Inputs) -> list[tuple[str, float]]:
    """Re-run the quick model with the inputs owners most often get wrong."""
    out = []
    for label, change in (("Operating expenses 25% higher", dict(opex=inp.opex * 1.25,
                                                                  nonrecoverable=inp.nonrecoverable * 1.25)),
                          ("Operating expenses 25% lower", dict(opex=inp.opex * 0.75,
                                                                 nonrecoverable=inp.nonrecoverable * 0.75))):
        try:
            out.append((label, underwrite(replace(inp, **change), sensitivity=False)["value"]))
        except ValuationError:
            pass
    if inp.suites:
        current = inp.suites[0]["lease_type"]
        for name, key in LEASE_OPTIONS.items():
            if key == current:
                continue
            alt = replace(inp, suites=[{**x, "lease_type": key} for x in inp.suites],
                          nonrecoverable=0.0 if key == "gross" else inp.nonrecoverable)
            try:
                out.append((f"If the leases are {name}", underwrite(alt, sensitivity=False)["value"]))
            except ValuationError:
                pass
    return out


def show_quick_result(r, inp, used, moves, facts):
    mf = inp.sector == "multifamily"
    styles.result_panel(r["low"], r["value"], r["high"], [
        ("Per unit" if mf else "Per SF", money(r["per_unit"])),
        ("Cap rate", f"{r['cap_rate']:.2%}"),
        ("Cap rate confidence", r["cap_confidence"]),
        ("Stabilized NOI", money(r["stabilized_noi"]["noi"])),
    ], range_note=r["range_label"])
    for m in r["warnings"]:
        st.warning(m)
    recon = checks.reasonableness(r, inp, {"opex": not facts["opex_given"], "tax": not facts["tax_given"]})
    show_reasonableness(recon, inp)
    rel = checks.reliability(inp, r["cap_confidence"], recon, facts)
    styles.qhead("Estimate reliability", rel["label"], badge="ok" if rel["label"] == "Higher" else "warn")
    st.markdown(rel["text"] + "\n" + "\n".join(f"- {mark} {txt}" for mark, txt in rel["items"]))
    st.markdown("**What the model assumed for you**\n" + "\n".join(f"- {u}" for u in used))
    if moves:
        st.markdown("**What moves this estimate**\n\n| If… | Estimate | Change |\n|---|---:|---:|\n" +
                    "\n".join(f"| {lbl} | {money(v)} | {'+' if v >= r['value'] else '−'}{money(abs(v - r['value']))} "
                              f"({abs(v / r['value'] - 1):.1%}) |" for lbl, v in moves))
        st.caption("Under NNN leases, tenants pay most expenses, so your expense figure mainly matters for vacant "
                   "space and costs you don't recover. Under gross leases, every dollar of expense comes out of "
                   "your income, which is why getting the lease type right matters so much.")
    with st.expander("How this estimate was built"):
        wts = r["weights"]
        st.markdown(f"| Method | Value | Weight |\n|---|---:|---:|\n"
                    f"| Direct capitalization | {money(r['direct_cap'])} | {wts['dc']:.0f}% |\n"
                    f"| Discounted cash flow (10 years) | {money(r['dcf_value'])} | {wts['dcf']:.0f}% |\n"
                    f"| **Estimate** | **{money(r['value'])}** | |")
        st.markdown("\n".join(f"- {x}" for x in r["weight_reasons"]))
        s = r["stabilized_noi"]
        st.markdown(f"Stabilized NOI {money(s['noi'])} = rent {money(s['potential_rent'])} − vacancy "
                    f"{money(-s['vacancy'])} − collection loss {money(-s['credit_loss'])} + other income "
                    f"{money(s['other_income'])} + reimbursements {money(s['recoveries'])} − expenses "
                    f"{money(-s['opex'])} − management {money(-s['management'])} − reserves "
                    f"{money(-s['reserves'])} − taxes {money(-s['taxes'])}. Discount rate {r['discount']:.2%}.")
        for n in r["notes"]:
            st.caption(n)
    with st.container(border=True):
        st.markdown("**Want a tighter number?** Detailed underwriting reviews your actual rent roll, lease dates, "
                    "expenses and tax bill, and models each lease separately.")
        st.button("Continue to detailed underwriting →", key="q_cta", use_container_width=True,
                  on_click=quick_to_detailed)
    st.download_button("Download underwriting summary (Excel)",
                       export.build(r, f"{TYPES[inp.sector][0]}, {inp.market} (quick estimate)",
                                    [("Market", inp.market), ("Size", f"{inp.size:,.0f}"),
                                     ("Potential rent", money(inp.gpr)),
                                     ("Occupancy", f"{1 - inp.physical_vacancy:.0%}"),
                                     ("Estimate type", "Quick estimate")]),
                       "quick_estimate.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="dl_q", use_container_width=True)


def q_step3_home(full, size):
    comps = [{"address": f"Sale {i + 1}", "price": ss[f"p_q_hp{i}"], "sf": ss[f"p_q_hs{i}"],
              "months_ago": ss.get(f"p_q_hm{i}", 6)}
             for i in range(3) if ss.get(f"p_q_hp{i}") and ss.get(f"p_q_hs{i}")]
    psfs = sorted(c["price"] / c["sf"] for c in comps)
    styles.summary_card("PROPERTY SUMMARY", f"{full.split(',')[0]} Home", f"{full} · {size:,.0f} SF", "home", [
        ("Nearby sales entered", str(len(comps)), "price and size"),
        ("Sale prices per SF", f"${psfs[0]:,.0f}–${psfs[-1]:,.0f}", "before size adjustment"),
    ])
    if any(c["months_ago"] > 12 for c in comps):
        st.info("Some sales are over a year old — prices may have moved since. Detailed underwriting adjusts for "
                "market change, bedrooms, baths, age and condition.")
    ack = w(st.checkbox, "I understand this quick estimate adjusts only for size, not condition, age or features.",
            value=False, key="p_q_hack")
    st.button("Back", key="q3h_back", on_click=go, args=("q_step", 2))
    if not ack:
        return
    r = home.quick_estimate(size, comps)
    styles.result_panel(r["low"], r["value"], r["high"], [
        ("Per SF", money(r["per_sf"])), ("Sales used", str(len(comps))),
        ("Median comp $/SF", money(r["med_psf"])), ("Approach", "Sales comparison"),
    ], range_note="Range spans the size-adjusted sales (at least ±5%) — not a statistical confidence interval")
    with st.expander("How this estimate was built"):
        st.markdown("| Sale | Price | Sq ft | Size-adjusted |\n|---|---:|---:|---:|\n" +
                    "\n".join(f"| {c['address']} | {money(c['price'])} | {c['sf']:,.0f} | {money(c['adjusted'])} |"
                              for c in r["comps"]))
        st.caption("Each sale is adjusted for the size difference at half the median price per square foot (larger "
                   "homes sell for less per square foot). The estimate is the average adjusted price.")
    rent = ss.get("p_q_hrent") or 0
    if rent:
        rc = home.rental_check(r["value"], rent, 0)
        st.caption(f"As a rental: gross yield {rc['gross_yield']:.1%}, price-to-rent {rc['price_to_rent']:.1f}× annual rent.")
    st.button("Refine with detailed underwriting →", key="q_cta_h", use_container_width=True, on_click=quick_to_detailed)


# ======================================================================
# DETAILED UNDERWRITING — shared input pieces
# ======================================================================
def expense_breakdown(key: str, opex):
    st.markdown("**Expense detail** — different costs grow at different speeds")
    b1, b2, b3 = st.columns(3)
    ins = w(b1.number_input, "Insurance ($/yr)", min_value=0.0, value=None, step=1000.0, key=f"{key}_ins", format="%.0f",
            help=f"Grows {md.EXPENSE_GROWTH['insurance']:.1%}/yr — Southeast premiums have risen fastest.")
    util = w(b2.number_input, "Utilities ($/yr)", min_value=0.0, value=None, step=1000.0, key=f"{key}_utilx",
             format="%.0f", help=f"Grows {md.EXPENSE_GROWTH['utilities']:.1%}/yr.")
    pay = w(b3.number_input, "Payroll ($/yr)", min_value=0.0, value=None, step=1000.0, key=f"{key}_pay", format="%.0f",
            help=f"Grows {md.EXPENSE_GROWTH['payroll']:.1%}/yr.")
    parts = {k: v for k, v in (("insurance", ins), ("utilities", util), ("payroll", pay)) if v}
    if parts and opex is not None:
        rest = opex - sum(parts.values())
        if rest < 0:
            st.error("These add up to more than your total operating expenses.")
        else:
            st.caption(f"Everything else ({money(rest)}) grows {md.EXPENSE_GROWTH['other']:.1%}/yr.")
    return parts or None


def tax_inputs(key: str, market: str, bill):
    row = md.MARKETS[market]
    rule = md.TAX_RULES[row["state"]]
    st.markdown("**Property taxes**")
    st.caption(f"{row['state']} rule: {rule['text']}")
    t1, t2 = st.columns(2)
    appraised = w(t1.number_input, "County appraised value on your bill ($)", min_value=0.0, value=None,
                  step=10000.0, key=f"{key}_appr", format="%.0f",
                  help="With your bill, this gives your actual tax rate (bill ÷ appraised value).")
    rate = None
    if bill and appraised:
        rate = bill / appraised
        t1.caption(f"Your effective rate: **{rate:.2%}** of value")
    modes = {"Use the state's rule (recommended)": "default", "Reassessed to the sale price": "sale",
             "Keeps the current bill until revaluation": "cycle"}
    mode = modes[w(t2.selectbox, "After a sale, taxes are…", list(modes), key=f"{key}_tmode",
                   help="Override only if your county works differently from the state default.")]
    eff = rule["type"] if mode == "default" else mode
    a1, a2, a3 = st.columns(3)
    assess = reval = None
    if eff == "sale":
        assess = w(a1.number_input, "Assessed value as % of price", 20.0, 120.0, value=rule.get("factor", 1.0) * 100,
                   step=5.0, key=f"{key}_assess", help="SC defaults to 75% (point-of-sale exemption).") / 100
    else:
        reval = w(a1.number_input, "Years until next revaluation", 1, 8, value=md.years_to_reval(market), step=1,
                  key=f"{key}_reval", help="The buyer keeps today's bill until then.")
    abate = w(a2.number_input, "Tax abatement / PILOT savings ($/yr)", min_value=0.0, value=0.0, step=1000.0,
              key=f"{key}_abate", format="%.0f")
    yrs = w(a3.number_input, "Years of abatement left", 0, 30, value=0, step=1, key=f"{key}_abyrs") if abate else 0
    return {"tax_rate_override": rate, "tax_mode": mode, "assess_pct": assess, "years_to_reval": reval,
            "abatement": abate, "abatement_years": int(yrs)}


def growth_leaseup_inputs(key: str, sector: str):
    std = md.STANDARD[sector]
    st.markdown("**Market outlook**")
    g1, g2 = st.columns(2)
    growth = w(g1.number_input, "Annual market rent growth (%)", -5.0, 10.0, value=std["rent_growth"] * 100,
               step=0.25, key=f"{key}_growth", help="Default: investor-survey long-run assumption.")
    months = w(g2.number_input, "Months to lease up today's vacancy (0 = default)", 0, 60, value=0, step=1,
               key=f"{key}_lu", help=f"Default: {std['absorb_per_month']:.1%} of the property leases each month.")
    return growth / 100, (months or None)


def condition_inputs(key: str, items: list[str]):
    st.markdown("**Condition and upcoming repairs**")
    cols = st.columns(2)
    checked = [w(cols[i % 2].checkbox, label, value=False, key=f"{key}_chk{i}") for i, label in enumerate(items)]
    capex = w(st.number_input, "Major repairs needed in the next 2–3 years ($)", min_value=0.0, value=0.0,
              step=10000.0, key=f"{key}_capex", format="%.0f",
              help="Paid in year 1 — buyers price it in dollar for dollar.")
    if any(checked) and capex == 0:
        st.warning("You checked a major system near the end of its life. Enter an estimated replacement cost.")
    return capex


def comps_input(key: str, sector: str):
    unit = "Units" if sector == "multifamily" else "SF"
    st.markdown("**Comparable sales** — the strongest check on the cap rate")
    st.caption("Recent sales of similar properties nearby (broker, CoStar or county deed records). Sales older than "
               "24 months are ignored.")
    blank = pd.DataFrame({"Property": pd.Series(dtype=str), "Months ago": pd.Series(dtype=float),
                          "Price ($)": pd.Series(dtype=float), unit: pd.Series(dtype=float),
                          "Cap rate (%)": pd.Series(dtype=float), "Class": pd.Series(dtype=str)})
    ed = persistent_editor(f"comps_{key}", blank, "blank", num_rows="dynamic", use_container_width=True,
                           hide_index=True, column_config={
                               "Months ago": st.column_config.NumberColumn(min_value=0, max_value=60, step=1),
                               "Price ($)": st.column_config.NumberColumn(min_value=0, format="$%d"),
                               unit: st.column_config.NumberColumn(min_value=0),
                               "Cap rate (%)": st.column_config.NumberColumn(min_value=2.0, max_value=15.0, step=0.05),
                               "Class": st.column_config.SelectboxColumn(options=["A", "B", "C"]),
                           })
    comps = []
    for _, r in ed.iterrows():
        if pd.notna(r["Price ($)"]) and pd.notna(r[unit]) and r["Price ($)"] > 0 and r[unit] > 0:
            comps.append({"name": r["Property"] if isinstance(r["Property"], str) and r["Property"] else f"Sale {len(comps) + 1}",
                          "price": float(r["Price ($)"]), "size": float(r[unit]),
                          "months_ago": float(r["Months ago"]) if pd.notna(r["Months ago"]) else 0,
                          "cap": float(r["Cap rate (%)"]) / 100 if pd.notna(r["Cap rate (%)"]) else None,
                          "pclass": r["Class"] if isinstance(r["Class"], str) and r["Class"] else None})
    return comps or None


def discount_override_input(key: str):
    v = w(st.number_input, "Discount rate override (%, 0 = build it from the market)", 0.0, 20.0, value=0.0,
          step=0.25, key=f"{key}_disc", help="Only if you have a specific target return.")
    return v / 100 if v else None


def quality_gate(key: str, q: dict) -> bool:
    with st.container(border=True):
        st.markdown(f"**Input quality: grade {q['grade']}** — {q['grade_text']}")
        st.caption(q["scope"])
        for sev, msg in q["items"]:
            SEVERITY[sev](msg)
        if q["critical"]:
            return w(st.checkbox, "I've reviewed the critical items above and want to continue anyway.", value=False,
                     key=f"{key}_ack_{abs(hash(tuple(q['critical']))) % 10**8}")
    return True


# ======================================================================
# DETAILED UNDERWRITING — flow
# ======================================================================
def detailed_flow():
    t = ss.get("p_d_type")
    header(f"{TYPES[t][0]} · Detailed underwriting" if t else "Detailed underwriting")
    {1: d_step1, 2: d_step2, 3: d_step3}[ss.get("d_step", 1)]()


def d_step1():
    styles.progress(1, "Property details")
    styles.title("What are you underwriting?",
                 "Detailed underwriting values your property lease by lease. Have your rent roll, last year's "
                 "expenses and your property tax bill handy.")
    type_cards("d")
    t = ss.get("p_d_type")
    w(st.selectbox, "Market", MARKET_LIST, key="p_d_market")
    ready = bool(t)
    if t in ("multifamily", "industrial", "office"):
        w(st.selectbox, "Building quality", list(CLASS_OPTIONS), key="p_d_class")
    if t in ("industrial", "office"):
        c1, c2 = st.columns(2)
        bsf = w(c1.number_input, "Building rentable SF", min_value=0.0, value=None, step=1000.0, key=f"p_d_bsf_{t}",
                format="%.0f", placeholder="e.g. 100,000",
                help="From the survey, appraisal or leasing flyer. Checked against the rent roll.")
        mpsf = w(c2.number_input, "Market rent ($/SF/yr)", min_value=0.0, value=None, step=0.25, key=f"p_d_mpsf_{t}",
                 help="What a new tenant would pay today on the same lease type. Used for vacant suites, renewals "
                      "and new leases. Ask a leasing broker if unsure.")
        ready = bool(bsf and mpsf)
        if t == "industrial":
            ready = bool(subtype_picker("p_d_subtype", bsf)) and ready
    if t == "home":
        c1, c2, c3, c4 = st.columns(4)
        sf = w(c1.number_input, "Heated sq ft", min_value=0.0, value=None, step=50.0, key="p_d_h_sf", format="%.0f")
        beds = w(c2.number_input, "Bedrooms", 0, 15, value=None, step=1, key="p_d_h_beds")
        baths = w(c3.number_input, "Bathrooms", 0.0, 15.0, value=None, step=0.5, key="p_d_h_baths")
        yr = w(c4.number_input, "Year built", 1800, 2027, value=None, step=1, key="p_d_h_yr")
        ready = bool(sf and beds is not None and baths is not None and yr)
    nav(None, None, "Continue →", ready, "d1_next", on_click=go, args=("d_step", 2))


def d_step2():
    t = ss["p_d_type"]
    market = ss["p_d_market"]
    _, full = place(market)
    styles.progress(2, "Comparable sales" if t == "home" else "Rent roll & expenses")
    if t == "home":
        styles.title("Recent nearby sales", "Enter 3–5 homes that sold in the last 6–12 months, within about a mile.")
        ready, payload = d_home_financials()
    elif t == "multifamily":
        styles.title("Rent roll and expenses", "Upload your rent roll, review it by floorplan, then add expenses.")
        styles.facts_lines(full, "building", "Apartments")
        ready, payload = d_mf_financials(market)
    else:
        styles.title("Rent roll and expenses", "Upload your rent roll, review each suite, then add expenses.")
        styles.facts_lines(full, TYPES[t][2], f"{TYPES[t][0]} · {ss[f'p_d_bsf_{t}']:,.0f} rentable SF")
        ready, payload = d_cm_financials(t, market)
    if nav("d_step", 1, "Continue to estimate →", ready, "d2_next"):
        ss["d_payload"] = payload
        go("d_step", 3)
        st.rerun()


def d_mf_financials(market: str):
    K = "p_d_mf"
    st.divider()
    styles.qhead("1. Rent roll")
    parsed, src = upload_table("mf_roll", "Upload your rent roll (CSV or Excel)", rentroll.summarize,
                               "Needs unit and rent columns. Unit Type, Status and Market Rent columns help.")
    st.download_button("Download a blank template", rentroll.template().to_csv(index=False),
                       "apartment_rent_roll_template.csv", "text/csv", key="tpl_mf")
    if parsed:
        for m in parsed["warnings"]:
            st.info(m)
        base, flags, occ_rent = parsed["plans"], parsed["flags"], parsed["occupied_rent_monthly"]
    else:
        st.caption("No rent roll handy? Fill in the floorplan table instead.")
        base = pd.DataFrame({"Unit type": ["1 bed", "2 bed"], "Units": [float("nan")] * 2,
                             "Occupied": [float("nan")] * 2, "Avg in-place rent": [float("nan")] * 2,
                             "Market rent": [float("nan")] * 2})
        flags, occ_rent = [], None
    styles.qhead("2. Review by floorplan")
    styles.hint("Check the counts, and enter market rent so vacant units are priced correctly.")
    ed = persistent_editor("mf_plans", base, src, num_rows="dynamic", use_container_width=True, hide_index=True,
                           column_config={
                               "Units": st.column_config.NumberColumn(min_value=0, step=1),
                               "Occupied": st.column_config.NumberColumn(min_value=0, step=1),
                               "Avg in-place rent": st.column_config.NumberColumn("In-place rent ($/mo)", min_value=0, format="$%d"),
                               "Market rent": st.column_config.NumberColumn("Market rent ($/mo)", min_value=0, format="$%d"),
                           })
    totals = None
    if pd.to_numeric(ed["Units"], errors="coerce").fillna(0).sum() > 0:
        try:
            totals = rentroll.plans_to_totals(ed, occ_rent if parsed else None)
            st.success(f"{totals['units']:,.0f} units · {totals['occupied']:,.0f} occupied "
                       f"({1 - totals['physical_vacancy']:.0%}) · average potential rent {money(totals['avg_rent'])}/mo")
            for n in totals["notes"]:
                st.caption(n)
        except ValueError as e:
            st.error(str(e))

    styles.qhead("3. Income and expenses")
    e1, e2 = st.columns(2)
    opex = w(e1.number_input, "Annual operating expenses ($)", min_value=0.0, value=None, step=1000.0,
             key=f"{K}_opex", format="%.0f", help="Utilities, repairs, payroll, insurance, admin, marketing. Leave "
                                                  "OUT property taxes, management fees and reserves.")
    other = w(e2.number_input, "Other monthly income ($)", min_value=0.0, value=0.0, step=100.0, key=f"{K}_oth",
              format="%.0f", help="Parking, pet fees, laundry, RUBS.")
    bill = w(e1.number_input, "Current annual property tax bill ($)", min_value=0.0, value=None, step=1000.0,
             key=f"{K}_bill", format="%.0f")
    with st.expander("Add other information to improve accuracy", icon=":material/tune:"):
        ptype = w(st.selectbox, "Property type", ["Conventional", "Student housing", "Affordable / rent-restricted"],
                  key=f"{K}_ptype")
        breakdown = expense_breakdown(K, opex)
        taxes = tax_inputs(K, market, bill)
        st.markdown("**Income detail (from your T-12)**")
        i1, i2 = st.columns(2)
        collected = w(i1.number_input, "Rent collected, last 12 months ($)", min_value=0.0, value=None,
                      step=10000.0, key=f"{K}_coll", format="%.0f")
        conc = w(i2.number_input, "Concessions (% of rent)", 0.0, 50.0, value=0.0, step=0.5, key=f"{K}_conc")
        growth, months = growth_leaseup_inputs(K, "multifamily")
        capex = condition_inputs(K, ["Roof is 20+ years old", "Most HVAC is 15+ years old",
                                     "Polybutylene or galvanized plumbing", "Most interiors are original"])
        comps = comps_input("mf", "multifamily")
        disc = discount_override_input(K)
    warnings = []
    if ptype != "Conventional":
        warnings.append(f"{ptype} properties often trade at different cap rates than conventional apartments. This "
                        "estimate uses conventional assumptions and may be off.")
    if not (totals and opex is not None):
        return False, None
    q = quality.check("multifamily", market, totals["units"], totals["gpr_annual"], totals["physical_vacancy"],
                      opex, current_tax=bill, tax_rate=taxes["tax_rate_override"], rent_flags=flags,
                      collected=collected, other_income=other * 12)
    ok = quality_gate(K, q)
    cls = CLASS_OPTIONS[ss.get("p_d_class", list(CLASS_OPTIONS)[0])]
    inp = Inputs(sector="multifamily", market=market, size=totals["units"], gpr=totals["gpr_annual"],
                 physical_vacancy=totals["physical_vacancy"], opex=opex, opex_breakdown=breakdown,
                 other_income=other * 12, pclass=cls, current_tax=bill, concessions=conc / 100,
                 collected_rent=collected, capex=capex, rent_growth=growth, leaseup_months=months, comps=comps,
                 discount_override=disc, quality_grade=q["grade"], **taxes)
    owner = [("Market", market), ("Units", f"{inp.size:,.0f}"), ("Annual potential rent", money(inp.gpr)),
             ("Vacancy today", f"{inp.physical_vacancy:.1%}"), ("Operating expenses", money(opex)),
             ("Current tax bill", money(bill) if bill else "Not provided"), ("Building class", cls or "Not sure"),
             ("Input quality grade", q["grade"])]
    return ok, {"inp": inp, "owner": owner, "warnings": warnings, "grade": q["grade"]}


CM_UI = {
    "industrial": {"opex": "Insurance, common-area maintenance, repairs, utilities — the FULL annual amount, even the "
                           "part tenants reimburse. Leave out property taxes, management and reserves.",
                   "condition": ["Roof is 20+ years old", "Truck court needs repaving", "Dock doors need replacing",
                                 "Sprinklers out of date"], "default": "NNN"},
    "office": {"opex": "Utilities, janitorial, repairs, insurance, security, admin — the FULL annual amount, even the "
                       "part tenants reimburse. Leave out property taxes, management and reserves.",
               "condition": ["Roof is 20+ years old", "HVAC / chillers 20+ years old", "Elevators need modernization",
                             "Lobby / common areas dated"], "default": "Gross"},
}


def d_cm_financials(t: str, market: str):
    K = f"p_d_{t[:3]}"
    ui = CM_UI[t]
    bsf, mpsf = ss[f"p_d_bsf_{t}"], ss[f"p_d_mpsf_{t}"]
    st.divider()
    styles.qhead("1. Rent roll")
    parsed, src = upload_table(f"{t}_roll", "Upload your rent roll (CSV or Excel)", rentroll.parse_commercial,
                               "One row per suite: Suite, Tenant, SF, Annual Rent (or Monthly Rent or Rent/SF), Lease "
                               "Type, Lease End. Mark empty suites 'Vacant'.")
    st.download_button("Download a blank template", rentroll.commercial_template().to_csv(index=False),
                       f"{t}_rent_roll_template.csv", "text/csv", key=f"tpl_{t}")
    if parsed is not None:
        base = parsed.copy()
    else:
        st.caption("No file? Type your suites into the table below.")
        base = pd.DataFrame({"Suite": ["100"], "Tenant": [""], "SF": [float("nan")], "Annual Rent": [float("nan")],
                             "Lease Type": [ui["default"]], "Lease End": [None], "Market Rent $/SF": [float("nan")],
                             "Vacant": [False]})
    base["Lease End"] = pd.to_datetime(base["Lease End"], errors="coerce").dt.date
    styles.qhead("2. Review the rent roll")
    styles.hint("Fix anything that's wrong before valuing: duplicate suites, missing space, lease types and dates.")
    deflabel = w(st.selectbox, "Lease type for suites without one", list(rentroll.LABEL_TO_KEY),
                 index=list(rentroll.LABEL_TO_KEY).index(ui["default"]), key=f"{K}_deflease", help=LEASE_HELP)
    ed = persistent_editor(f"{t}_suites", base, src, num_rows="dynamic", use_container_width=True, hide_index=True,
                           column_config={
                               "SF": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                               "Annual Rent": st.column_config.NumberColumn("Annual rent ($)", min_value=0, format="$%d"),
                               "Lease Type": st.column_config.SelectboxColumn(options=list(rentroll.LABEL_TO_KEY)),
                               "Lease End": st.column_config.DateColumn(format="MM/DD/YYYY"),
                               "Market Rent $/SF": st.column_config.NumberColumn("Market rent $/SF (override)",
                                                                                 min_value=0, step=0.25),
                               "Vacant": st.column_config.CheckboxColumn(),
                           })
    review = None
    if pd.to_numeric(ed["SF"], errors="coerce").fillna(0).sum() > 0:
        try:
            review = rentroll.review_commercial(ed, bsf, rentroll.LABEL_TO_KEY[deflabel], mpsf)
            m = st.columns(4)
            m[0].metric("Rentable SF", f"{review['total_sf']:,.0f}")
            m[1].metric("Leased", f"{1 - review['physical_vacancy']:.0%}")
            m[2].metric("In-place rent", f"${review['avg_rent_psf']:,.2f}/SF")
            m[3].metric("Avg term left", f"{review['walt']:.1f} yrs")
        except ValueError as e:
            st.error(str(e))

    styles.qhead("3. Expenses")
    e1, e2 = st.columns(2)
    opex = w(e1.number_input, "Total annual operating expenses ($)", min_value=0.0, value=None, step=1000.0,
             key=f"{K}_opex", format="%.0f", help=ui["opex"])
    other = w(e2.number_input, "Other annual income ($)", min_value=0.0, value=0.0, step=1000.0, key=f"{K}_oth",
              format="%.0f")
    bill = w(e1.number_input, "Current annual property tax bill ($)", min_value=0.0, value=None, step=1000.0,
             key=f"{K}_bill", format="%.0f")
    warnings = []
    with st.expander("Add other information to improve accuracy", icon=":material/tune:"):
        breakdown = expense_breakdown(K, opex)
        st.markdown("**Expense recoveries (from your T-12)**")
        r1, r2 = st.columns(2)
        recov = w(r1.number_input, "Reimbursements collected, last 12 months ($)", min_value=0.0, value=None,
                  step=5000.0, key=f"{K}_recov", format="%.0f")
        nonrec = w(r2.number_input, "Costs tenants never reimburse ($/yr)", min_value=0.0, value=0.0, step=1000.0,
                   key=f"{K}_nonrec", format="%.0f")
        taxes = tax_inputs(K, market, bill)
        sub = ss.get("p_d_subtype") if t == "industrial" else None
        L = md.leasing_for(t, sub)
        st.markdown("**Leasing assumptions** — applied at every lease expiration"
                    + (f" (defaults for {sub.lower()})" if sub else ""))
        l1, l2, l3 = st.columns(3)
        renew = w(l1.number_input, "Renewal probability (%)", 0.0, 95.0, value=L["renewal_prob"] * 100, step=5.0,
                  key=f"{K}_renew_{sub or ''}")
        down = w(l2.number_input, "Months vacant if a tenant leaves", 0, 36, value=int(L["downtime"]), step=1,
                 key=f"{K}_down_{sub or ''}")
        term = w(l3.number_input, "New lease term (years)", 1, 15, value=int(L["term"]), step=1, key=f"{K}_term_{sub or ''}")
        ti_new = w(l1.number_input, "Improvements, new ($/SF)", 0.0, 200.0, value=float(L["ti_new"]), step=1.0,
                   key=f"{K}_tin_{sub or ''}")
        ti_ren = w(l2.number_input, "Improvements, renewal ($/SF)", 0.0, 200.0, value=float(L["ti_renew"]), step=1.0,
                   key=f"{K}_tir_{sub or ''}")
        bump = w(l3.number_input, "Annual rent bumps (%)", 0.0, 6.0, value=L["bump"] * 100, step=0.25, key=f"{K}_bump_{sub or ''}")
        conc = w(st.number_input, "Current free rent / concessions (% of rent)", 0.0, 50.0, value=0.0, step=0.5,
                 key=f"{K}_conc")
        leasing = {"renewal_prob": renew / 100, "downtime": down, "term": term, "ti_new": ti_new,
                   "ti_renew": ti_ren, "bump": bump / 100}
        if t == "industrial":
            if w(st.selectbox, "Clear height", ["Not sure", "Under 24 ft", "24–32 ft", "32 ft+"],
                 key=f"{K}_clear") == "Under 24 ft":
                warnings.append("Clear heights under 24 ft limit modern distribution users and narrow the buyer pool.")
        elif w(st.selectbox, "Parking (spaces per 1,000 SF)", ["Not sure", "Under 3", "3–4", "4+"],
               key=f"{K}_park") == "Under 3":
            warnings.append("Low parking ratios limit which tenants can lease the space and can slow re-leasing.")
        growth, months = growth_leaseup_inputs(K, t)
        capex = condition_inputs(K, ui["condition"])
        comps = comps_input(t, t)
        disc = discount_override_input(K)

    if not (review and opex is not None):
        return False, None
    q = quality.check(t, market, review["total_sf"], review["gpr_annual"], review["physical_vacancy"], opex,
                      current_tax=bill, tax_rate=taxes["tax_rate_override"], review=review, other_income=other)
    ok = quality_gate(K, q)
    if not q["critical"]:
        ok = w(st.checkbox, "I've reviewed the rent roll above and it's correct.", value=False, key=f"{K}_reviewed")
    cls = CLASS_OPTIONS[ss.get("p_d_class", list(CLASS_OPTIONS)[0])]
    inp = Inputs(sector=t, market=market, size=review["total_sf"], gpr=review["gpr_annual"],
                 physical_vacancy=review["physical_vacancy"], opex=opex, opex_breakdown=breakdown,
                 other_income=other, pclass=cls, suites=review["suites"], leasing=leasing, current_tax=bill,
                 subtype=ss.get("p_d_subtype") if t == "industrial" else None,
                 actual_recoveries=recov, nonrecoverable=nonrec, concessions=conc / 100, capex=capex,
                 rent_growth=growth, leaseup_months=months, comps=comps, discount_override=disc,
                 quality_grade=q["grade"], **taxes)
    owner = [("Market", market), ("Rentable SF", f"{inp.size:,.0f}"), ("Annual potential rent", money(inp.gpr)),
             ("Vacancy today", f"{inp.physical_vacancy:.1%}"), ("Operating expenses", money(opex)),
             ("Current tax bill", money(bill) if bill else "Not provided"), ("Building class", cls or "Not sure"),
             ("Input quality grade", q["grade"])]
    return ok, {"inp": inp, "owner": owner, "warnings": warnings, "grade": q["grade"]}


def d_home_financials():
    K = "p_d_h"
    st.markdown("On Zillow or Redfin, search your area and filter to *Sold*.")
    n = w(st.radio, "How many sales will you enter?", [3, 4, 5], key=f"{K}_n", horizontal=True)
    comps = []
    for i in range(n):
        with st.container(border=True):
            st.markdown(f"**Sale {i + 1}**")
            r1 = st.columns([2, 1.2, 1.2])
            addr = w(r1[0].text_input, "Address", value="", key=f"{K}_a{i}", placeholder="e.g. 210 Pine St")
            price = w(r1[1].number_input, "Sale price ($)", min_value=0.0, value=None, step=5000.0, key=f"{K}_p{i}",
                      format="%.0f")
            sdate = w(r1[2].date_input, "Sale date", value=None, max_value=date.today(),
                      min_value=date.today() - timedelta(days=3 * 365), key=f"{K}_d{i}", format="MM/DD/YYYY")
            r2 = st.columns([1, 0.8, 0.8, 1, 1.6])
            csf = w(r2[0].number_input, "Sq ft", min_value=0, value=None, step=50, key=f"{K}_s{i}")
            cb = w(r2[1].number_input, "Beds", 0, 15, value=None, step=1, key=f"{K}_b{i}")
            cba = w(r2[2].number_input, "Baths", 0.0, 15.0, value=None, step=0.5, key=f"{K}_ba{i}")
            cy = w(r2[3].number_input, "Year built", 1800, 2027, value=None, step=1, key=f"{K}_y{i}")
            cond = w(r2[4].selectbox, "Condition vs. mine", list(home.CONDITION_SHIFT), index=1, key=f"{K}_c{i}")
            if all(v is not None for v in (price, sdate, csf, cb, cba, cy)) and price > 0 and csf > 0:
                comps.append({"address": addr or f"Sale {i + 1}", "price": float(price), "sale_date": sdate,
                              "sf": float(csf), "beds": float(cb), "baths": float(cba), "year_built": int(cy),
                              "condition": cond})
    with st.expander("Add other information to improve accuracy", icon=":material/tune:"):
        appr = w(st.number_input, "Home price change in your area over the past year (%)", -20.0, 20.0, value=0.0,
                 step=0.5, key=f"{K}_appr", help="Older sales are adjusted forward to today's prices at this rate.")
        capex = w(st.number_input, "Repairs a buyer would expect you to fix ($)", min_value=0.0, value=0.0,
                  step=1000.0, key=f"{K}_capex", format="%.0f")
        rent = w(st.number_input, "Monthly rent, if rented ($)", min_value=0.0, value=0.0, step=50.0, key=f"{K}_rent",
                 format="%.0f")
        costs = w(st.number_input, "Annual taxes + insurance + HOA + maintenance ($)", min_value=0.0, value=0.0,
                  step=500.0, key=f"{K}_costs", format="%.0f")
    if comps:
        st.caption(f"{len(comps)} complete sale(s)" + ("" if len(comps) >= 3 else " — need at least 3."))
    subject = {"sf": ss["p_d_h_sf"], "beds": ss["p_d_h_beds"], "baths": ss["p_d_h_baths"],
               "year_built": int(ss["p_d_h_yr"])}
    return len(comps) >= 3, {"home": True, "subject": subject, "comps": comps, "appr": appr, "capex": capex,
                             "rent": rent, "costs": costs}


def d_step3():
    t = ss["p_d_type"]
    p = ss.get("d_payload")
    market = ss["p_d_market"]
    city, full = place(market)
    styles.progress(3, "Review & Estimate", right_chip=True)
    styles.title("Your underwriting is ready", "Check the summary, then run the full model.")
    if not p:
        st.button("Back", key="d3_back0", on_click=go, args=("d_step", 2))
        return
    if p.get("home"):
        return d_home_result(p, full)
    inp = p["inp"]
    mf = t == "multifamily"
    occ = 1 - inp.physical_vacancy
    styles.summary_card("PROPERTY SUMMARY", f"{city} {TYPES[t][0]}{'' if mf else ' Property'}",
                        f"{full} · {inp.size:,.0f} {'units' if mf else 'SF'}", TYPES[t][2], [
                            ("Potential annual rent", money(inp.gpr),
                             f"{money(inp.gpr / inp.size / 12)} / unit / month" if mf else f"${inp.gpr / inp.size:,.2f} / SF / year"),
                            ("Current occupancy", f"{occ:.0%}", f"{inp.size * occ:,.0f} {'units' if mf else 'SF'} occupied"),
                            ("Input quality", f"Grade {p['grade']}", {"A": "Consistent, normal ranges",
                                                                     "B": "A few items to double-check",
                                                                     "C": "Several unusual inputs"}[p["grade"]]),
                            ("Operating expenses", money(inp.opex), "Before taxes, management and reserves"),
                        ])
    c1, c2 = st.columns([1, 3])
    c1.button("Back", key="d3_back", use_container_width=True, on_click=go, args=("d_step", 2))
    sig = repr(asdict(inp))
    if c2.button("Run detailed underwriting", type="primary", use_container_width=True, key="go_d"):
        try:
            ss["_d_res"] = (sig, underwrite(inp), None)
        except ValuationError as e:
            ss["_d_res"] = (sig, None, str(e))
    saved = ss.get("_d_res")
    if not saved or saved[0] != sig:
        return
    if saved[2]:
        st.error(saved[2])
        return
    show_results(saved[1], inp, f"{TYPES[t][0]}, {market}", "Per unit" if mf else "Per SF", p["warnings"], p["owner"])


def show_results(r, inp, title, per_label, extra_warnings, owner_inputs):
    w_ = r["weights"]
    styles.result_panel(r["low"], r["value"], r["high"], [
        (per_label, money(r["per_unit"])), ("Cap rate", f"{r['cap_rate']:.2%}"),
        ("Cap rate confidence", r["cap_confidence"]), ("Discount rate", f"{r['discount']:.2%}"),
    ], range_note=r["range_label"])
    for msg in r["warnings"] + extra_warnings:
        st.warning(msg)
    show_reasonableness(checks.reasonableness(r, inp), inp)
    if r["notes"]:
        st.markdown("**What the model did with your property:**\n" + "\n".join(f"- {n}" for n in r["notes"]))

    with st.expander("How the estimate was reconciled", expanded=True):
        rows = [("Direct capitalization", r["direct_cap"], w_["dc"]), ("Discounted cash flow", r["dcf_value"], w_["dcf"])]
        if w_["sales"]:
            rows.append(("Sales comparison", r["sales_value"], w_["sales"]))
        st.markdown("| Method | Value | Weight | Contribution |\n|---|---:|---:|---:|\n" +
                    "\n".join(f"| {n} | {money(v)} | {wt:.0f}% | {money(v * wt / 100)} |" for n, v, wt in rows) +
                    f"\n| **Estimate** | | 100% | **{money(r['value'])}** |")
        st.markdown("**Why these weights** (both start at 50%):\n" + "\n".join(f"- {x}" for x in r["weight_reasons"]))

    with st.expander("How each method got its number"):
        cur, stab = r["current_noi"], r["stabilized_noi"]
        lines = [("Occupancy", "occupancy"), ("Potential rent", "potential_rent"), ("Vacancy", "vacancy"),
                 ("Collection loss / concessions", "credit_loss"), ("Other income", "other_income"),
                 ("Expense reimbursements", "recoveries"), ("Operating expenses", "opex"),
                 ("Management", "management"), ("Reserves", "reserves"),
                 ("Unreimbursed expenses", "nonrecoverable"), ("Property taxes", "taxes"),
                 ("**Net operating income**", "noi")]
        fmt = lambda k, v: f"{v:.0%}" if k == "occupancy" else money(v)
        st.markdown("**Current vs. stabilized NOI** (one year, today's dollars)\n\n| | Current | Stabilized |\n"
                    "|---|---:|---:|\n" + "\n".join(f"| {lbl} | {fmt(k, cur[k])} | {fmt(k, stab[k])} |"
                                                    for lbl, k in lines
                                                    if not (k in ("recoveries", "nonrecoverable") and inp.sector == "multifamily")))
        st.markdown(
            "**Direct capitalization**  \n"
            f"Stabilized NOI ÷ cap rate = {money(stab['noi'])} ÷ {r['cap_rate']:.2%} = {money(stab['noi'] / r['cap_rate'])}  \n"
            f"− lease-up costs and lost rent {money(r['leaseup_cost'] + r['lost_rent'])} − repairs {money(r['one_time'])} "
            f"− lease-up risk allowance {money(r['allowance'])} = **{money(r['direct_cap'])}**\n\n"
            "**Discounted cash flow**" + (" (lease by lease, month by month)" if inp.sector != "multifamily" else "") + "  \n"
            f"PV of 10 years of cash flow {money(r['pv_cf'])} + PV of a year-10 sale at a {r['exit_cap']:.2%} cap "
            f"{money(r['dcf_value'] + r['allowance'] - r['pv_cf'])} − lease-up risk allowance {money(r['allowance'])} "
            f"= **{money(r['dcf_value'])}**")
        if r["sales_value"]:
            c = r["comps"]
            st.markdown(f"**Sales comparison**  \n{c['n']} sale(s), class-adjusted median {money(c['per_unit'])} "
                        f"{per_label.lower()} × {inp.size:,.0f} − lease-up and repairs = **{money(r['sales_value'])}**")

    with st.expander("Cap rate evidence and discount rate build-up"):
        ev = r["cap_evidence"]
        st.markdown(f"**Cap rate confidence: {r['cap_confidence']}** — {ev['why']}")
        st.caption(ev.get("scope", ""))
        if ev["points"]:
            st.markdown("| Source | Period | Cap rate |\n|---|---|---:|\n" +
                        "\n".join(f"| {pt[1]} | Q{pt[3]} {pt[2]} | {pt[0]:.2%} |" for pt in ev["points"]))
        st.markdown("**Discount rate** — the annual return a buyer requires, built up from evidence:\n\n"
                    "| Component | Rate | Basis |\n|---|---:|---|\n" +
                    "\n".join(f"| {n} | {(f'{v:.2%}' if i == 0 else bps(v))} | {b} |"
                              for i, (n, v, b) in enumerate(r["discount_rows"])) +
                    f"\n| **Discount rate** | **{r['discount']:.2%}** | |")
        sd = r["sens_disc_exit"]
        st.markdown("**DCF value: discount rate × exit cap rate**")
        st.dataframe(pd.DataFrame({f"{x:.2%} exit": [money(row["values"][j]) for row in sd["rows"]]
                                   for j, x in enumerate(sd["exits"])},
                                  index=[f"{row['disc']:.2%} discount" for row in sd["rows"]]), use_container_width=True)

    if r["lease_events"]:
        with st.expander("Lease rollover schedule"):
            L = r["leasing_assumptions"]
            st.caption(f"At each expiration: {L['renewal_prob']:.0%} chance of renewal; otherwise {L['downtime']:.0f} "
                       f"months vacant, then a new tenant. Renewals ${L['ti_renew']:.0f}/SF, {L['lc_renew']:.0%} commission; "
                       f"new leases ${L['ti_new']:.0f}/SF, {L['lc_new']:.0%} commission, {L['free_new']:.0f} mo free. "
                       f"Rents reset to market and step {L['bump']:.1%}/yr. Results are probability-weighted.")
            st.dataframe(pd.DataFrame([{"Suite": e["suite"], "Tenant": e["tenant"], "Month": e["event_month"],
                                        "Event": e["event"], "Rent $/SF": f"${e['rent_psf']:,.2f}"}
                                       for e in r["lease_events"]]).sort_values("Month"),
                         use_container_width=True, hide_index=True)

    with st.expander("10-year cash flow"):
        rows = [("Occupancy", "occupancy"), ("Potential rent", "potential_rent"), ("Vacancy", "vacancy"),
                ("Free rent", "free_rent"), ("Collection loss", "credit_loss"), ("Reimbursements", "recoveries"),
                ("Effective gross income", "egi"), ("Operating expenses", "opex"), ("Management", "management"),
                ("Reserves", "reserves"), ("Property taxes", "taxes"), ("Net operating income", "noi"),
                ("Improvements + commissions" if inp.sector != "multifamily" else "Leasing costs", "leasing_costs"),
                ("One-time costs", "one_time"), ("Cash flow", "cash_flow")]
        if inp.sector == "multifamily":
            rows = [x for x in rows if x[1] not in ("free_rent", "recoveries")]
        st.dataframe(pd.DataFrame({f"Year {f['year']}": [(f"{f[k]:.0%}" if k == "occupancy" else money(f[k]))
                                                         for _, k in rows] for f in r["flows"]},
                                  index=[lbl for lbl, _ in rows]), use_container_width=True)

    with st.expander("Value range and sensitivity"):
        s = r["scenarios"]
        st.markdown(f"**{r['range_label']}.** Downside {money(s['Downside'])} · Base {money(s['Base'])} · "
                    f"Upside {money(s['Upside'])}.")
        st.caption(r["sources"]["Value range"])
        sens = r["sensitivity"]
        st.markdown("**Reconciled value: going-in cap rate × rent growth** (each cell re-runs the full model)")
        st.dataframe(pd.DataFrame({f"{g:.1%} growth": [money(row["values"][j]) for row in sens["rows"]]
                                   for j, g in enumerate(sens["growths"])},
                                  index=[f"{row['cap']:.2%} cap" for row in sens["rows"]]), use_container_width=True)

    with st.expander("Assumptions and sources"):
        for k, v in r["sources"].items():
            st.markdown(f"- **{k}:** {v}")

    st.download_button("Download underwriting model (Excel)", export.build(r, title, owner_inputs),
                       f"{title.lower().replace(' ', '_').replace(',', '')}_underwriting.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_d",
                       use_container_width=True)


def d_home_result(p, full):
    subj, comps = p["subject"], p["comps"]
    styles.summary_card("PROPERTY SUMMARY", f"{full.split(',')[0]} Home", f"{full} · {subj['sf']:,.0f} SF", "home", [
        ("Bedrooms / baths", f"{subj['beds']:.0f} / {subj['baths']:g}", f"Built {subj['year_built']}"),
        ("Comparable sales", str(len(comps)), "adjusted to your home"),
    ])
    c1, c2 = st.columns([1, 3])
    c1.button("Back", key="d3h_back", use_container_width=True, on_click=go, args=("d_step", 2))
    if c2.button("Run the comparison", type="primary", use_container_width=True, key="go_dh"):
        ss["_dh_done"] = True
    if not ss.get("_dh_done"):
        return
    r = home.estimate_home(subj, [dict(c) for c in comps], appreciation=p["appr"] / 100, capex=p["capex"])
    styles.result_panel(r["low"], r["value"], r["high"], [
        ("Per sq ft", money(r["per_sf"])), ("Sales compared", str(len(r["comps"]))),
        ("Range width", f"{r['spread_pct']:.0%}"), ("Approach", "Sales comparison"),
    ], range_note="Range spans the lowest to highest adjusted sale — not a statistical confidence interval")
    if r["spread_pct"] > 0.20:
        st.warning(f"Your adjusted comps are {r['spread_pct']:.0%} apart. Sales closer to your home in size, age and "
                   "location would tighten the range.")
    for c in r["comps"]:
        if c["flags"]:
            st.info(f"**{c['address']}:** " + ", ".join(c["flags"]) + " — weighted less.")
    with st.expander("How we got this number", expanded=True):
        names = [c["address"] for c in r["comps"]]
        rows = [("Sale price", [c["price"] for c in r["comps"]])]
        for line in r["comps"][0]["lines"]:
            rows.append((line, [c["lines"][line] for c in r["comps"]]))
        rows.append(("**Adjusted price**", [c["adjusted"] for c in r["comps"]]))
        body = "| | " + " | ".join(names) + " |\n|---|" + "---:|" * len(names) + "\n"
        body += "\n".join(f"| {k} | " + " | ".join(money(v) for v in vals) + " |" for k, vals in rows)
        body += "\n| **Weight** | " + " | ".join(f"**{c['weight']:.0%}**" for c in r["comps"]) + " |"
        st.markdown(body)
        st.caption(r["assumptions"])
    if p["rent"]:
        rc = home.rental_check(r["value"], p["rent"], p["costs"])
        st.markdown(f"**As a rental:** gross yield {rc['gross_yield']:.1%} · net yield {rc['net_yield']:.1%} · "
                    f"price-to-rent {rc['price_to_rent']:.1f}×")


# ======================================================================
# Page
# ======================================================================
_mode = ss.get("mode")
if _mode is None:
    landing()
elif _mode == "quick":
    quick_flow()
else:
    detailed_flow()
styles.fineprint(DISCLAIMER)
