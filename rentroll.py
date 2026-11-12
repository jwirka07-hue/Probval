"""
Rent roll readers.

Apartments: unit-level rows → a floorplan summary. Vacant units are priced at the floorplan's market rent
(owner override, else the file's Market Rent column, else the floorplan's average occupied rent — never a
property-wide average when unit types differ).

Commercial: suite-level rows → a clean suite table the owner reviews and edits before valuation, with
duplicate-suite checks, rentable-area reconciliation, lease types per suite and market-rent overrides.
"""
from __future__ import annotations

import pandas as pd

VACANT_WORDS = ("vacant", "down", "model", "offline", "non-rev", "admin")


def _norm(s) -> str:
    return str(s).strip().lower().replace("_", " ")


def _find(columns, aliases, contains=None, exclude=()):
    norm = {_norm(c): c for c in columns}
    for a in aliases:
        if a in norm:
            return norm[a]
    if contains:
        for n, c in norm.items():
            if contains in n and not any(x in n for x in exclude):
                return c
    return None


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")


def read_file(uploaded) -> pd.DataFrame:
    name = getattr(uploaded, "name", str(uploaded)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    return pd.read_csv(uploaded)


# ======================================================================
# Apartments
# ======================================================================
MF = {
    "unit": ["unit", "unit #", "unit number", "unit no", "apt", "apartment", "unit id"],
    "type": ["unit type", "type", "floorplan", "floor plan", "plan", "bed/bath", "beds", "bedrooms", "bd/ba"],
    "rent": ["rent", "current rent", "in-place rent", "in place rent", "actual rent", "lease rent",
             "contract rent", "monthly rent"],
    "market": ["market rent", "market", "asking rent"],
    "status": ["status", "unit status", "occupancy", "occupancy status"],
}


def summarize(df: pd.DataFrame) -> dict:
    df = df.dropna(how="all").copy()
    if len(df) == 0:
        raise ValueError("The file has no unit rows.")
    rent_col = _find(df.columns, MF["rent"], contains="rent", exclude=("market", "asking"))
    if rent_col is None:
        raise ValueError("Couldn't find a rent column. Name it 'Rent' and try again.")
    warnings, flags = [], []
    unit_col, type_col = _find(df.columns, MF["unit"]), _find(df.columns, MF["type"])
    mkt_col, status_col = _find(df.columns, MF["market"]), _find(df.columns, MF["status"])

    rent = _money(df[rent_col]).fillna(0)
    if (rent < 0).any():
        flags.append(("warn", f"{int((rent < 0).sum())} unit(s) had a negative rent and were treated as vacant."))
        rent = rent.clip(lower=0)
    if status_col:
        status = df[status_col].astype(str).str.lower()
        vacant = status.apply(lambda s: any(w in s for w in VACANT_WORDS)) | (rent <= 0)
    else:
        vacant = rent <= 0
        warnings.append("No status column — units with $0 rent were treated as vacant.")

    if unit_col:
        dup = df[unit_col].astype(str).str.strip().duplicated(keep=False) & df[unit_col].notna()
        if dup.any():
            flags.append(("critical", f"{int(dup.sum())} rows share a unit number "
                                      f"({', '.join(sorted(df.loc[dup, unit_col].astype(str).unique())[:5])}). "
                                      "Remove duplicates so units aren't counted twice."))

    ftype = df[type_col].astype(str).str.strip() if type_col else pd.Series("All units", index=df.index)
    if not type_col:
        flags.append(("info", "No unit type column — all units are treated as one floorplan. Add a Unit Type "
                              "column (e.g. 1x1, 2x2) so vacant units are priced by type."))
    market = _money(df[mkt_col]) if mkt_col else pd.Series(float("nan"), index=df.index)

    plans = []
    for t, idx in ftype.groupby(ftype).groups.items():
        occ = idx[~vacant.loc[idx].values]
        avg_occ = float(rent.loc[occ].mean()) if len(occ) else float("nan")
        mkt = float(market.loc[idx].dropna().mean()) if market.loc[idx].notna().any() else float("nan")
        plans.append({"Unit type": t, "Units": int(len(idx)), "Occupied": int(len(occ)),
                      "Avg in-place rent": round(avg_occ, 0) if avg_occ == avg_occ else None,
                      "Market rent": round(mkt, 0) if mkt == mkt else None})
    if int((~vacant).sum()) == 0:
        raise ValueError("Every unit looks vacant. Check that the rent column has amounts.")
    return {"plans": pd.DataFrame(plans), "warnings": warnings, "flags": flags,
            "occupied_rent_monthly": float(rent[~vacant].sum())}


def plans_to_totals(plans: pd.DataFrame, occupied_rent_monthly: float | None = None) -> dict:
    """Totals from the (possibly edited) floorplan table. Vacant units: market rent → floorplan average → property average."""
    p = plans.copy()
    p["Units"] = pd.to_numeric(p["Units"], errors="coerce").fillna(0)
    p["Occupied"] = pd.to_numeric(p["Occupied"], errors="coerce").fillna(0)
    p["Avg in-place rent"] = pd.to_numeric(p["Avg in-place rent"], errors="coerce")
    p["Market rent"] = pd.to_numeric(p["Market rent"], errors="coerce")
    units, occupied = float(p["Units"].sum()), float(p["Occupied"].sum())
    if units <= 0:
        raise ValueError("The floorplan table has no units.")
    if (p["Occupied"] > p["Units"]).any():
        raise ValueError("A floorplan shows more occupied units than total units.")
    if occupied <= 0:
        raise ValueError("No occupied units — the property has no income to value.")
    prop_avg = float((p["Avg in-place rent"].fillna(0) * p["Occupied"]).sum() / occupied)
    notes, gpr_m, loss_to_lease = [], 0.0, 0.0
    for _, r in p.iterrows():
        inplace = r["Avg in-place rent"] if pd.notna(r["Avg in-place rent"]) else prop_avg
        if pd.notna(r["Market rent"]) and r["Market rent"] > 0:
            vac_rent, how = r["Market rent"], "market rent"
            loss_to_lease += (r["Market rent"] - inplace) * r["Occupied"]
        elif pd.notna(r["Avg in-place rent"]):
            vac_rent, how = r["Avg in-place rent"], "the floorplan's average occupied rent"
        else:
            vac_rent, how = prop_avg, "the property average (no occupied units of this type)"
        vac = r["Units"] - r["Occupied"]
        gpr_m += inplace * r["Occupied"] + vac_rent * vac
        if vac > 0:
            label = "" if r["Unit type"] == "All units" else f"{r['Unit type']} "
            notes.append(f"{int(vac)} vacant {label}unit(s) priced at {how} (${vac_rent:,.0f}).")
    gpr_m_occ = occupied_rent_monthly if occupied_rent_monthly else None
    return {"units": units, "occupied": occupied, "physical_vacancy": 1 - occupied / units,
            "gpr_annual": gpr_m * 12, "avg_rent": gpr_m / units, "loss_to_lease_annual": loss_to_lease * 12,
            "notes": notes, "_check_occ_rent": gpr_m_occ}


def template() -> pd.DataFrame:
    return pd.DataFrame({"Unit": ["101", "102", "103"], "Unit Type": ["1x1", "2x2", "1x1"],
                         "Rent": [1450, 1750, 0], "Market Rent": [1500, 1800, 1500],
                         "Status": ["Occupied", "Occupied", "Vacant"]})


# ======================================================================
# Commercial (industrial / office)
# ======================================================================
CM = {
    "suite": ["suite", "suite #", "unit", "space", "suite number", "unit #", "bay"],
    "tenant": ["tenant", "tenant name", "lessee", "occupant"],
    "sf": ["sf", "rsf", "nrsf", "square feet", "sq ft", "size", "rentable sf", "leased sf", "area"],
    "annual": ["annual rent", "annual base rent", "base rent", "rent", "yearly rent", "abr"],
    "monthly": ["monthly rent", "monthly base rent", "rent/month", "rent per month"],
    "psf": ["rent/sf", "rent psf", "$/sf", "rent per sf", "annual rent/sf", "rate"],
    "market": ["market rent", "market rent/sf", "market rent psf", "market $/sf"],
    "type": ["lease type", "type", "lease structure", "structure", "expense structure", "recovery type"],
    "end": ["lease end", "lease expiration", "expiration", "expires", "lease exp", "end date"],
}
LEASE_LABELS = {"nnn": "NNN", "base_year": "Base Year", "gross": "Gross"}
LABEL_TO_KEY = {v: k for k, v in LEASE_LABELS.items()}


def classify_lease(v) -> str | None:
    t = str(v).lower().strip()
    if t in ("", "nan", "none"):
        return None
    if any(k in t for k in ("base", "modified", "mg", "stop")):
        return "base_year"
    if any(k in t for k in ("nnn", "triple", "net", "nn")):
        return "nnn"
    if any(k in t for k in ("gross", "fsg", "full")):
        return "gross"
    return None


def parse_commercial(df: pd.DataFrame) -> pd.DataFrame:
    """Raw file → editable suite table (one row per suite)."""
    df = df.dropna(how="all").copy()
    sf_col = _find(df.columns, CM["sf"])
    if sf_col is None:
        raise ValueError("Couldn't find a square footage column. Name it 'SF' and try again.")
    sf = _money(df[sf_col])
    mcol, acol, pcol = _find(df.columns, CM["monthly"]), _find(df.columns, CM["annual"]), _find(df.columns, CM["psf"])
    if mcol:
        rent = _money(df[mcol]) * 12
    elif pcol:
        rent = _money(df[pcol]) * sf
    elif acol:
        rent = _money(df[acol])
    else:
        raise ValueError("Couldn't find a rent column. Use 'Annual Rent', 'Monthly Rent' or 'Rent/SF'.")
    scol, tcol = _find(df.columns, CM["suite"]), _find(df.columns, CM["tenant"])
    mkcol, tycol, ecol = _find(df.columns, CM["market"]), _find(df.columns, CM["type"]), _find(df.columns, CM["end"])
    tenant = df[tcol].astype(str).str.strip() if tcol else pd.Series("", index=df.index)
    out = pd.DataFrame({
        "Suite": df[scol].astype(str).str.strip() if scol else [str(i + 1) for i in range(len(df))],
        "Tenant": tenant.replace({"nan": ""}),
        "SF": sf,
        "Annual Rent": rent.fillna(0),
        "Lease Type": (df[tycol].map(classify_lease).map(LEASE_LABELS) if tycol else None),
        "Lease End": pd.to_datetime(df[ecol], errors="coerce").dt.date if ecol else None,
        "Market Rent $/SF": _money(df[mkcol]) if mkcol else float("nan"),
    })
    out["Vacant"] = out["Tenant"].str.lower().str.contains("vacant") | (out["Annual Rent"] <= 0)
    return out.reset_index(drop=True)


def review_commercial(table: pd.DataFrame, building_sf: float | None, default_type: str,
                      market_rent_psf: float | None, today=None) -> dict:
    """Validate the (possibly edited) suite table. Returns suites for the model plus review flags."""
    today = pd.Timestamp(today or pd.Timestamp.today().normalize()).date()
    t = table.copy()
    t["SF"] = pd.to_numeric(t["SF"], errors="coerce")
    t["Annual Rent"] = pd.to_numeric(t["Annual Rent"], errors="coerce").fillna(0)
    t["Market Rent $/SF"] = pd.to_numeric(t["Market Rent $/SF"], errors="coerce")
    flags = []

    bad = t["SF"].isna() | (t["SF"] <= 0)
    if bad.any():
        flags.append(("warn", f"{int(bad.sum())} row(s) have no valid square footage and are excluded "
                              f"(suites {', '.join(t.loc[bad, 'Suite'].astype(str).head(5))})."))
        t = t[~bad]
    if len(t) == 0:
        raise ValueError("No suites have valid square footage.")
    if (t["Annual Rent"] < 0).any():
        flags.append(("warn", "Negative rents were treated as $0 (vacant)."))
        t["Annual Rent"] = t["Annual Rent"].clip(lower=0)
    t["Vacant"] = t["Vacant"].fillna(False).astype(bool) | (t["Annual Rent"] <= 0)

    # Duplicate suites
    sid = t["Suite"].astype(str).str.strip().str.lower()
    dup = sid.duplicated(keep=False) & (sid != "")
    if dup.any():
        flags.append(("critical", f"Suite numbers appear more than once: {', '.join(sorted(t.loc[dup, 'Suite'].astype(str).unique())[:6])}. "
                                  "Merge or delete duplicates in the table so space isn't counted twice."))
    same = t.duplicated(subset=["Tenant", "SF", "Annual Rent"], keep=False) & ~t["Vacant"] & (t["Tenant"] != "")
    if same.any():
        flags.append(("warn", f"{int(same.sum())} rows have the same tenant, size and rent — possible duplicate entries."))

    # Rentable area reconciliation
    roll_sf = float(t["SF"].sum())
    recon = None
    if building_sf:
        diff = building_sf - roll_sf
        pct = diff / building_sf
        recon = {"building_sf": building_sf, "roll_sf": roll_sf, "diff": diff, "pct": pct}
        if abs(pct) <= 0.02:
            flags.append(("info", f"Rentable area reconciles: rent roll {roll_sf:,.0f} SF vs. building {building_sf:,.0f} SF."))
        elif diff > 0:
            sev = "critical" if pct > 0.10 else "warn"
            flags.append((sev, f"The rent roll covers {roll_sf:,.0f} SF but the building is {building_sf:,.0f} SF. "
                               f"The missing {diff:,.0f} SF ({pct:.0%}) is added as vacant space."))
        else:
            flags.append(("critical", f"The rent roll totals {roll_sf:,.0f} SF — {-diff:,.0f} SF more than the building's "
                                      f"{building_sf:,.0f} SF. Fix duplicate or mis-sized suites before valuing."))
    else:
        flags.append(("info", "Enter the building's rentable SF to reconcile it against the rent roll."))

    # Leases
    occ = t[~t["Vacant"]]
    if len(occ) == 0:
        raise ValueError("Every suite is vacant — the building has no income to value.")
    avg_psf = float(occ["Annual Rent"].sum() / occ["SF"].sum())
    mkt_default = market_rent_psf or avg_psf
    unknown = occ["Lease Type"].isna() | ~occ["Lease Type"].isin(list(LABEL_TO_KEY))
    if unknown.any():
        flags.append(("warn", f"{int(unknown.sum())} occupied suite(s) have no recognized lease type and are modeled as "
                              f"{LEASE_LABELS[default_type]} (your default). Set each one in the table if that's wrong."))
    ends = pd.to_datetime(occ["Lease End"], errors="coerce")
    expired = ends.notna() & (ends.dt.date < today)
    if expired.any():
        flags.append(("warn", f"{int(expired.sum())} lease(s) have already expired but the suite is occupied — modeled "
                              "as month-to-month, rolling in month 1."))
    no_end = ends.isna()
    if no_end.any():
        flags.append(("warn", f"{int(no_end.sum())} occupied suite(s) have no lease end date — assumed to expire in 3 years."))
    if market_rent_psf is None and t["Market Rent $/SF"].isna().all():
        flags.append(("info", f"No market rent given — new and renewal leases are priced at the average in-place rent "
                              f"(${avg_psf:,.2f}/SF). Enter a market rent if in-place rents are above or below market."))

    suites = []
    for _, r in t.iterrows():
        key = LABEL_TO_KEY.get(r["Lease Type"]) if isinstance(r["Lease Type"], str) else None
        end = pd.to_datetime(r["Lease End"], errors="coerce")
        months_left = None
        if not r["Vacant"]:
            if pd.isna(end):
                months_left = 36
            else:
                months_left = max(1, round((end.date() - today).days / 30.44))
        suites.append({
            "suite": str(r["Suite"]), "tenant": r["Tenant"], "sf": float(r["SF"]),
            "rent": 0.0 if r["Vacant"] else float(r["Annual Rent"]),
            "lease_type": key or default_type, "months_left": months_left, "vacant": bool(r["Vacant"]),
            "market_psf": float(r["Market Rent $/SF"]) if pd.notna(r["Market Rent $/SF"]) else mkt_default,
        })
    if recon and recon["diff"] > 0 and recon["pct"] > 0.02:
        suites.append({"suite": "Unlisted area", "tenant": "", "sf": recon["diff"], "rent": 0.0,
                       "lease_type": default_type, "months_left": None, "vacant": True, "market_psf": mkt_default})

    total_sf = sum(s["sf"] for s in suites)
    occ_rent = sum(s["rent"] for s in suites)
    top = max(s["rent"] for s in suites) / occ_rent if occ_rent else 0
    roll3 = sum(s["rent"] for s in suites if s["months_left"] is not None and s["months_left"] <= 36) / occ_rent
    walt = sum(s["rent"] * s["months_left"] for s in suites if s["months_left"]) / occ_rent / 12
    leased_sf = sum(s["sf"] for s in suites if not s["vacant"])
    return {
        "suites": suites, "flags": flags, "total_sf": total_sf, "leased_sf": leased_sf,
        "physical_vacancy": 1 - leased_sf / total_sf, "occupied_rent": occ_rent, "avg_rent_psf": avg_psf,
        "gpr_annual": occ_rent + sum(s["sf"] * s["market_psf"] for s in suites if s["vacant"]),
        "top_tenant_share": top, "rollover_3yr": roll3, "walt": walt, "tenants": int((~t["Vacant"]).sum()),
        "critical": [m for sev, m in flags if sev == "critical"], "recon": recon,
    }


def commercial_template() -> pd.DataFrame:
    return pd.DataFrame({
        "Suite": ["100", "200", "300"], "Tenant": ["Acme Logistics", "Blue Ridge Supply", "Vacant"],
        "SF": [60000, 25000, 15000], "Annual Rent": [480000, 212500, 0],
        "Lease Type": ["NNN", "Base Year", ""], "Lease End": ["2029-06-30", "2027-03-31", ""],
        "Market Rent $/SF": [8.50, 8.75, 8.50],
    })
